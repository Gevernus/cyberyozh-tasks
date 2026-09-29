"""OpenAPI schema generation: error responses and the JWT security scheme."""

from drf_spectacular import openapi
from drf_spectacular.contrib.rest_framework_simplejwt import SimpleJWTScheme
from drf_spectacular.utils import OpenApiResponse
from rest_framework import serializers
from rest_framework.permissions import SAFE_METHODS
from rest_framework_simplejwt.views import TokenViewBase

OBJECT_ACTIONS = {"retrieve", "update", "partial_update", "destroy"}


class ErrorSerializer(serializers.Serializer):
    detail = serializers.CharField()


MESSAGES_BY_FIELD = {
    "type": "object",
    "additionalProperties": {"type": "array", "items": {"type": "string"}},
}

ERRORS = {
    "400": OpenApiResponse(
        MESSAGES_BY_FIELD,
        description="Invalid input: messages per field, `non_field_errors` for the whole request.",
    ),
    "401": OpenApiResponse(ErrorSerializer, description="No valid credentials."),
    "403": OpenApiResponse(ErrorSerializer, description="The caller may not change this object."),
    "404": OpenApiResponse(ErrorSerializer, description="Not found."),
    "429": OpenApiResponse(ErrorSerializer, description="Rate limit exceeded, see `Retry-After`."),
}


class AutoSchema(openapi.AutoSchema):
    """Documents the error responses each operation can return."""

    def _get_response_bodies(self, direction="response"):
        responses = super()._get_response_bodies(direction)
        for code in self._error_codes():
            if code not in responses:
                responses[code] = self._get_response_for_code(ERRORS[code], code, None, direction)
        return responses

    def _error_codes(self) -> list[str]:
        action = getattr(self.view, "action", None)
        takes_input = self.method in {"POST", "PUT", "PATCH"} or (
            action == "list" and getattr(self.view, "filterset_class", None) is not None
        )
        auth = self.get_auth()
        authenticated = bool(auth) and {} not in auth
        on_object = bool(getattr(self.view, "detail", False)) or action in OBJECT_ACTIONS
        applies = {
            "400": takes_input,
            "401": authenticated or isinstance(self.view, TokenViewBase),
            "403": authenticated and on_object and self.method not in SAFE_METHODS,
            "404": "{" in self.path,
            "429": bool(self.view.get_throttles()),
        }
        return [code for code, applied in applies.items() if applied]


class JWTScheme(SimpleJWTScheme):
    priority = 1

    def get_security_definition(self, auto_schema):
        return {
            **super().get_security_definition(auto_schema),
            "description": "Access token from `/api/auth/token/`, without the `Bearer` prefix.",
        }
