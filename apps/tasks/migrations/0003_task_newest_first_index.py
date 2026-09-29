"""Indexes for the newest-first task list.

The composite indexes replace the plain foreign key ones. Non-atomic: indexes are
built and dropped concurrently, see core.migration_operations.
"""

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models

from core.migration_operations import (
    AddIndexConcurrently,
    RemoveIndexConcurrently,
    create_index,
    drop_index,
)

# Django's names for the foreign key indexes.
FOREIGN_KEY_INDEXES = {
    "tasks_task_assignee_id_2c3ca866": "assignee_id",
    "tasks_task_author_id_33a50930": "author_id",
}


def drop_foreign_key_indexes(apps, schema_editor):
    for name in FOREIGN_KEY_INDEXES:
        drop_index(schema_editor, name)


def create_foreign_key_indexes(apps, schema_editor):
    for name, column in FOREIGN_KEY_INDEXES.items():
        create_index(schema_editor, name, "tasks_task", f'("{column}")')


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("tasks", "0002_task_comments_count"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AlterModelOptions(
            name="task",
            options={"ordering": ["-created_at", "-id"]},
        ),
        AddIndexConcurrently(
            model_name="task",
            index=models.Index(fields=["-created_at", "-id"], name="task_newest_first_idx"),
        ),
        AddIndexConcurrently(
            model_name="task",
            index=models.Index(
                fields=["assignee", "-created_at", "-id"], name="task_assignee_newest_idx"
            ),
        ),
        AddIndexConcurrently(
            model_name="task",
            index=models.Index(
                fields=["author", "-created_at", "-id"], name="task_author_newest_idx"
            ),
        ),
        RemoveIndexConcurrently(model_name="task", name="tasks_task_assigne_7928f6_idx"),
        RemoveIndexConcurrently(model_name="task", name="tasks_task_author__4d54e1_idx"),
        # AlterField would also re-create the foreign key constraints, re-validating
        # every row under a lock that blocks writes.
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.RunPython(drop_foreign_key_indexes, create_foreign_key_indexes),
            ],
            state_operations=[
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
            ],
        ),
    ]
