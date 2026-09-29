from unittest import mock

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework import status
from rest_framework_simplejwt.tokens import AccessToken

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


REGISTRATION_FAILED = {"non_field_errors": ["Registration failed."]}


def register(client, username: str, **extra):
    payload = {"username": username, "password": "Sup3r-secret!", **extra}
    return client.post(reverse("auth-register"), payload)


def test_register_does_not_reveal_a_taken_username(api_client, user):
    response = register(api_client, user.username, email="someone@example.com")

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.json() == REGISTRATION_FAILED
    assert User.objects.filter(username=user.username).count() == 1


def test_taken_username_hashes_the_password_like_a_new_account(api_client, user):
    with mock.patch("apps.accounts.serializers.make_password") as make_password:
        register(api_client, user.username)

    make_password.assert_called_once_with("Sup3r-secret!")


def test_taken_username_is_checked_after_the_other_fields(api_client, user):
    response = api_client.post(
        reverse("auth-register"), {"username": user.username, "password": "123"}
    )

    assert set(response.json()) == {"password"}


def test_concurrent_registration_of_one_username_fails_generically(api_client, user):
    exists = mock.patch("django.db.models.QuerySet.exists", return_value=False)

    with exists:
        response = register(api_client, user.username)

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.json() == REGISTRATION_FAILED


def test_register_explains_an_invalid_username(api_client):
    response = register(api_client, "no spaces allowed")

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert "username" in response.json()


def test_register_requires_ten_characters_in_a_password(api_client):
    too_short = api_client.post(
        reverse("auth-register"), {"username": "erin", "password": "Xy7-long!"}
    )
    long_enough = api_client.post(
        reverse("auth-register"), {"username": "erin", "password": "Xy7-long!!"}
    )

    assert too_short.status_code == status.HTTP_400_BAD_REQUEST
    assert "password" in too_short.json()
    assert long_enough.status_code == status.HTTP_201_CREATED


def obtain_tokens(client, user) -> dict:
    response = client.post(
        reverse("token-obtain-pair"), {"username": user.username, "password": DEFAULT_PASSWORD}
    )
    assert response.status_code == status.HTTP_200_OK
    return response.data


def refresh(client, token: str):
    return client.post(reverse("token-refresh"), {"refresh": token})


def test_refresh_rotates_the_refresh_token(api_client, user):
    tokens = obtain_tokens(api_client, user)

    refreshed = refresh(api_client, tokens["refresh"])

    assert refreshed.status_code == status.HTTP_200_OK
    assert {"access", "refresh"} <= refreshed.data.keys()
    assert refreshed.data["refresh"] != tokens["refresh"]
    assert refresh(api_client, refreshed.data["refresh"]).status_code == status.HTTP_200_OK


def test_a_refresh_token_works_only_once(api_client, user):
    tokens = obtain_tokens(api_client, user)
    refresh(api_client, tokens["refresh"])

    assert refresh(api_client, tokens["refresh"]).status_code == status.HTTP_401_UNAUTHORIZED


def test_logout_revokes_the_refresh_token(api_client, user):
    tokens = obtain_tokens(api_client, user)

    logout = api_client.post(reverse("token-blacklist"), {"refresh": tokens["refresh"]})

    assert logout.status_code == status.HTTP_200_OK
    assert refresh(api_client, tokens["refresh"]).status_code == status.HTTP_401_UNAUTHORIZED


def test_access_token_lives_fifteen_minutes(api_client, user):
    access = AccessToken(obtain_tokens(api_client, user)["access"])

    assert access["exp"] - access["iat"] == 15 * 60


def test_obtain_jwt_with_wrong_password_fails(api_client, user):
    response = api_client.post(
        reverse("token-obtain-pair"), {"username": user.username, "password": "wrong"}
    )

    assert response.status_code == status.HTTP_401_UNAUTHORIZED


def test_access_token_authenticates_requests(api_client, user):
    token = obtain_tokens(api_client, user)["access"]

    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
    response = api_client.get(reverse("user-me"))

    assert response.status_code == status.HTTP_200_OK
    assert response.data["username"] == user.username


def test_api_requires_authentication(api_client):
    response = api_client.get(reverse("user-list"))

    assert response.status_code == status.HTTP_401_UNAUTHORIZED
