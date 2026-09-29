"""Index operations that keep a live table writable while they run.

A plain CREATE INDEX blocks writes to the table until the index is built, minutes
on a large table. PostgreSQL's CONCURRENTLY variants do not, but they cannot run in
a transaction: a migration using them sets ``atomic = False``. Other databases
(SQLite in development) get the plain operation.
"""

from django.contrib.postgres import operations
from django.contrib.postgres.operations import NotInTransactionMixin


def is_postgresql(schema_editor) -> bool:
    return schema_editor.connection.vendor == "postgresql"


class PlainOutsidePostgresMixin:
    def database_forwards(self, app_label, schema_editor, from_state, to_state):
        self._implementation(schema_editor).database_forwards(
            app_label, schema_editor, from_state, to_state
        )

    def database_backwards(self, app_label, schema_editor, from_state, to_state):
        self._implementation(schema_editor).database_backwards(
            app_label, schema_editor, from_state, to_state
        )

    def _implementation(self, schema_editor):
        if is_postgresql(schema_editor):
            return super()
        # Past the PostgreSQL class in the MRO: its plain base, AddIndex or RemoveIndex.
        return super(NotInTransactionMixin, self)


class AddIndexConcurrently(PlainOutsidePostgresMixin, operations.AddIndexConcurrently):
    def database_forwards(self, app_label, schema_editor, from_state, to_state):
        if is_postgresql(schema_editor):
            # An interrupted concurrent build leaves an INVALID index behind. Dropping
            # it first lets a failed migration simply be run again.
            self._ensure_not_in_transaction(schema_editor)
            name = schema_editor.quote_name(self.index.name)
            schema_editor.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {name}")
        super().database_forwards(app_label, schema_editor, from_state, to_state)


class RemoveIndexConcurrently(PlainOutsidePostgresMixin, operations.RemoveIndexConcurrently):
    pass
