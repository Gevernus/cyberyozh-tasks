import pytest
from django.db import connection
from django.db.migrations.loader import MigrationLoader
from django.db.migrations.operations import AddIndex, RemoveIndex

POSTGRES_URL = "postgres://app:secret@db:5432/tasks"


@pytest.mark.parametrize(
    ("env", "options"),
    [
        ({}, {"options": "-c statement_timeout=5000"}),
        ({"DJANGO_DB_STATEMENT_TIMEOUT_MS": "250"}, {"options": "-c statement_timeout=250"}),
        ({"DJANGO_DB_STATEMENT_TIMEOUT_MS": "0"}, {}),
    ],
)
def test_statement_timeout_on_postgresql(load_settings, env, options):
    loaded = load_settings(
        **{"DATABASE_URL": POSTGRES_URL, "DJANGO_DB_STATEMENT_TIMEOUT_MS": None, **env}
    )

    assert loaded["DATABASES"]["default"].get("OPTIONS", {}) == options


def test_no_statement_timeout_option_for_sqlite(load_settings):
    loaded = load_settings(DATABASE_URL="sqlite:///:memory:")

    assert "options" not in loaded["DATABASES"]["default"].get("OPTIONS", {})


@pytest.mark.django_db
@pytest.mark.skipif(connection.vendor != "postgresql", reason="PostgreSQL setting")
def test_connections_carry_the_statement_timeout():
    with connection.cursor() as cursor:
        cursor.execute("SHOW statement_timeout")
        (value,) = cursor.fetchone()

    assert value == "5s"


@pytest.mark.django_db
@pytest.mark.skipif(connection.vendor != "postgresql", reason="PostgreSQL indexes")
def test_task_search_is_backed_by_trigram_indexes():
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT indexname, indexdef FROM pg_indexes WHERE tablename = 'tasks_task'"
            " AND indexname LIKE '%%trgm%%'"
        )
        indexes = dict(cursor.fetchall())

    assert set(indexes) == {"task_title_trgm_idx", "task_description_trgm_idx"}
    assert all("gin_trgm_ops" in definition for definition in indexes.values())


@pytest.mark.django_db
def test_a_tasks_comments_have_one_index_in_cursor_order():
    with connection.cursor() as cursor:
        constraints = connection.introspection.get_constraints(cursor, "tasks_comment")

    led_by_task = [
        constraint["columns"]
        for constraint in constraints.values()
        if constraint["index"] and constraint["columns"][0] == "task_id"
    ]
    assert led_by_task == [["task_id", "created_at", "id"]]


def test_indexes_on_existing_tables_are_built_without_blocking_writes():
    loader = MigrationLoader(None, ignore_no_migrations=True)
    blocking = [
        f"{app_label}.{name}: {operation.describe()}"
        for (app_label, name), migration in loader.disk_migrations.items()
        if app_label in {"accounts", "tasks"} and not migration.initial
        for operation in migration.operations
        if type(operation) in {AddIndex, RemoveIndex}
    ]

    assert blocking == [], "use core.migration_operations in a non-atomic migration"
