import runpy

import pytest
from django.conf import settings as django_settings
from django.core.cache import cache
from rest_framework.test import APIClient
from rest_framework.throttling import SimpleRateThrottle

from core.throttling import LOCAL_CACHE
from tests.factories import UserFactory


@pytest.fixture(autouse=True)
def _fast_password_hashing(settings):
    settings.PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]


@pytest.fixture(autouse=True)
def _static_files_without_manifest(settings):
    """Tests run without collectstatic, so there is no manifest to look names up in."""
    settings.STORAGES = {
        **settings.STORAGES,
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    }


@pytest.fixture(autouse=True)
def _fresh_throttle_counters():
    cache.clear()
    LOCAL_CACHE.clear()


@pytest.fixture
def throttle_rates(monkeypatch):
    """Lower the rates for one test.

    DRF copies the rates into the throttle classes at import time, so
    override_settings would not reach them.
    """

    def _set(**rates: str) -> None:
        monkeypatch.setattr(
            SimpleRateThrottle, "THROTTLE_RATES", {**SimpleRateThrottle.THROTTLE_RATES, **rates}
        )

    return _set


@pytest.fixture
def unreachable_cache(settings):
    """A Redis cache nobody listens on: every call raises redis ConnectionError."""
    settings.CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.redis.RedisCache",
            "LOCATION": "redis://127.0.0.1:1/0",
        }
    }


@pytest.fixture
def api_client() -> APIClient:
    return APIClient()


@pytest.fixture
def user(db):
    return UserFactory(username="alice")


@pytest.fixture
def other_user(db):
    return UserFactory(username="bob")


@pytest.fixture
def client_for():
    """Clients authenticated without a token; JWT itself is covered in test_auth."""

    def _client_for(some_user) -> APIClient:
        client = APIClient()
        client.force_authenticate(user=some_user)
        return client

    return _client_for


@pytest.fixture
def auth_client(client_for, user) -> APIClient:
    return client_for(user)


@pytest.fixture
def load_settings(monkeypatch):
    """Evaluate config/settings.py afresh; a None value unsets the variable."""

    def _load(**env: str | None) -> dict:
        for name, value in env.items():
            if value is None:
                monkeypatch.delenv(name, raising=False)
            else:
                monkeypatch.setenv(name, value)
        return runpy.run_path(str(django_settings.BASE_DIR / "config" / "settings.py"))

    return _load
