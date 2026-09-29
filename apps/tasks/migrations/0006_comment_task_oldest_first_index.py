"""One index for a task's comments in cursor order, instead of two.

Comments are paged by (created_at, id). With the (task, created_at) index, rows that
share a created_at were sorted by id on every page; (task, created_at, id) returns
them in order. It also serves lookups by task alone, so the plain foreign key index
on task_id only slowed down writes.

Non-atomic: indexes are built and dropped CONCURRENTLY. Every step can be repeated.
"""

import django.db.models.deletion
from django.db import migrations, models

from core.migration_operations import (
    AddIndexConcurrently,
    RemoveIndexConcurrently,
    is_postgresql,
)

# Django's name for the plain foreign key index on tasks_comment.task_id.
FOREIGN_KEY_INDEX = "tasks_comment_task_id_8e8bc4fe"


def concurrently(schema_editor) -> str:
    return " CONCURRENTLY" if is_postgresql(schema_editor) else ""


def drop_foreign_key_index(apps, schema_editor):
    schema_editor.execute(f'DROP INDEX{concurrently(schema_editor)} IF EXISTS "{FOREIGN_KEY_INDEX}"')


def create_foreign_key_index(apps, schema_editor):
    schema_editor.execute(
        f'CREATE INDEX{concurrently(schema_editor)} IF NOT EXISTS "{FOREIGN_KEY_INDEX}" '
        'ON "tasks_comment" ("task_id")'
    )


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
        # A plain AlterField would also drop and re-add the foreign key constraint,
        # which re-validates every row while holding a lock that blocks writes.
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.RunPython(drop_foreign_key_index, create_foreign_key_index),
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
