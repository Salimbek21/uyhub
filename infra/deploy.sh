#!/usr/bin/env bash
#
# Deploy UyHub to this server.
#
#   ./infra/deploy.sh            deploy the current checkout
#   ./infra/deploy.sh v0.2.0     check out a tag first, then deploy
#
# Steps: build -> migrate -> start -> smoke test. If the smoke test fails the
# previous images are restored and the services restarted, so a bad deploy costs
# the smoke-test timeout rather than an outage (SPEC section 16).
#
# Safe to re-run. It never touches volumes, so data survives every path through
# this script, including the rollback.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

COMPOSE=(docker compose --env-file .env -f infra/docker-compose.prod.yml)

# Docker Compose silently drops a service's `env_file` when `run` targets a
# service whose profile is not explicitly activated: the container starts, but
# with none of the configuration. Verified on Compose 2.34. So one-shot services
# are always invoked with their profile named.
COMPOSE_TOOLS=("${COMPOSE[@]}" --profile tools)
COMPOSE_INIT=("${COMPOSE[@]}" --profile init)
SMOKE_TIMEOUT=${SMOKE_TIMEOUT:-90}
ROLLBACK_TAG="rollback"

log()  { printf '\n\033[1;34m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33mwarning:\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[1;31merror:\033[0m %s\n' "$*" >&2; exit 1; }

# ---------------------------------------------------------------------------
# Preflight
# ---------------------------------------------------------------------------
[[ -f .env ]] || die ".env is missing. Copy .env.prod.example and fill it in."

# 0600 matters: .env holds the database password and every API token.
perms=$(stat -c '%a' .env 2>/dev/null || stat -f '%OLp' .env)
[[ "$perms" == "600" ]] || warn ".env is mode $perms; it should be 600. Run: chmod 600 .env"

for required in DOMAIN ACME_EMAIL POSTGRES_PASSWORD DATABASE_URL S3_SECRET_KEY \
                TG_API_ID TG_API_HASH PHONE_HASH_KEY \
                BOT_TOKEN CORS_ALLOW_ORIGINS MEDIA_PUBLIC_BASE_URL; do
    grep -qE "^${required}=.+" .env || die "$required is not set in .env"
done

# A filled-in-looking .env that still carries an example placeholder fails much
# later, at the smoke test, with a confusing error. Catch it here instead.
for placeholder in THE_SAME_PASSWORD example.uz replace-with-your; do
    if grep -q "$placeholder" .env; then
        die ".env still contains the placeholder '$placeholder'. Fill it in first."
    fi
done

# The API refuses to start with this on in production, but failing here is
# clearer than a container that restarts in a loop. It makes every caller a
# signed-in user (docs/DECISIONS.md 4.5).
if grep -qiE '^API_ALLOW_INSECURE_AUTH=(true|1|yes)' .env; then
    die "API_ALLOW_INSECURE_AUTH must be false in production: it accepts any caller as a user"
fi

# A wildcard here would let any site on the internet make authenticated calls
# from a victim's browser.
if grep -qE '^CORS_ALLOW_ORIGINS=.*\*' .env; then
    die "CORS_ALLOW_ORIGINS must list exact origins, never '*'"
fi

# The public media host must not point at the originals bucket: those photos
# carry whatever the seller's camera recorded.
if grep -qE "^MEDIA_PUBLIC_BASE_URL=.*$(grep -E '^S3_BUCKET_RAW=' .env | cut -d= -f2-)" .env; then
    die "MEDIA_PUBLIC_BASE_URL points at the private originals bucket"
fi

command -v docker >/dev/null || die "docker is not installed"
docker compose version >/dev/null 2>&1 || die "the docker compose plugin is not installed"

# ---------------------------------------------------------------------------
# Check out the requested revision
# ---------------------------------------------------------------------------
if [[ $# -gt 0 ]]; then
    log "Checking out $1"
    git fetch --all --tags --prune
    git checkout "$1"
fi

VERSION=$(git describe --tags --always --dirty 2>/dev/null || echo "unknown")
export UYHUB_VERSION="$VERSION"
log "Deploying $VERSION"

# ---------------------------------------------------------------------------
# Keep the current images so a failed deploy can be undone
# ---------------------------------------------------------------------------
PREVIOUS_SAVED=false
if docker image inspect "uyhub-backend:${UYHUB_VERSION}" >/dev/null 2>&1 \
    || docker image inspect uyhub-backend:latest >/dev/null 2>&1; then
    current=$(docker image inspect --format '{{.Id}}' uyhub-backend:latest 2>/dev/null || true)
    if [[ -n "$current" ]]; then
        docker tag "$current" "uyhub-backend:${ROLLBACK_TAG}"
        PREVIOUS_SAVED=true
        log "Saved the running backend image as uyhub-backend:${ROLLBACK_TAG}"
    fi
fi

rollback() {
    if [[ "$PREVIOUS_SAVED" != true ]]; then
        warn "No previous image to roll back to; leaving the stack as it is."
        warn "Inspect with: docker compose -f infra/docker-compose.prod.yml logs --tail=200"
        return
    fi
    log "Rolling back to the previous image"
    docker tag "uyhub-backend:${ROLLBACK_TAG}" uyhub-backend:latest
    UYHUB_VERSION=latest "${COMPOSE[@]}" up -d --no-build api caddy
    warn "Rolled back. The failed revision was $VERSION."
}

# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------
log "Building images"
"${COMPOSE[@]}" build
docker tag "uyhub-backend:${UYHUB_VERSION}" uyhub-backend:latest

# ---------------------------------------------------------------------------
# Data stores first, then migrations, then the application
# ---------------------------------------------------------------------------
log "Starting data stores"
"${COMPOSE[@]}" up -d --wait postgres redis seaweedfs

log "Ensuring object storage buckets"
"${COMPOSE_INIT[@]}" run --rm init-storage

log "Applying database migrations"
if ! "${COMPOSE_TOOLS[@]}" run --rm migrate; then
    die "Migrations failed. Nothing was switched over; the previous version is still serving."
fi

log "Refreshing the exchange rate"
# Not fatal: a stale rate only means so'm prices keep yesterday's USD value,
# while a failed deploy over cbu.uz being down would be absurd.
"${COMPOSE_TOOLS[@]}" run --rm --entrypoint uyhub migrate update-rates \
    || warn "Could not fetch today's CBU rate; the last stored one stays in use."

log "Starting application and edge"
"${COMPOSE[@]}" up -d --wait api caddy parser

# The collector needs a Telethon session, and only a human can create one. On a
# server that has never had `make login-userbot` run, starting it would just
# crash-loop, so it is skipped with a clear message instead.
if "${COMPOSE[@]}" run --rm --entrypoint sh -T collector \
        -c 'test -f "${TG_SESSION_PATH:-/data/sessions/uyhub.session}"' >/dev/null 2>&1; then
    log "Starting the collector"
    "${COMPOSE[@]}" up -d collector
else
    warn "No Telethon session found — the collector is not being started."
    warn "Run 'make login-userbot' on this server, then './infra/deploy.sh' again."
fi

log "Publishing the Mini App bundle"
"${COMPOSE[@]}" run --rm miniapp

# ---------------------------------------------------------------------------
# Smoke test
# ---------------------------------------------------------------------------
log "Smoke testing (up to ${SMOKE_TIMEOUT}s)"
deadline=$(( $(date +%s) + SMOKE_TIMEOUT ))
ready=false
while [[ $(date +%s) -lt $deadline ]]; do
    if "${COMPOSE[@]}" exec -T api curl -fsS http://127.0.0.1:8000/readyz >/dev/null 2>&1; then
        ready=true
        break
    fi
    sleep 3
done

if [[ "$ready" != true ]]; then
    warn "/readyz did not come up in time:"
    "${COMPOSE[@]}" exec -T api curl -sS http://127.0.0.1:8000/readyz || true
    "${COMPOSE[@]}" logs --tail=80 api || true
    rollback
    exit 1
fi

# `/readyz` only proves the dependencies answer. This proves the feed route
# exists and that authentication is switched on: an unauthenticated call must
# be refused with 401, not served with 200 and not blown up with 500.
feed_status=$("${COMPOSE[@]}" exec -T api \
    curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8000/v1/listings 2>/dev/null || echo "000")
if [[ "$feed_status" != "401" ]]; then
    warn "GET /v1/listings without credentials returned $feed_status; expected 401."
    [[ "$feed_status" == "200" ]] && warn "The feed is being served to unauthenticated callers."
    "${COMPOSE[@]}" logs --tail=80 api || true
    rollback
    exit 1
fi

# The Mini App must actually be on disk, or Caddy serves an empty directory.
if ! "${COMPOSE[@]}" exec -T caddy test -f /srv/miniapp/index.html; then
    warn "The Mini App bundle is missing from the serving volume."
    rollback
    exit 1
fi

DOMAIN_VALUE=$(grep -E '^DOMAIN=' .env | cut -d= -f2-)

log "Deployed $VERSION"
cat <<EOF

  Mini App   https://app.${DOMAIN_VALUE}
  API        https://api.${DOMAIN_VALUE}/healthz
  Media      https://media.${DOMAIN_VALUE}

First deploy only: TLS certificates take a minute or two to issue. Watch with
  docker compose -f infra/docker-compose.prod.yml logs -f caddy

EOF

log "Removing images no longer referenced"
docker image prune -f >/dev/null || true
