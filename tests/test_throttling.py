import logging

import pytest
from django.urls import reverse
from rest_framework import status

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize(
    "url_name", ["auth-register", "token-obtain-pair", "token-refresh", "token-blacklist"]
)
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


def throttle_warnings(caplog) -> set[str]:
    return {
        record.getMessage().split(" ")[0]
        for record in caplog.records
        if record.name == "config.throttling" and record.levelno == logging.WARNING
    }


def login(client, username: str, address: str = "127.0.0.1"):
    return client.post(
        reverse("token-obtain-pair"),
        {"username": username, "password": "wrong"},
        REMOTE_ADDR=address,
    )


# --- Per-account limits on the token endpoint -----------------------------------


def test_token_attempts_are_limited_per_account_and_address(api_client, throttle_rates):
    throttle_rates(auth_account_ip="2/min")

    codes = [login(api_client, "alice", "198.51.100.1").status_code for _ in range(3)]

    assert codes == [401, 401, 429]
    assert login(api_client, "alice", "198.51.100.2").status_code == 401
    assert login(api_client, "bob", "198.51.100.1").status_code == 401


def test_attempts_refused_for_one_address_do_not_lock_the_owner_out(api_client, throttle_rates):
    throttle_rates(auth_account_ip="2/min", auth_account="3/min")

    codes = [login(api_client, "alice", "203.0.113.66").status_code for _ in range(5)]

    assert codes == [401, 401, 429, 429, 429]
    assert login(api_client, "alice", "198.51.100.1").status_code == 401


def test_token_attempts_are_limited_per_account_across_addresses(api_client, throttle_rates):
    throttle_rates(auth_account="2/min")

    codes = [login(api_client, "alice", f"198.51.100.{n}").status_code for n in range(3)]

    assert codes == [401, 401, 429]
    assert login(api_client, "bob", "198.51.100.9").status_code == 401


def test_username_case_and_spacing_do_not_reset_the_account_limit(api_client, throttle_rates):
    throttle_rates(auth_account="2/min")

    login(api_client, "alice", "198.51.100.1")
    login(api_client, "ALICE", "198.51.100.2")

    assert login(api_client, " Alice ", "198.51.100.3").status_code == 429


def test_reaching_the_account_limit_is_logged_once_per_window(api_client, throttle_rates, caplog):
    throttle_rates(auth_account="1/min")

    codes = [login(api_client, " Alice ", f"198.51.100.{n}").status_code for n in range(3)]

    assert codes == [401, 429, 429]
    [record] = [r for r in caplog.records if r.getMessage().startswith("Account throttled")]
    assert record.levelno == logging.WARNING
    assert record.account == "alice"


@pytest.mark.parametrize("payload", [{}, {"username": ""}, {"username": ["a", "b"]}])
def test_requests_without_a_username_skip_the_account_limits(api_client, throttle_rates, payload):
    throttle_rates(auth_account_ip="1/min", auth_account="1/min")
    url = reverse("token-obtain-pair")

    codes = [api_client.post(url, payload).status_code for _ in range(2)]

    assert codes == [400, 400]


def test_account_limits_apply_only_to_obtaining_tokens(api_client, throttle_rates):
    throttle_rates(auth_account_ip="1/min", auth_account="1/min")
    login(api_client, "alice", "198.51.100.1")

    response = api_client.post(
        reverse("token-refresh"), {"username": "alice", "refresh": "x"}, REMOTE_ADDR="198.51.100.1"
    )

    assert response.status_code == status.HTTP_401_UNAUTHORIZED


# --- Redis outage ----------------------------------------------------------------


@pytest.mark.usefixtures("unreachable_cache")
def test_general_limits_fail_open_when_the_cache_is_down(
    api_client, auth_client, throttle_rates, caplog
):
    throttle_rates(anon="1/min", user="1/min")

    tasks = [auth_client.get(reverse("task-list")).status_code for _ in range(2)]
    schema = [api_client.get(reverse("schema")).status_code for _ in range(2)]

    assert tasks == [200, 200]
    assert schema == [200, 200]
    assert throttle_warnings(caplog) == {"FailOpenAnonRateThrottle", "FailOpenUserRateThrottle"}


@pytest.mark.usefixtures("unreachable_cache")
def test_auth_limits_count_in_process_memory_when_the_cache_is_down(
    api_client, throttle_rates, caplog
):
    throttle_rates(anon="100/min", auth="2/min", auth_account="100/min")

    codes = [login(api_client, f"user{n}").status_code for n in range(3)]

    assert codes == [401, 401, 429]
    assert "AuthRateThrottle" in throttle_warnings(caplog)


@pytest.mark.usefixtures("unreachable_cache")
@pytest.mark.parametrize(
    ("rates", "addresses", "throttle"),
    [
        ({"auth_account_ip": "2/min"}, ["198.51.100.1"] * 3, "AuthAccountAddressRateThrottle"),
        (
            {"auth_account": "2/min"},
            ["198.51.100.1", "198.51.100.2", "198.51.100.3"],
            "AuthAccountRateThrottle",
        ),
    ],
)
def test_account_limits_count_in_process_memory_when_the_cache_is_down(
    api_client, throttle_rates, caplog, rates, addresses, throttle
):
    throttle_rates(anon="100/min", auth="100/min", **rates)

    codes = [login(api_client, "alice", address).status_code for address in addresses]

    assert codes == [401, 401, 429]
    assert throttle in throttle_warnings(caplog)
