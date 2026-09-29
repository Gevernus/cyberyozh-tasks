"""Invariants of the compose stack that the deployment docs rely on."""

import pytest
import yaml
from django.conf import settings

COMPOSE = yaml.safe_load((settings.BASE_DIR / "docker-compose.yml").read_text())
SERVICES = COMPOSE["services"]


def test_only_the_edge_is_published():
    published = {name for name, service in SERVICES.items() if "ports" in service}

    assert published == {"caddy"}


def test_web_can_be_scaled():
    assert "container_name" not in SERVICES["web"]


def test_migrations_run_once_before_web():
    migrate = SERVICES["migrate"]

    assert migrate["command"] == ["python", "manage.py", "migrate", "--noinput"]
    assert migrate["restart"] == "no"
    assert migrate["environment"]["DJANGO_DB_STATEMENT_TIMEOUT_MS"] == "0"
    assert SERVICES["web"]["depends_on"]["migrate"] == {
        "condition": "service_completed_successfully"
    }
    assert "command" not in SERVICES["web"]


@pytest.mark.parametrize("volume", ["caddy_data", "caddy_config", "postgres_data"])
def test_state_lives_in_named_volumes(volume):
    assert volume in COMPOSE["volumes"]


def test_app_hosts_follow_the_domain():
    environment = SERVICES["web"]["environment"]

    assert environment["DJANGO_ALLOWED_HOSTS"].startswith("${DOMAIN")
    assert environment["DJANGO_CSRF_TRUSTED_ORIGINS"] == "https://${DOMAIN}"


def test_env_example_matches_the_edge_setup():
    lines = (settings.BASE_DIR / ".env.example").read_text().splitlines()
    env = dict(line.split("=", 1) for line in lines if line and not line.startswith("#"))

    assert env["DJANGO_SECURE_HTTPS"] == "1"
    assert env["DJANGO_SECURE_PROXY_SSL_HEADER"] == "1"
    assert env["NUM_PROXIES"] == "1"
    assert "DJANGO_MIGRATE" not in env


def test_every_service_rotates_its_logs():
    for name, service in SERVICES.items():
        assert service["logging"]["options"]["max-size"], name
