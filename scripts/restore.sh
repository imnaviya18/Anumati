#!/usr/bin/env bash
# Explicit offline restore; never report success when nothing was restored.
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"
BACKUP_PATH="${1:?Usage: restore.sh /absolute/path/to/backup}"
[ -f "$BACKUP_PATH/db.dump" ] && [ -f "$BACKUP_PATH/storage.tar.gz" ] && [ -f "$BACKUP_PATH/manifest.sha256" ]
(cd "$BACKUP_PATH" && shasum -a 256 -c manifest.sha256)
if [ -z "$(docker compose ps --status running -q db)" ]; then echo "Start PostgreSQL before restoring." >&2; exit 1; fi
for service in backend worker beat; do
  if [ -n "$(docker compose ps --status running -q "$service")" ]; then echo "Stop backend, worker and beat before restoring." >&2; exit 1; fi
done
docker compose exec -T db sh -c 'pg_restore --exit-on-error --single-transaction -U "$POSTGRES_USER" -d "$POSTGRES_DB" --clean --if-exists' < "$BACKUP_PATH/db.dump"
docker compose run --rm --no-deps -T backend tar -xzf - -C /var/lib/anumati < "$BACKUP_PATH/storage.tar.gz"
echo "Database and file archive restored. Reconcile storage and run smoke tests before starting writers."
