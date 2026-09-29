import pytest
from django.core.management import call_command
from django.urls import reverse
from drf_spectacular.generators import SchemaGenerator


@pytest.mark.django_db
@pytest.mark.parametrize("url_name", ["schema", "swagger-ui", "redoc"])
def test_docs_are_public(api_client, url_name):
    assert api_client.get(reverse(url_name)).status_code == 200


def test_root_redirects_to_swagger_ui(client):
    response = client.get("/")

    assert response.status_code == 302
    assert response["Location"] == reverse("swagger-ui")


def test_schema_generates_without_warnings(tmp_path):
    call_command("spectacular", "--validate", "--fail-on-warn", "--file", tmp_path / "s.yml")


@pytest.mark.django_db
def test_docs_pages_need_no_inline_script_or_cdn(api_client):
    swagger = api_client.get(reverse("swagger-ui")).content.decode()
    redoc = api_client.get(reverse("redoc")).content.decode()

    for page in (swagger, redoc):
        assert "cdn.jsdelivr.net" not in page
        assert "<script>" not in page
    assert "/static/drf_spectacular_sidecar/swagger-ui-dist/" in swagger
    assert "/static/drf_spectacular_sidecar/redoc/" in redoc


@pytest.mark.django_db
def test_swagger_init_script_is_served_separately(api_client):
    response = api_client.get(reverse("swagger-ui"), {"script": ""})

    assert response.status_code == 200
    assert response["Content-Type"].startswith("application/javascript")


@pytest.fixture(scope="module")
def schema() -> dict:
    return SchemaGenerator().get_schema(request=None, public=True)


def responses(schema: dict, method: str, path: str) -> set[str]:
    return set(schema["paths"][path][method]["responses"])


def test_schema_documents_error_responses(schema):
    assert responses(schema, "post", "/api/tasks/{id}/complete/") == {
        "200",
        "400",
        "401",
        "403",
        "404",
        "429",
    }
    assert responses(schema, "get", "/api/tasks/") == {"200", "400", "401", "429"}
    assert responses(schema, "post", "/api/auth/token/") == {"200", "400", "401", "429"}
    assert responses(schema, "get", "/api/health/live/") == {"200"}


def test_schema_offers_only_jwt_authorization(schema):
    [(name, scheme)] = schema["components"]["securitySchemes"].items()

    assert name == "jwtAuth"
    assert scheme["scheme"] == "bearer"
    assert "without the `Bearer` prefix" in scheme["description"]
