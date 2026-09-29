from unittest import mock

import pytest
from django.urls import reverse
from rest_framework import status

from core import health

READY_URL = reverse("health")
LIVE_URL = reverse("health-live")


def failing_checks(*names: str) -> dict[str, mock.Mock]:
    checks = {name: mock.Mock() for name in health.CHECKS}
    for name in names:
        checks[name].side_effect = ConnectionError("unreachable")
    return checks


@pytest.mark.django_db
def test_readiness_reports_ok(api_client):
    response = api_client.get(READY_URL)

    assert response.status_code == status.HTTP_200_OK
    assert response.json() == {"status": "ok", "checks": {"database": "ok", "cache": "ok"}}


@pytest.mark.django_db
@pytest.mark.parametrize("url", [READY_URL, LIVE_URL])
def test_health_ignores_credentials_and_throttling(api_client, throttle_rates, url):
    throttle_rates(anon="1/min")
    api_client.credentials(HTTP_AUTHORIZATION="Bearer not-a-token")

    codes = [api_client.get(url).status_code for _ in range(3)]

    assert codes == [200, 200, 200]


@pytest.mark.parametrize("failing", [["database"], ["database", "cache"]])
def test_readiness_returns_503_without_the_database(api_client, failing):
    with mock.patch.dict(health.CHECKS, failing_checks(*failing)):
        response = api_client.get(READY_URL)

    assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
    assert response.json()["status"] == "error"
    assert response.json()["checks"]["database"] == "error"


@pytest.mark.django_db
def test_readiness_is_degraded_without_the_cache(api_client):
    with mock.patch.dict(health.CHECKS, failing_checks("cache")):
        response = api_client.get(READY_URL)

    assert response.status_code == status.HTTP_200_OK
    assert response.json() == {
        "status": "degraded",
        "checks": {"database": "ok", "cache": "error"},
    }


def test_readiness_does_not_expose_error_details(api_client):
    with mock.patch.dict(health.CHECKS, failing_checks("database", "cache")):
        response = api_client.get(READY_URL)

    assert "unreachable" not in response.content.decode()


@pytest.mark.django_db
@pytest.mark.usefixtures("unreachable_cache")
def test_readiness_is_degraded_when_redis_is_down(api_client):
    response = api_client.get(READY_URL)

    assert response.status_code == status.HTTP_200_OK
    assert response.json()["status"] == "degraded"


def test_liveness_touches_no_dependencies(api_client):
    checks = failing_checks("database", "cache")
    with mock.patch.dict(health.CHECKS, checks):
        response = api_client.get(LIVE_URL)

    assert response.status_code == status.HTTP_200_OK
    assert response.json() == {"status": "ok"}
    for check in checks.values():
        check.assert_not_called()
