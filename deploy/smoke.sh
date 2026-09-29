#!/bin/sh
# End-to-end check of a running stack through Caddy.
#
#   deploy/smoke.sh tasks.example.com
#   CURL_OPTS="--insecure --resolve tasks.test:443:127.0.0.1 --resolve tasks.test:80:127.0.0.1" \
#       deploy/smoke.sh tasks.test          # CADDY_TLS=internal, no DNS record
#
# Needs curl and jq. Creates one user and one task.
set -eu

domain=${1:?usage: deploy/smoke.sh DOMAIN}
base="https://$domain"
CURL_OPTS=${CURL_OPTS:-}

# shellcheck disable=SC2086  # CURL_OPTS holds several options
http() { curl --silent --show-error $CURL_OPTS "$@"; }
json() { http --fail -H "Content-Type: application/json" "$@"; }
step() { printf '%s\n' "- $*"; }

step "HTTP redirects to HTTPS"
code=$(http -o /dev/null -w '%{http_code}' "http://$domain/api/health/live/")
test "$code" = 308

step "liveness"
http --fail --retry 10 --retry-delay 3 --retry-all-errors -o /dev/null "$base/api/health/live/"

step "readiness is ok"
http --fail --retry 10 --retry-delay 3 --retry-all-errors "$base/api/health/" |
    jq --exit-status '.status == "ok"' >/dev/null

step "security headers and request id"
headers=$(http -D - -o /dev/null -H "X-Request-ID: smoke-1" "$base/api/health/live/")
printf '%s' "$headers" | grep -qi '^strict-transport-security: max-age='
printf '%s' "$headers" | grep -qi '^content-security-policy: '
printf '%s' "$headers" | grep -qi '^x-request-id: smoke-1'

step "metrics are not public"
code=$(http -o /dev/null -w '%{http_code}' "$base/metrics")
test "$code" = 404

step "register, log in, create, list, complete, comment, refresh, log out"
username="smoke-$(date +%s)-$$"
password="Smoke-$(od -An -N8 -tx1 /dev/urandom | tr -d ' \n')"
json -o /dev/null "$base/api/auth/register/" \
    -d "{\"username\": \"$username\", \"password\": \"$password\"}"
tokens=$(json "$base/api/auth/token/" \
    -d "{\"username\": \"$username\", \"password\": \"$password\"}")
access=$(printf '%s' "$tokens" | jq -r .access)
refresh=$(printf '%s' "$tokens" | jq -r .refresh)
auth="Authorization: Bearer $access"

task_id=$(json -H "$auth" "$base/api/tasks/" -d '{"title": "Smoke test"}' | jq -r .id)
json -H "$auth" "$base/api/tasks/?page_size=5" |
    jq --exit-status '(.results | length) >= 1 and has("next") and (has("count") | not)' >/dev/null
json -X POST -H "$auth" "$base/api/tasks/$task_id/complete/" |
    jq --exit-status '.status == "done" and .completed_at != null' >/dev/null
json -o /dev/null -H "$auth" "$base/api/tasks/$task_id/comments/" -d '{"text": "Done."}'
json -H "$auth" "$base/api/tasks/$task_id/" | jq --exit-status '.comments_count == 1' >/dev/null

rotated=$(json "$base/api/auth/token/refresh/" -d "{\"refresh\": \"$refresh\"}" | jq -r .refresh)
json -o /dev/null "$base/api/auth/token/blacklist/" -d "{\"refresh\": \"$rotated\"}"
code=$(http -o /dev/null -w '%{http_code}' -H "Content-Type: application/json" \
    "$base/api/auth/token/refresh/" -d "{\"refresh\": \"$rotated\"}")
test "$code" = 401

echo "smoke test passed: $base"
