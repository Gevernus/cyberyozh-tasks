import datetime
import importlib.util
import json
import logging
import logging.config
import runpy
from types import SimpleNamespace
from unittest import mock

import pytest
from django.conf import settings
from django.urls import reverse
from gunicorn.config import Config

from config import health
from config.observability import RequestIdFilter, request_id_var

LIVE_URL = reverse("health-live")
READY_URL = reverse("health")
METRICS_URL = reverse("metrics")


def test_generates_a_request_id_when_none_is_given(api_client):
    response = api_client.get(LIVE_URL)

    request_id = response["X-Request-ID"]
    assert len(request_id) == 32
    int(request_id, 16)


def test_generated_ids_are_unique(api_client):
    ids = {api_client.get(LIVE_URL)["X-Request-ID"] for _ in range(3)}

    assert len(ids) == 3


def test_keeps_a_valid_caller_request_id(api_client):
    response = api_client.get(LIVE_URL, HTTP_X_REQUEST_ID="edge-7f3a.01_B")

    assert response["X-Request-ID"] == "edge-7f3a.01_B"


@pytest.mark.parametrize(
    "unsafe", ["", "a" * 65, "has space", "line\nbreak", 'quote"', "ünïcode", "a/b"]
)
def test_replaces_an_unsafe_caller_request_id(api_client, unsafe):
    response = api_client.get(LIVE_URL, HTTP_X_REQUEST_ID=unsafe)

    assert response["X-Request-ID"] != unsafe
    assert len(response["X-Request-ID"]) == 32


def test_request_id_is_visible_while_handling_the_request(api_client):
    seen = []
    checks = {"database": lambda: seen.append(request_id_var.get()), "cache": mock.Mock()}

    with mock.patch.dict(health.CHECKS, checks):
        response = api_client.get(READY_URL, HTTP_X_REQUEST_ID="trace-1")

    assert seen == ["trace-1"]
    assert response["X-Request-ID"] == "trace-1"
    assert request_id_var.get() is None


def test_log_records_carry_the_request_id(capsys):
    logging.config.dictConfig(settings.LOGGING)
    token = request_id_var.set("trace-2")
    try:
        logging.getLogger("apps.tasks").warning("something happened")
    finally:
        request_id_var.reset(token)

    record = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert record["message"] == "something happened"
    assert record["level"] == "WARNING"
    assert record["logger"] == "apps.tasks"
    assert record["request_id"] == "trace-2"
    assert "timestamp" in record


def test_filter_keeps_an_explicit_request_id():
    record = logging.LogRecord("x", logging.INFO, __file__, 1, "msg", None, None)
    record.request_id = "from-access-log"

    RequestIdFilter().filter(record)

    assert record.request_id == "from-access-log"


def load_gunicorn_config() -> dict:
    return runpy.run_path(str(settings.BASE_DIR / "gunicorn.conf.py"))


def test_gunicorn_access_log_is_structured(caplog):
    logger = load_gunicorn_config()["JsonAccessLogger"](Config())
    response = SimpleNamespace(
        status="201 Created", sent=42, headers=[("X-Request-ID", "trace-3")]
    )
    environ = {
        "REQUEST_METHOD": "POST",
        "PATH_INFO": "/api/tasks/",
        "REMOTE_ADDR": "172.18.0.5",
        "HTTP_X_FORWARDED_FOR": "203.0.113.9",
        "HTTP_USER_AGENT": "k6",
    }

    logger.access_log.addHandler(caplog.handler)  # gunicorn loggers do not propagate
    try:
        logger.access(response, None, environ, datetime.timedelta(milliseconds=12.5))
    finally:
        logger.access_log.removeHandler(caplog.handler)

    record = caplog.records[-1]
    assert record.getMessage() == "POST /api/tasks/ 201"
    assert record.status == 201
    assert record.request_id == "trace-3"
    assert record.duration_ms == 12.5
    assert record.forwarded_for == "203.0.113.9"
    assert record.bytes == 42


def test_gunicorn_uses_json_logging():
    config = load_gunicorn_config()

    formatter = config["logconfig_dict"]["formatters"]["json"]["()"]
    assert formatter == "pythonjsonlogger.json.JsonFormatter"
    assert config["logger_class"].__name__ == "JsonAccessLogger"


@pytest.mark.django_db
@pytest.mark.parametrize(
    "address", ["127.0.0.1", "10.0.3.4", "172.18.0.7", "192.168.1.2", "::1", "::ffff:10.0.0.2"]
)
def test_metrics_are_served_to_internal_addresses(client, address):
    response = client.get(METRICS_URL, REMOTE_ADDR=address)

    assert response.status_code == 200
    assert b"django_http_requests" in response.content


@pytest.mark.parametrize(
    "address", ["203.0.113.9", "8.8.8.8", "100.64.0.1", "2001:db8::1", "not-an-ip", ""]
)
def test_metrics_are_hidden_from_public_addresses(client, address):
    assert client.get(METRICS_URL, REMOTE_ADDR=address).status_code == 404


def test_metrics_ignore_forwarded_for(client):
    response = client.get(METRICS_URL, REMOTE_ADDR="203.0.113.9", HTTP_X_FORWARDED_FOR="10.0.0.1")

    assert response.status_code == 404


@pytest.mark.parametrize(
    ("env", "initialised"),
    [({}, False), ({"SENTRY_DSN": "https://key@sentry.example.com/1"}, True)],
)
def test_sentry_is_enabled_only_with_a_dsn(monkeypatch, env, initialised):
    monkeypatch.delenv("SENTRY_DSN", raising=False)
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    settings_file = importlib.util.find_spec("config.settings").origin

    with mock.patch("sentry_sdk.init") as init:
        runpy.run_path(settings_file)

    assert init.called is initialised
    if initialised:
        assert init.call_args.kwargs["send_default_pii"] is False
        assert init.call_args.kwargs["dsn"] == env["SENTRY_DSN"]
