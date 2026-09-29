# syntax=docker/dockerfile:1

# --- builder: install the locked dependencies into a separate prefix --------
FROM python:3.12-slim AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Prebuilt wheels only, checked against the lock file hashes.
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

# Code and static files stay owned by root, read-only for the app user.
COPY . .
RUN DJANGO_DEBUG=False DJANGO_SECRET_KEY=collectstatic-only \
    python manage.py collectstatic --noinput

# Workers share metrics through files here; every process that loads Django needs it.
ENV PROMETHEUS_MULTIPROC_DIR=/tmp/prometheus
RUN install -d -o app -g app "$PROMETHEUS_MULTIPROC_DIR"

USER app

EXPOSE 8000

# Liveness only: restarting does not fix a database or Redis outage.
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/health/live/', timeout=4)"]

CMD ["gunicorn", "--config", "gunicorn.conf.py", "config.wsgi"]
