import logging
from collections.abc import Callable

from django.core.cache import cache
from django.db import connection
from drf_spectacular.utils import extend_schema
from rest_framework import serializers, status
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

logger = logging.getLogger(__name__)


def check_database() -> None:
    with connection.cursor() as cursor:
        cursor.execute("SELECT 1")


def check_cache() -> None:
    cache.get("health-check")


CHECKS: dict[str, Callable[[], None]] = {"database": check_database, "cache": check_cache}


class HealthSerializer(serializers.Serializer):
    status = serializers.CharField(help_text="`ok` or `error`.")
    checks = serializers.DictField(
        child=serializers.CharField(), help_text="Per-dependency result, `ok` or `error`."
    )


@extend_schema(
    tags=["health"],
    summary="Health check",
    description="Checks the database and the cache. Public, not throttled.",
    responses={
        status.HTTP_200_OK: HealthSerializer,
        status.HTTP_503_SERVICE_UNAVAILABLE: HealthSerializer,
    },
)
class HealthView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = []

    def get(self, request: Request) -> Response:
        results = {}
        for name, check in CHECKS.items():
            try:
                check()
            except Exception:  # whatever the cause, the dependency is unusable
                logger.exception("Health check %r failed", name)
                results[name] = "error"
            else:
                results[name] = "ok"

        healthy = all(result == "ok" for result in results.values())
        return Response(
            {"status": "ok" if healthy else "error", "checks": results},
            status=status.HTTP_200_OK if healthy else status.HTTP_503_SERVICE_UNAVAILABLE,
        )
