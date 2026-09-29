"""Request ids and structured logging shared by Django and gunicorn."""

import logging
import re
import uuid
from collections.abc import Callable
from contextvars import ContextVar

import sentry_sdk
from django.http import HttpRequest, HttpResponse

REQUEST_ID_HEADER = "X-Request-ID"

# Accept a caller's id only if it is short and cannot break log lines or headers.
VALID_REQUEST_ID = re.compile(r"[A-Za-z0-9._-]{1,64}")

request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)

JSON_FORMATTER = {
    "()": "pythonjsonlogger.json.JsonFormatter",
    "fmt": "%(levelname)s %(name)s %(process)d %(message)s",
    "rename_fields": {"levelname": "level", "name": "logger"},
    "timestamp": True,
}


class RequestIdFilter(logging.Filter):
    """Adds the current request id to every record, unless the caller set one."""

    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, "request_id"):
            record.request_id = request_id_var.get()
        return True


class RequestIdMiddleware:
    """Tags the request with an id: the caller's X-Request-ID if valid, else a new one.

    The id is available to log records for the duration of the request and is
    returned in the X-Request-ID response header.
    """

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        incoming = request.headers.get(REQUEST_ID_HEADER, "")
        request_id = incoming if VALID_REQUEST_ID.fullmatch(incoming) else uuid.uuid4().hex
        token = request_id_var.set(request_id)
        sentry_sdk.set_tag("request_id", request_id)
        try:
            response = self.get_response(request)
        finally:
            request_id_var.reset(token)
        response[REQUEST_ID_HEADER] = request_id
        return response
