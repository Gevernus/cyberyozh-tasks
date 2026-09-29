# syntax=docker/dockerfile:1

# --- builder: resolve and build every dependency into wheels -----------------
FROM python:3.12-slim AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

COPY requirements.txt /tmp/requirements.txt
RUN pip wheel --wheel-dir /wheels --requirement /tmp/requirements.txt

# --- runtime: wheels + code, no compilers, no dev dependencies --------------
FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PROMETHEUS_MULTIPROC_DIR=/tmp/prometheus

# Gunicorn workers share metrics through files in PROMETHEUS_MULTIPROC_DIR; it must
# exist for any process that loads Django, including manage.py commands.
RUN groupadd --system --gid 10001 app \
    && useradd --system --uid 10001 --gid app --no-create-home app \
    && install -d -o app -g app "$PROMETHEUS_MULTIPROC_DIR"

WORKDIR /app

COPY requirements.txt .
RUN --mount=type=bind,from=builder,source=/wheels,target=/wheels \
    pip install --no-index --find-links=/wheels --requirement requirements.txt

# Code and static files stay owned by root: the app user can read but not modify them.
COPY . .
RUN DJANGO_DEBUG=False DJANGO_SECRET_KEY=collectstatic-only \
    python manage.py collectstatic --noinput

USER app

EXPOSE 8000

# Liveness only: a database or Redis outage is not fixed by restarting the container.
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/health/live/', timeout=4)"]

CMD ["gunicorn", "--config", "gunicorn.conf.py", "config.wsgi"]
