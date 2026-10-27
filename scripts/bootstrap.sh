#!/usr/bin/env bash
# Bootstrap initial roles, permission groups, and technical administrator from env vars only (DATA RULES)
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if command -v docker >/dev/null 2>&1 && docker compose ps backend --status running >/dev/null 2>&1; then
  docker compose exec -T backend python manage.py migrate --noinput
else
  (cd "$ROOT_DIR/backend" && python3 manage.py migrate --noinput)
fi
echo "Bootstrap migrations applied."
