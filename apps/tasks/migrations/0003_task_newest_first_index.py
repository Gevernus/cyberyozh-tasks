import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("tasks", "0002_task_comments_count"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AlterModelOptions(
            name="task",
            options={"ordering": ["-created_at", "-id"]},
        ),
        migrations.AddIndex(
            model_name="task",
            index=models.Index(fields=["-created_at", "-id"], name="task_newest_first_idx"),
        ),
        migrations.AddIndex(
            model_name="task",
            index=models.Index(
                fields=["assignee", "-created_at", "-id"], name="task_assignee_newest_idx"
            ),
        ),
        migrations.AddIndex(
            model_name="task",
            index=models.Index(
                fields=["author", "-created_at", "-id"], name="task_author_newest_idx"
            ),
        ),
        migrations.RemoveIndex(model_name="task", name="tasks_task_assigne_7928f6_idx"),
        migrations.RemoveIndex(model_name="task", name="tasks_task_author__4d54e1_idx"),
        migrations.AlterField(
            model_name="task",
            name="assignee",
            field=models.ForeignKey(
                blank=True,
                db_index=False,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="assigned_tasks",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AlterField(
            model_name="task",
            name="author",
            field=models.ForeignKey(
                db_index=False,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="authored_tasks",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
    ]
