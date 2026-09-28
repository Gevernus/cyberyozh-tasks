from unittest import mock

import pytest
from django.urls import reverse
from rest_framework import status

from config import health

URL = reverse("health")


@pytest.mark.django_db
def test_health_reports_ok(api_client):
    response = api_client.get(URL)

    assert response.status_code == status.HTTP_200_OK
    assert response.json() == {"status": "ok", "checks": {"database": "ok", "cache": "ok"}}


@pytest.mark.django_db
def test_health_ignores_credentials_and_throttling(api_client, throttle_rates):
    throttle_rates(anon="1/min")
    api_client.credentials(HTTP_AUTHORIZATION="Bearer not-a-token")

    codes = [api_client.get(URL).status_code for _ in range(3)]

    assert codes == [200, 200, 200]


@pytest.mark.parametrize("failing", ["database", "cache"])
def test_health_returns_503_when_a_dependency_fails(api_client, failing):
    checks = {name: mock.Mock() for name in health.CHECKS}
    checks[failing].side_effect = ConnectionError("unreachable")

    with mock.patch.dict(health.CHECKS, checks):
        response = api_client.get(URL)

    assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
    assert response.json()["status"] == "error"
    assert response.json()["checks"][failing] == "error"
