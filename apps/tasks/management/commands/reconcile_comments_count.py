from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction
from django.db.models import Max

from apps.tasks.models import Task

# Writes only the tasks whose counter is off.
RECONCILE = """
UPDATE tasks_task SET comments_count = actual.amount
FROM (
    SELECT task.id, count(comment.id) AS amount
    FROM tasks_task AS task LEFT JOIN tasks_comment AS comment ON comment.task_id = task.id
    WHERE task.id > %s AND task.id <= %s
    GROUP BY task.id
) AS actual
WHERE tasks_task.id = actual.id AND tasks_task.comments_count <> actual.amount
"""


class Command(BaseCommand):
    help = (
        "Set each task's comments_count to the number of its comments. Run after a deploy "
        "once all replicas of the old code are replaced: code from before the counter adds "
        "comments without counting them. Safe on a live database and repeatable: tasks are "
        "handled in id batches, each a short transaction."
    )

    def add_arguments(self, parser):
        parser.add_argument("--batch-size", type=int, default=1_000)

    def handle(self, *args, batch_size, **options):
        if batch_size < 1:
            raise CommandError("--batch-size must be >= 1.")
        last_id = Task.objects.aggregate(last=Max("pk"))["last"] or 0
        corrected = 0
        for start in range(0, last_id, batch_size):
            end = start + batch_size
            with transaction.atomic(), connection.cursor() as cursor:
                # Counted after the lock, the batch misses no comment committed before it,
                # and a comment added or deleted meanwhile updates its counter after the
                # batch commits, on top of the corrected value.
                batch = Task.objects.filter(pk__gt=start, pk__lte=end).order_by("pk")
                list(batch.select_for_update().values_list("pk", flat=True))
                cursor.execute(RECONCILE, [start, end])
                corrected += cursor.rowcount
        self.stdout.write(f"Corrected tasks: {corrected}")
