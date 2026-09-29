# syntax=docker/dockerfile:1

# --- builder: install the locked dependencies into a separate prefix --------
FROM python:3.12-slim AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Only prebuilt wheels, each checked against the hash in the lock file: nothing is
# compiled or resolved at build time.
COPY requirements.txt /tmp/requirements.txt
RUN pip install --require-hashes --only-binary=:all: --no-deps --prefix=/install \
    --requirement /tmp/requirements.txt

# --- runtime: dependencies + code, no build tools, no dev dependencies ------
FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN groupadd --system --gid 10001 app \
    && useradd --system --uid 10001 --gid app --no-create-home app

WORKDIR /app

COPY --from=builder /install /usr/local

# Code and static files stay owned by root: the app user can read but not modify them.
COPY . .
RUN DJANGO_DEBUG=False DJANGO_SECRET_KEY=collectstatic-only \
    python manage.py collectstatic --noinput

# Gunicorn workers share metrics through files in this directory; it must exist for
# any process that loads Django, manage.py commands included.
ENV PROMETHEUS_MULTIPROC_DIR=/tmp/prometheus
RUN install -d -o app -g app "$PROMETHEUS_MULTIPROC_DIR"

USER app

EXPOSE 8000

# Liveness only: a database or Redis outage is not fixed by restarting the container.
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/health/live/', timeout=4)"]

CMD ["gunicorn", "--config", "gunicorn.conf.py", "config.wsgi"]
