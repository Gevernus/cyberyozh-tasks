import pytest
from django.core.management import call_command
from django.urls import reverse


@pytest.mark.django_db
@pytest.mark.parametrize("url_name", ["schema", "swagger-ui", "redoc"])
def test_docs_are_public(api_client, url_name):
    assert api_client.get(reverse(url_name)).status_code == 200


def test_schema_generates_without_warnings(tmp_path):
    # --fail-on-warn turns any drf-spectacular warning (e.g. unresolved types) into an error.
    call_command("spectacular", "--validate", "--fail-on-warn", "--file", tmp_path / "s.yml")
