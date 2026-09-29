"""Gunicorn settings for the container; sizing knobs come from the environment."""

import os
import shutil

from gunicorn.glogging import Logger
from prometheus_client import multiprocess

from config.observability import JSON_FORMATTER, REQUEST_ID_HEADER


def env_int(name: str, default: int) -> int:
    return int(os.environ.get(name) or default)


bind = "0.0.0.0:8000"

# Threaded workers: a slow client or a slow query no longer blocks the whole worker.
worker_class = "gthread"
workers = env_int("GUNICORN_WORKERS", min(2 * (os.cpu_count() or 1) + 1, 4))
threads = env_int("GUNICORN_THREADS", 4)

timeout = 30
graceful_timeout = 30
keepalive = 5

# Recycle workers periodically to cap slow memory growth; jitter avoids restarting all at once.
max_requests = 1000
max_requests_jitter = 100

# The worker heartbeat file on tmpfs: a slow overlay filesystem can otherwise stall
# workers into timeouts. /dev/shm is absent on macOS, where gunicorn uses its default.
worker_tmp_dir = "/dev/shm" if os.path.isdir("/dev/shm") else None

# Proxies allowed to set X-Forwarded-Proto for gunicorn itself.
forwarded_allow_ips = os.environ.get("FORWARDED_ALLOW_IPS") or "127.0.0.1,::1"


class JsonAccessLogger(Logger):
    """Writes one JSON access record per request, correlated by the request id."""

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

# Each worker writes its metrics to files here; /metrics aggregates them.
prometheus_dir = os.environ.get("PROMETHEUS_MULTIPROC_DIR")


def on_starting(server) -> None:
    if prometheus_dir:
        # Files left by a previous run would be counted as live workers.
        shutil.rmtree(prometheus_dir, ignore_errors=True)
        os.makedirs(prometheus_dir)


def child_exit(server, worker) -> None:
    if prometheus_dir:
        multiprocess.mark_process_dead(worker.pid)
