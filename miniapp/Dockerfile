# Mini App build.
#
# The output is static files, not a running server — Caddy serves them. The image
# exists so the build is reproducible and runs in the same place as everything
# else; `infra/docker-compose.prod.yml` runs it once and copies dist into the
# volume Caddy reads.

FROM node:22-bookworm-slim AS builder

WORKDIR /app

# npm ci needs both files and installs exactly what package-lock.json pins.
COPY package.json package-lock.json ./
RUN npm ci

COPY tsconfig.json vite.config.ts index.html ./
COPY src ./src

# VITE_* variables are baked in at build time, so the API origin has to be known
# here rather than at container start.
ARG VITE_API_BASE_URL=""
ENV VITE_API_BASE_URL=${VITE_API_BASE_URL}

RUN npm run build

# ---------------------------------------------------------------------------
# A tiny image whose only job is to hand `dist` to the serving volume.
# ---------------------------------------------------------------------------
FROM alpine:3.21 AS dist

RUN addgroup -g 10001 uyhub && adduser -u 10001 -G uyhub -D -s /sbin/nologin uyhub

COPY --from=builder --chown=uyhub:uyhub /app/dist /dist

# The mount point must exist in the image and be owned by the runtime user.
# Docker seeds an empty named volume from the image path including its
# ownership; without this the volume is created root-owned and a non-root
# container cannot write to it at all.
RUN mkdir -p /srv/miniapp && chown uyhub:uyhub /srv/miniapp

USER uyhub

# `cp -r`, not `cp -a`: -a implies -p, which tries to chown the volume's mount
# point and fails for a non-root user, leaving the bundle unpublished.
# Clears first so a rollback cannot leave files from two bundles mixed together.
CMD ["sh", "-c", "rm -rf /srv/miniapp/* /srv/miniapp/.[!.]* 2>/dev/null; cp -r /dist/. /srv/miniapp/ && echo 'miniapp published'"]
