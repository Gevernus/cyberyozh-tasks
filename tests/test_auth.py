import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework import status

from tests.factories import DEFAULT_PASSWORD

User = get_user_model()

pytestmark = pytest.mark.django_db


def test_register_creates_user_with_hashed_password(api_client):
    payload = {"username": "carol", "email": "carol@example.com", "password": "Sup3r-secret!"}

    response = api_client.post(reverse("auth-register"), payload)

    assert response.status_code == status.HTTP_201_CREATED
    assert "password" not in response.data
    created = User.objects.get(username="carol")
    assert created.check_password("Sup3r-secret!")


def test_register_rejects_weak_password(api_client):
    response = api_client.post(reverse("auth-register"), {"username": "dave", "password": "123"})

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert "password" in response.data
    assert not User.objects.filter(username="dave").exists()


def test_register_rejects_duplicate_username(api_client, user):
    response = api_client.post(
        reverse("auth-register"), {"username": user.username, "password": "Sup3r-secret!"}
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert "username" in response.data


def test_obtain_and_refresh_jwt(api_client, user):
    response = api_client.post(
        reverse("token-obtain-pair"), {"username": user.username, "password": DEFAULT_PASSWORD}
    )
    assert response.status_code == status.HTTP_200_OK
    assert {"access", "refresh"} <= response.data.keys()

    refreshed = api_client.post(reverse("token-refresh"), {"refresh": response.data["refresh"]})
    assert refreshed.status_code == status.HTTP_200_OK
    assert "access" in refreshed.data


def test_obtain_jwt_with_wrong_password_fails(api_client, user):
    response = api_client.post(
        reverse("token-obtain-pair"), {"username": user.username, "password": "wrong"}
    )

    assert response.status_code == status.HTTP_401_UNAUTHORIZED


def test_access_token_authenticates_requests(api_client, user):
    token = api_client.post(
        reverse("token-obtain-pair"), {"username": user.username, "password": DEFAULT_PASSWORD}
    ).data["access"]

    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
    response = api_client.get(reverse("user-me"))

    assert response.status_code == status.HTTP_200_OK
    assert response.data["username"] == user.username


def test_api_requires_authentication(api_client):
    response = api_client.get(reverse("user-list"))

    assert response.status_code == status.HTTP_401_UNAUTHORIZED
