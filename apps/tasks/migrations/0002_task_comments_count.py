"""Store the number of comments on each task.

Non-atomic, so the ADD COLUMN lock, which blocks even reads, is released before the
backfill runs in short id-range statements. Both steps can run again after a failure.
"""

from django.db import migrations, models
from django.db.models import Count, Max, OuterRef, Subquery
from django.db.models.functions import Coalesce

from core.migration_operations import AddFieldIfMissing

BATCH_SIZE = 10_000


def count_comments(apps, schema_editor):
    Task = apps.get_model("tasks", "Task")
    Comment = apps.get_model("tasks", "Comment")
    counts = (
        Comment.objects.filter(task=OuterRef("pk"))
        .order_by()
        .values("task")
        .annotate(total=Count("pk"))
        .values("total")
    )
    actual = Coalesce(Subquery(counts), 0)
    last_id = Task.objects.aggregate(last=Max("pk"))["last"] or 0
    for start in range(0, last_id, BATCH_SIZE):
        Task.objects.filter(pk__gt=start, pk__lte=start + BATCH_SIZE).exclude(
            comments_count=actual
        ).update(comments_count=actual)


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("tasks", "0001_initial"),
    ]

    operations = [
        AddFieldIfMissing(
            model_name="task",
            name="comments_count",
            field=models.PositiveIntegerField(db_default=0, default=0, editable=False),
        ),
        migrations.RunPython(count_comments, migrations.RunPython.noop, elidable=True),
    ]
