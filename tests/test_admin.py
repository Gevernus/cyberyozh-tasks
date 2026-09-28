import importlib
import runpy
from contextlib import ExitStack

import pytest
from django.conf import settings
from django.test import override_settings
from django.urls import clear_url_caches
from rest_framework import status

import config.urls

SETTINGS_FILE = settings.BASE_DIR / "config" / "settings.py"


@pytest.fixture
def load_urls():
    """Rebuild the URLconf under overridden settings; it reads them at import time."""
    overrides = ExitStack()

    def _load(**values) -> None:
        overrides.enter_context(override_settings(**values))
        importlib.reload(config.urls)
        clear_url_caches()

    yield _load
    overrides.close()
    importlib.reload(config.urls)
    clear_url_caches()


@pytest.mark.django_db
def test_admin_is_not_routed_when_disabled(client, load_urls):
    load_urls(ADMIN_ENABLED=False)

    assert client.get("/admin/").status_code == status.HTTP_404_NOT_FOUND
    assert client.get("/admin/login/").status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.django_db
def test_admin_is_served_when_enabled(client, load_urls):
    load_urls(ADMIN_ENABLED=True, ADMIN_URL="admin/")

    response = client.get("/admin/")

    assert response.status_code == status.HTTP_302_FOUND
    assert response["Location"] == "/admin/login/?next=/admin/"


@pytest.mark.django_db
def test_admin_path_is_configurable(client, load_urls):
    load_urls(ADMIN_ENABLED=True, ADMIN_URL="backstage/")

    response = client.get("/backstage/")

    assert response.status_code == status.HTTP_302_FOUND
    assert response["Location"] == "/backstage/login/?next=/backstage/"
    assert client.get("/admin/").status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.parametrize(
    ("env", "enabled", "url"),
    [
        ({"DJANGO_DEBUG": "True"}, True, "admin/"),
        ({"DJANGO_DEBUG": "False"}, False, "admin/"),
        ({"DJANGO_DEBUG": "False", "DJANGO_ADMIN_ENABLED": "1"}, True, "admin/"),
        ({"DJANGO_DEBUG": "True", "DJANGO_ADMIN_ENABLED": "0"}, False, "admin/"),
        ({"DJANGO_ADMIN_URL": "/backstage"}, True, "backstage/"),
    ],
)
def test_admin_settings_from_environment(monkeypatch, env, enabled, url):
    for name in ("DJANGO_DEBUG", "DJANGO_ADMIN_ENABLED", "DJANGO_ADMIN_URL"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("DJANGO_SECRET_KEY", "test-only")
    for name, value in env.items():
        monkeypatch.setenv(name, value)

    loaded = runpy.run_path(str(SETTINGS_FILE))

    assert loaded["ADMIN_ENABLED"] is enabled
    assert loaded["ADMIN_URL"] == url
