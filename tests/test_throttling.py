import pytest
from django.urls import reverse
from rest_framework import status

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize("url_name", ["auth-register", "token-obtain-pair", "token-refresh"])
def test_auth_endpoints_are_rate_limited(api_client, throttle_rates, url_name):
    throttle_rates(auth="2/min")
    url = reverse(url_name)

    first, second, third = (api_client.post(url, {}) for _ in range(3))

    assert first.status_code != status.HTTP_429_TOO_MANY_REQUESTS
    assert second.status_code != status.HTTP_429_TOO_MANY_REQUESTS
    assert third.status_code == status.HTTP_429_TOO_MANY_REQUESTS
    assert "Retry-After" in third.headers


def test_auth_endpoints_share_one_budget(api_client, throttle_rates):
    throttle_rates(auth="2/min")

    api_client.post(reverse("auth-register"), {})
    api_client.post(reverse("token-obtain-pair"), {})
    response = api_client.post(reverse("token-refresh"), {})

    assert response.status_code == status.HTTP_429_TOO_MANY_REQUESTS


def test_forged_forwarded_for_does_not_bypass_the_limit(api_client, throttle_rates):
    throttle_rates(auth="1/min")
    url = reverse("token-obtain-pair")

    api_client.post(url, {})
    response = api_client.post(url, {}, HTTP_X_FORWARDED_FOR="203.0.113.7")

    assert response.status_code == status.HTTP_429_TOO_MANY_REQUESTS


def test_auth_limit_does_not_affect_other_endpoints(api_client, auth_client, throttle_rates):
    throttle_rates(auth="1/min")
    api_client.post(reverse("token-obtain-pair"), {})
    limited = api_client.post(reverse("token-obtain-pair"), {})
    assert limited.status_code == status.HTTP_429_TOO_MANY_REQUESTS

    assert auth_client.get(reverse("task-list")).status_code == status.HTTP_200_OK
    assert api_client.get(reverse("schema")).status_code == status.HTTP_200_OK


def test_authenticated_requests_are_limited_per_user(client_for, user, other_user, throttle_rates):
    throttle_rates(user="2/min")
    url = reverse("task-list")

    responses = [client_for(user).get(url) for _ in range(3)]

    assert [r.status_code for r in responses] == [200, 200, 429]
    assert client_for(other_user).get(url).status_code == status.HTTP_200_OK


def test_anonymous_requests_are_limited(api_client, throttle_rates):
    throttle_rates(anon="1/min")
    url = reverse("schema")

    assert api_client.get(url).status_code == status.HTTP_200_OK
    assert api_client.get(url).status_code == status.HTTP_429_TOO_MANY_REQUESTS
