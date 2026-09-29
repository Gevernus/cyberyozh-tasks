"""Gunicorn settings for the container."""

import os
import shutil

from gunicorn.glogging import Logger
from prometheus_client import multiprocess

from core.observability import JSON_FORMATTER, REQUEST_ID_HEADER


def env_int(name: str, default: int) -> int:
    return int(os.environ.get(name) or default)


bind = "0.0.0.0:8000"

# A slow client or query occupies one thread, not the whole worker.
worker_class = "gthread"
workers = env_int("GUNICORN_WORKERS", min(2 * (os.cpu_count() or 1) + 1, 4))
threads = env_int("GUNICORN_THREADS", 4)

timeout = 30
graceful_timeout = 30
keepalive = 5

# Recycling caps memory growth; the jitter keeps workers from restarting together.
max_requests = 1000
max_requests_jitter = 100

# Worker heartbeats on tmpfs: a slow overlay filesystem can stall workers into timeouts.
worker_tmp_dir = "/dev/shm" if os.path.isdir("/dev/shm") else None  # nosec B108


class JsonAccessLogger(Logger):
    """One JSON access record per request, with its request id."""

    def access(self, resp, req, environ, request_time) -> None:
        response_headers = {name.lower(): value for name, value in resp.headers}
        status = int(str(resp.status).split(None, 1)[0])
        self.access_log.info(
            "%s %s %s",
            environ["REQUEST_METHOD"],
            environ.get("PATH_INFO", ""),
            status,
            extra={
                "method": environ["REQUEST_METHOD"],
                "path": environ.get("PATH_INFO", ""),
                "status": status,
                "bytes": getattr(resp, "sent", None),
                "duration_ms": round(request_time.total_seconds() * 1000, 2),
                "remote_addr": environ.get("REMOTE_ADDR"),
                "forwarded_for": environ.get("HTTP_X_FORWARDED_FOR"),
                "user_agent": environ.get("HTTP_USER_AGENT"),
                "request_id": response_headers.get(REQUEST_ID_HEADER.lower()),
            },
        )


logger_class = JsonAccessLogger
logconfig_dict = {
    "formatters": {"json": JSON_FORMATTER},
    "handlers": {
        "stdout": {
            "class": "logging.StreamHandler",
            "stream": "ext://sys.stdout",
            "formatter": "json",
        }
    },
    "root": {"level": "INFO", "handlers": ["stdout"]},
    "loggers": {
        "gunicorn.error": {"level": "INFO", "handlers": ["stdout"], "propagate": False},
        "gunicorn.access": {"level": "INFO", "handlers": ["stdout"], "propagate": False},
    },
}

# Workers write metrics to files here; /metrics aggregates them.
prometheus_dir = os.environ.get("PROMETHEUS_MULTIPROC_DIR")


def on_starting(server) -> None:
    if prometheus_dir:
        # Files from a previous run would count as live workers.
        shutil.rmtree(prometheus_dir, ignore_errors=True)
        os.makedirs(prometheus_dir)


def child_exit(server, worker) -> None:
    if prometheus_dir:
        multiprocess.mark_process_dead(worker.pid)
