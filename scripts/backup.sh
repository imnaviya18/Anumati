#!/usr/bin/env bash
# Maintenance-window backup: quiesce application writers before database + file snapshot.
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"
if [ -z "$(docker compose ps --status running -q db)" ]; then
  echo "PostgreSQL service is not running. No backup was created." >&2
  exit 1
fi
BACKUP_DIR="${BACKUP_DIR:-$ROOT_DIR/backups}"
TARGET_DIR="$BACKUP_DIR/backup_$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p "$TARGET_DIR"
RUNNING_WRITERS=()
for service in backend worker beat; do
  if [ -n "$(docker compose ps --status running -q "$service")" ]; then RUNNING_WRITERS+=("$service"); fi
done
resume_writers() { if [ "${#RUNNING_WRITERS[@]}" -gt 0 ]; then docker compose start "${RUNNING_WRITERS[@]}"; fi; }
trap resume_writers EXIT
if [ "${#RUNNING_WRITERS[@]}" -gt 0 ]; then docker compose stop "${RUNNING_WRITERS[@]}"; fi
docker compose exec -T db sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' > "$TARGET_DIR/db.dump"
docker compose run --rm --no-deps -T backend tar -czf - -C /var/lib/anumati private_storage sealed_audit_exports > "$TARGET_DIR/storage.tar.gz"
(cd "$TARGET_DIR" && shasum -a 256 db.dump storage.tar.gz > manifest.sha256)
echo "Maintenance snapshot created: $TARGET_DIR"
