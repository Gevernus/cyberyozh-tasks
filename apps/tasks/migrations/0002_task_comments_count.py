from django.db import migrations, models
from django.db.models import Count, OuterRef, Subquery


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
    Task.objects.filter(pk__in=Comment.objects.values("task")).update(
        comments_count=Subquery(counts)
    )


class Migration(migrations.Migration):
    dependencies = [
        ("tasks", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="task",
            name="comments_count",
            field=models.PositiveIntegerField(db_default=0, default=0, editable=False),
        ),
        migrations.RunPython(count_comments, migrations.RunPython.noop, elidable=True),
    ]
