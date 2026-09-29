"""Rate limits kept in Redis. Without Redis general limits let requests through,
while auth limits count in the memory of each process."""

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
    """One budget per client IP for all auth endpoints, signed in or not."""

    scope = "auth"

    def get_cache_key(self, request, view) -> str:
        return self.cache_format % {"scope": self.scope, "ident": self.get_ident(request)}


def requested_account(request) -> str | None:
    """The username a token request is for, normalised and case-folded."""
    username = request.data.get("username") if hasattr(request.data, "get") else None
    if not isinstance(username, str) or not username.strip():
        return None
    return AbstractBaseUser.normalize_username(username.strip()).casefold()


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


class AuthAccountAddressRateThrottle(LocalFallbackMixin, throttling.SimpleRateThrottle):
    """Token requests for one username from one IP; using it up blocks only that IP."""

    scope = "auth_account_ip"

    def get_cache_key(self, request, view) -> str | None:
        account = requested_account(request)
        if account is None:
            return None
        ident = digest(f"{account}\0{self.get_ident(request)}")
        return self.cache_format % {"scope": self.scope, "ident": ident}


class AuthAccountRateThrottle(LocalFallbackMixin, throttling.SimpleRateThrottle):
    """Token requests for one username from all IPs.

    Using it up locks the owner out too, so it is set well above the per-IP limit
    and reaching it is logged.
    """

    scope = "auth_account"

    def get_cache_key(self, request, view) -> str | None:
        self.account = requested_account(request)
        if self.account is None:
            return None
        return self.cache_format % {"scope": self.scope, "ident": digest(self.account)}

    def throttle_failure(self) -> bool:
        # Once per window and account.
        if self.cache.add(f"{self.key}:reported", True, self.duration):
            logger.warning(
                "Account throttled: token requests over %s from all addresses",
                self.rate,
                # The digest from the throttle key keeps logins out of the log.
                extra={"account": digest(self.account)},
            )
        return False
