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

# Only throttling uses the cache, and it works without it.
OPTIONAL_CHECKS = frozenset({"cache"})


class LivenessSerializer(serializers.Serializer):
    status = serializers.CharField(help_text="Always `ok`.")


class HealthSerializer(serializers.Serializer):
    status = serializers.CharField(
        help_text="`ok`, `degraded` (an optional dependency is down) or `error`."
    )
    checks = serializers.DictField(
        child=serializers.CharField(), help_text="Per-dependency result, `ok` or `error`."
    )


class PublicView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = []


@extend_schema(
    tags=["health"],
    summary="Liveness check",
    description="The process serves requests. Touches no dependencies. Public, not throttled.",
    responses={status.HTTP_200_OK: LivenessSerializer},
)
class LivenessView(PublicView):
    def get(self, request: Request) -> Response:
        return Response({"status": "ok"})


@extend_schema(
    tags=["health"],
    summary="Readiness check",
    description=(
        "Checks the database and the cache. `503` when the database is unavailable; "
        "without the cache the API still works, without rate limits, and the status "
        "is `degraded`. Public, not throttled."
    ),
    responses={
        status.HTTP_200_OK: HealthSerializer,
        status.HTTP_503_SERVICE_UNAVAILABLE: HealthSerializer,
    },
)
class ReadinessView(PublicView):
    def get(self, request: Request) -> Response:
        results = {}
        for name, check in CHECKS.items():
            try:
                check()
            except Exception:
                logger.exception("Health check %r failed", name)
                results[name] = "error"
            else:
                results[name] = "ok"

        failed = {name for name, result in results.items() if result == "error"}
        if failed - OPTIONAL_CHECKS:
            overall, code = "error", status.HTTP_503_SERVICE_UNAVAILABLE
        elif failed:
            overall, code = "degraded", status.HTTP_200_OK
        else:
            overall, code = "ok", status.HTTP_200_OK
        return Response({"status": overall, "checks": results}, status=code)
