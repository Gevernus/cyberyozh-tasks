import runpy

import pytest
from django.conf import settings
from django.db import connection

SETTINGS_FILE = str(settings.BASE_DIR / "config" / "settings.py")
POSTGRES_URL = "postgres://app:secret@db:5432/tasks"


@pytest.mark.parametrize(
    ("env", "options"),
    [
        ({}, {"options": "-c statement_timeout=5000"}),
        ({"DJANGO_DB_STATEMENT_TIMEOUT_MS": "250"}, {"options": "-c statement_timeout=250"}),
        ({"DJANGO_DB_STATEMENT_TIMEOUT_MS": "0"}, {}),
    ],
)
def test_statement_timeout_on_postgresql(monkeypatch, env, options):
    monkeypatch.setenv("DATABASE_URL", POSTGRES_URL)
    monkeypatch.delenv("DJANGO_DB_STATEMENT_TIMEOUT_MS", raising=False)
    for name, value in env.items():
        monkeypatch.setenv(name, value)

    loaded = runpy.run_path(SETTINGS_FILE)

    assert loaded["DATABASES"]["default"].get("OPTIONS", {}) == options


def test_no_statement_timeout_option_for_sqlite(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")

    loaded = runpy.run_path(SETTINGS_FILE)

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
