# UyHub backend. One image, several entrypoints (SPEC section 2.1):
#   docker run uyhub-backend uyhub api | collector | parser | bot | poster | scheduler
#
# Built on the server by infra/deploy.sh, or in CI on a tag.

# ---------------------------------------------------------------------------
# Builder — resolve and install dependencies into a self-contained venv
# ---------------------------------------------------------------------------
FROM python:3.12-slim-bookworm AS builder

# uv is installed with pip rather than copied from its own image so the build
# depends on one registry instead of two.
RUN pip install --no-cache-dir "uv==0.13.5"

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

# Dependencies first: this layer is cached until uv.lock changes, so ordinary
# code changes rebuild in seconds.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY src ./src
COPY migrations ./migrations
COPY alembic.ini ./
RUN uv sync --frozen --no-dev

# ---------------------------------------------------------------------------
# Runtime
# ---------------------------------------------------------------------------
FROM python:3.12-slim-bookworm AS runtime

# curl is used by the container healthcheck only.
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

# Non-root (SPEC section 15). A fixed uid keeps volume ownership predictable
# across rebuilds.
RUN groupadd --gid 10001 uyhub \
    && useradd --uid 10001 --gid uyhub --create-home --shell /usr/sbin/nologin uyhub

WORKDIR /app

COPY --from=builder --chown=uyhub:uyhub /app /app

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    APP_ENV=production \
    LOG_FORMAT=json \
    API_HOST=0.0.0.0 \
    API_PORT=8000

# Telethon's session file lives here on a volume, mode 0600 (SPEC 4.1).
RUN mkdir -p /data/sessions && chown -R uyhub:uyhub /data && chmod 700 /data/sessions
VOLUME ["/data"]

USER uyhub

EXPOSE 8000

# Liveness only — readiness is probed by Caddy and the deploy smoke test, since
# a dependency being down should not make Docker restart a healthy process.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8000/healthz || exit 1

ENTRYPOINT ["uyhub"]
CMD ["api"]
