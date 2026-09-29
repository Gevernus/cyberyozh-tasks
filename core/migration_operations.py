"""Schema operations for migrations that run on a live database.

On PostgreSQL indexes are built and dropped CONCURRENTLY, so writes to the table
are not blocked; such migrations set ``atomic = False``. Other databases get the
plain statements. Every operation can run again after a failure midway.
"""

from django.db import migrations


def is_postgresql(schema_editor) -> bool:
    return schema_editor.connection.vendor == "postgresql"


def _add_index(schema_editor, model, index) -> None:
    if is_postgresql(schema_editor):
        # An interrupted concurrent build leaves an INVALID index behind.
        schema_editor.remove_index(model, index, concurrently=True)
        schema_editor.add_index(model, index, concurrently=True)
    else:
        schema_editor.add_index(model, index)


def _remove_index(schema_editor, model, index) -> None:
    if is_postgresql(schema_editor):
        schema_editor.remove_index(model, index, concurrently=True)
    else:
        schema_editor.remove_index(model, index)


def _concurrently(schema_editor) -> str:
    return " CONCURRENTLY" if is_postgresql(schema_editor) else ""


def drop_index(schema_editor, name: str) -> None:
    """Drop an index the model state does not describe, e.g. a foreign key's own."""
    quoted = schema_editor.quote_name(name)
    schema_editor.execute(f"DROP INDEX{_concurrently(schema_editor)} IF EXISTS {quoted}")


def create_index(schema_editor, name: str, table: str, definition: str) -> None:
    """CREATE INDEX name ON table definition, replacing a leftover one."""
    drop_index(schema_editor, name)
    schema_editor.execute(
        f"CREATE INDEX{_concurrently(schema_editor)} {schema_editor.quote_name(name)} "
        f"ON {schema_editor.quote_name(table)} {definition}"
    )


class AddIndexConcurrently(migrations.AddIndex):
    def database_forwards(self, app_label, schema_editor, from_state, to_state):
        model = to_state.apps.get_model(app_label, self.model_name)
        if self.allow_migrate_model(schema_editor.connection.alias, model):
            _add_index(schema_editor, model, self.index)

    def database_backwards(self, app_label, schema_editor, from_state, to_state):
        model = from_state.apps.get_model(app_label, self.model_name)
        if self.allow_migrate_model(schema_editor.connection.alias, model):
            _remove_index(schema_editor, model, self.index)


class RemoveIndexConcurrently(migrations.RemoveIndex):
    def database_forwards(self, app_label, schema_editor, from_state, to_state):
        model = from_state.apps.get_model(app_label, self.model_name)
        if self.allow_migrate_model(schema_editor.connection.alias, model):
            model_state = from_state.models[app_label, self.model_name_lower]
            _remove_index(schema_editor, model, model_state.get_index_by_name(self.name))

    def database_backwards(self, app_label, schema_editor, from_state, to_state):
        model = to_state.apps.get_model(app_label, self.model_name)
        if self.allow_migrate_model(schema_editor.connection.alias, model):
            model_state = to_state.models[app_label, self.model_name_lower]
            _add_index(schema_editor, model, model_state.get_index_by_name(self.name))


class AddFieldIfMissing(migrations.AddField):
    """AddField that keeps a column an interrupted run already added."""

    def database_forwards(self, app_label, schema_editor, from_state, to_state):
        model = to_state.apps.get_model(app_label, self.model_name)
        connection = schema_editor.connection
        with connection.cursor() as cursor:
            columns = connection.introspection.get_table_description(cursor, model._meta.db_table)
        if model._meta.get_field(self.name).column not in {column.name for column in columns}:
            super().database_forwards(app_label, schema_editor, from_state, to_state)
