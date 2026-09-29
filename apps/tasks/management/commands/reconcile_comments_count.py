from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Max
from django.db.models.functions import Coalesce

from apps.tasks.models import Comment, Task, comments_per_task


class Command(BaseCommand):
    help = (
        "Set each task's comments_count to the number of its comments, in id batches. "
        "Run after a deploy, once no replica runs code older than the counter."
    )

    def add_arguments(self, parser):
        parser.add_argument("--batch-size", type=int, default=1_000)

    def handle(self, *args, batch_size, **options):
        if batch_size < 1:
            raise CommandError("--batch-size must be >= 1.")
        actual = Coalesce(comments_per_task(Comment.objects.all()), 0)
        last_id = Task.objects.aggregate(last=Max("pk"))["last"] or 0
        corrected = 0
        for start in range(0, last_id, batch_size):
            batch = Task.objects.filter(pk__gt=start, pk__lte=start + batch_size)
            with transaction.atomic():
                # Counting after the lock sees every committed comment; changes that
                # wait for the lock apply on top of the corrected value.
                list(batch.order_by("pk").select_for_update().values_list("pk", flat=True))
                corrected += batch.exclude(comments_count=actual).update(comments_count=actual)
        self.stdout.write(f"Corrected tasks: {corrected}")
