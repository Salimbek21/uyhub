#!/usr/bin/env sh
# Nightly backup of everything that cannot be rebuilt.
#
# Run by the `backup` service in docker-compose.prod.yml, inside the Postgres
# image so `pg_dump` matches the server version exactly.
#
# What is backed up and why:
#
#   postgres   — listings, sources, users, and the raw messages everything is
#                derived from. Re-collecting is impossible: Telegram history is
#                only retrievable while the posts are still up, and the ones
#                that matter are the ones that get deleted.
#   seaweedfs  — NOT backed up here. Photos are large, and a lost photo is a
#                missing image on a card, not a lost listing. Re-downloading is
#                possible while the source post survives. This is a deliberate
#                trade; see docs/DECISIONS.md 6.1.
#
# A backup nobody has restored is a hope, not a backup. The restore procedure
# is in docs/RUNBOOK.md section 6 and should be rehearsed before launch.

set -eu

: "${POSTGRES_USER:?}"
: "${POSTGRES_DB:?}"
: "${BACKUP_KEEP_DAYS:=14}"

DIR=/backup
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
TARGET="$DIR/uyhub-$STAMP.sql.gz"

log() { echo "{\"service\":\"backup\",\"event\":\"$1\",\"detail\":\"${2:-}\"}"; }

mkdir -p "$DIR"

# --clean --if-exists so the dump can be replayed over a live database during a
# restore without dropping it first. A partial file must never be left looking
# like a good backup, so write to .part and rename only on success.
if pg_dump --username="$POSTGRES_USER" --dbname="$POSTGRES_DB" \
        --clean --if-exists --no-owner --no-privileges \
        | gzip -9 > "$TARGET.part"; then
    mv "$TARGET.part" "$TARGET"
else
    rm -f "$TARGET.part"
    log backup_failed "pg_dump returned non-zero"
    exit 1
fi

SIZE=$(wc -c < "$TARGET")

# A dump far smaller than the last one means something went wrong quietly —
# an empty database, a permissions problem, a truncated pipe.
PREVIOUS=$(ls -1t "$DIR"/uyhub-*.sql.gz 2>/dev/null | sed -n 2p || true)
if [ -n "$PREVIOUS" ]; then
    PREV_SIZE=$(wc -c < "$PREVIOUS")
    if [ "$SIZE" -lt $((PREV_SIZE / 2)) ]; then
        log backup_suspiciously_small "$SIZE bytes, previous was $PREV_SIZE"
    fi
fi

log backup_written "$TARGET ($SIZE bytes)"

# Retention. Deleting runs after a successful write, never before, so a failing
# backup can never erase the last good one.
find "$DIR" -name 'uyhub-*.sql.gz' -mtime "+$BACKUP_KEEP_DAYS" -delete
log retention_applied "kept $BACKUP_KEEP_DAYS days"
