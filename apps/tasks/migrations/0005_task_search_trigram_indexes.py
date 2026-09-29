"""Trigram indexes for task search on PostgreSQL.

Search is `icontains`, which PostgreSQL runs as UPPER(column::text) LIKE '%term%'.
A B-tree cannot serve that, so without these indexes every search that matches
few rows scans the whole table. The indexes are on exactly that expression.
Other databases skip this migration; the model does not declare the indexes
because SQLite cannot create them.
"""

from django.db import migrations

INDEXES = {
    "task_title_trgm_idx": "title",
    "task_description_trgm_idx": "description",
}


def create_indexes(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    schema_editor.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    for name, column in INDEXES.items():
        schema_editor.execute(
            f'CREATE INDEX IF NOT EXISTS "{name}" ON "tasks_task" '
            f'USING gin ((UPPER("{column}"::text)) gin_trgm_ops)'
        )


def drop_indexes(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    for name in INDEXES:
        schema_editor.execute(f'DROP INDEX IF EXISTS "{name}"')


class Migration(migrations.Migration):
    dependencies = [
        ("tasks", "0004_limit_text_length"),
    ]

    operations = [migrations.RunPython(create_indexes, drop_indexes)]
