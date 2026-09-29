"""One index for a task's comments in cursor order.

(task, created_at, id) returns a page without sorting and serves lookups by task,
so it replaces both the (task, created_at) index and the foreign key index.
Non-atomic: indexes are built and dropped concurrently, see core.migration_operations.
"""

import django.db.models.deletion
from django.db import migrations, models

from core.migration_operations import (
    AddIndexConcurrently,
    RemoveIndexConcurrently,
    create_index,
    drop_index,
)

# Django's name for the foreign key index.
FOREIGN_KEY_INDEXES = {"tasks_comment_task_id_8e8bc4fe": "task_id"}


def drop_foreign_key_indexes(apps, schema_editor):
    for name in FOREIGN_KEY_INDEXES:
        drop_index(schema_editor, name)


def create_foreign_key_indexes(apps, schema_editor):
    for name, column in FOREIGN_KEY_INDEXES.items():
        create_index(schema_editor, name, "tasks_comment", f'("{column}")')


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("tasks", "0005_task_search_trigram_indexes"),
    ]

    operations = [
        AddIndexConcurrently(
            model_name="comment",
            index=models.Index(
                fields=["task", "created_at", "id"], name="comment_task_oldest_first_idx"
            ),
        ),
        RemoveIndexConcurrently(model_name="comment", name="tasks_comme_task_id_860403_idx"),
        # AlterField would also re-create the foreign key constraint, see 0003.
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.RunPython(drop_foreign_key_indexes, create_foreign_key_indexes),
            ],
            state_operations=[
                migrations.AlterField(
                    model_name="comment",
                    name="task",
                    field=models.ForeignKey(
                        db_index=False,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="comments",
                        to="tasks.task",
                    ),
                ),
            ],
        ),
    ]
