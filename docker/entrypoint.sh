#!/bin/sh
set -eu

# On by default for the single-instance compose setup; with several replicas set
# DJANGO_MIGRATE=0 and run migrations once as a separate release step.
if [ "${DJANGO_MIGRATE:-1}" = "1" ]; then
    python manage.py migrate --noinput
fi

exec "$@"
