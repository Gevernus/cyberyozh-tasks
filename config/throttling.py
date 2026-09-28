"""Throttles that let requests through when the cache backend is down.

Rate limits live in Redis. Losing them for the duration of an outage is the lesser
evil compared with answering every request with 500.
"""

import logging

from redis.exceptions import RedisError
from rest_framework import throttling

logger = logging.getLogger(__name__)


class FailOpenMixin:
    def allow_request(self, request, view) -> bool:
        try:
            return super().allow_request(request, view)
        except RedisError as exc:
            logger.warning("%s skipped, cache unavailable: %s", type(self).__name__, exc)
            return True


class AnonRateThrottle(FailOpenMixin, throttling.AnonRateThrottle):
    pass


class UserRateThrottle(FailOpenMixin, throttling.UserRateThrottle):
    pass


class ScopedRateThrottle(FailOpenMixin, throttling.ScopedRateThrottle):
    pass
