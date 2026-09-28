"""Gunicorn settings for the container; sizing knobs come from the environment."""

import os


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

accesslog = "-"
errorlog = "-"
access_log_format = '%(h)s "%(r)s" %(s)s %(b)s %(M)sms "%(a)s"'

# Proxies allowed to set X-Forwarded-Proto for gunicorn itself.
forwarded_allow_ips = os.environ.get("FORWARDED_ALLOW_IPS") or "127.0.0.1,::1"
