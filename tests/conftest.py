import pytest
from rest_framework.test import APIClient

from tests.factories import UserFactory


@pytest.fixture(autouse=True)
def _fast_password_hashing(settings):
    settings.PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]


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
def auth_client(user) -> APIClient:
    """Client authenticated as ``user``; JWT itself is covered in test_auth."""
    client = APIClient()
    client.force_authenticate(user=user)
    return client


@pytest.fixture
def client_for():
    def _client_for(some_user) -> APIClient:
        client = APIClient()
        client.force_authenticate(user=some_user)
        return client

    return _client_for
