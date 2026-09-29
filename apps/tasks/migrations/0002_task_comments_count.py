"""Store the number of comments on each task.

Non-atomic: in one transaction, the lock taken by ADD COLUMN, which blocks even
reads of the table, would last until the backfill finished. The column is added
at once; the backfill then runs in id ranges, each a short statement of its own.

Both steps can be repeated: the column is added only if missing, and the backfill
sets every task's counter from its comments. A run that failed midway is simply
run again, never marked applied with --fake.
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
