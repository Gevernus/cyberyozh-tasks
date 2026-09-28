import pytest
from django.urls import reverse
from rest_framework import status

from tests.factories import UserFactory

pytestmark = pytest.mark.django_db


def test_list_users_returns_only_active_users(auth_client, user, other_user):
    UserFactory(username="ghost", is_active=False)

    response = auth_client.get(reverse("user-list"))

    assert response.status_code == status.HTTP_200_OK
    usernames = [item["username"] for item in response.data["results"]]
    assert usernames == ["alice", "bob"]


def test_user_payload_does_not_leak_private_fields(auth_client, other_user):
    response = auth_client.get(reverse("user-detail", args=[other_user.pk]))

    assert response.status_code == status.HTTP_200_OK
    assert set(response.data) == {"id", "username", "first_name", "last_name"}


def test_search_users(auth_client, other_user):
    response = auth_client.get(reverse("user-list"), {"search": "bo"})

    assert [item["username"] for item in response.data["results"]] == ["bob"]


def test_me_returns_current_user(auth_client, user):
    response = auth_client.get(reverse("user-me"))

    assert response.data["id"] == user.pk
