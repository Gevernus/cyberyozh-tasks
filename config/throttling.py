"""Rate limits that survive a Redis outage.

Counters live in Redis so that every gunicorn process and replica shares them.
When Redis is unreachable:

* general limits fail open: the API keeps serving rather than answering 500;
* auth limits fall back to a counter in the process's memory. Password guessing
  stays limited, only per process instead of globally (see docs/OPERATIONS.md for
  the effective rate).
"""

import hashlib
import logging

from django.contrib.auth.base_user import AbstractBaseUser
from django.core.cache.backends.locmem import LocMemCache
from redis.exceptions import RedisError
from rest_framework import throttling

logger = logging.getLogger(__name__)

LOCAL_CACHE = LocMemCache("throttle-fallback", {"OPTIONS": {"MAX_ENTRIES": 100_000}})


class FailOpenMixin:
    def allow_request(self, request, view) -> bool:
        try:
            return super().allow_request(request, view)
        except RedisError as exc:
            logger.warning("%s skipped, cache unavailable: %s", type(self).__name__, exc)
            return True


class LocalFallbackMixin:
    def allow_request(self, request, view) -> bool:
        try:
            return super().allow_request(request, view)
        except RedisError as exc:
            logger.warning(
                "%s counts in process memory, cache unavailable: %s", type(self).__name__, exc
            )
            self.cache = LOCAL_CACHE
            return super().allow_request(request, view)


class FailOpenAnonRateThrottle(FailOpenMixin, throttling.AnonRateThrottle):
    pass


class FailOpenUserRateThrottle(FailOpenMixin, throttling.UserRateThrottle):
    pass


class AuthRateThrottle(LocalFallbackMixin, throttling.SimpleRateThrottle):
    """One budget per client IP shared by all auth endpoints, signed in or not."""

    scope = "auth"

    def get_cache_key(self, request, view) -> str:
        return self.cache_format % {"scope": self.scope, "ident": self.get_ident(request)}


class AuthAccountRateThrottle(LocalFallbackMixin, throttling.SimpleRateThrottle):
    """Attempts per target username, whichever IPs they come from.

    Stops password guessing spread over many addresses. The name is normalised as
    Django does, then case-folded, so case variants share one budget.
    """

    scope = "auth_account"

    def get_cache_key(self, request, view) -> str | None:
        username = request.data.get("username") if hasattr(request.data, "get") else None
        if not isinstance(username, str) or not username.strip():
            return None
        normalised = AbstractBaseUser.normalize_username(username.strip()).casefold()
        ident = hashlib.sha256(normalised.encode()).hexdigest()
        return self.cache_format % {"scope": self.scope, "ident": ident}
