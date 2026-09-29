import yaml
from django.conf import settings


def test_only_the_edge_is_published():
    compose = yaml.safe_load((settings.BASE_DIR / "docker-compose.yml").read_text())

    published = {name for name, service in compose["services"].items() if "ports" in service}

    assert published == {"caddy"}
