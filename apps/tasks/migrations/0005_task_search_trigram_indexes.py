"""Trigram indexes for task search, PostgreSQL only.

Search runs `icontains` as UPPER(column::text) LIKE '%term%', which a B-tree cannot
serve; the indexes are on that expression. The model does not declare them because
SQLite cannot build them. Non-atomic: indexes are built concurrently, see
core.migration_operations.
"""

from django.db import migrations

from core.migration_operations import create_index, drop_index, is_postgresql

INDEXES = {
    "task_title_trgm_idx": "title",
    "task_description_trgm_idx": "description",
}


def create_indexes(apps, schema_editor):
    if not is_postgresql(schema_editor):
        return
    schema_editor.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    for name, column in INDEXES.items():
        create_index(
            schema_editor, name, "tasks_task", f'USING gin ((UPPER("{column}"::text)) gin_trgm_ops)'
        )


def drop_indexes(apps, schema_editor):
    if not is_postgresql(schema_editor):
        return
    for name in INDEXES:
        drop_index(schema_editor, name)


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("tasks", "0004_limit_text_length"),
    ]

    operations = [migrations.RunPython(create_indexes, drop_indexes)]
