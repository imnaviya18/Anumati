#!/usr/bin/env bash
# Unified test and lint runner for ANUMATI v2 (Sheet 07 Q1-Q5, GATE RULE)
set -euo pipefail

export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MODE="${1:-all}"
cd "$ROOT_DIR"
export PATH="$ROOT_DIR/.venv/bin:$PATH"

run_lint() {
  echo "=== [1/2] Backend Lint & Static Verification ==="
  if command -v docker >/dev/null 2>&1 && [ -n "$(docker compose ps --status running -q backend 2>/dev/null)" ]; then
    docker compose exec -T backend ruff check .
  elif python3 -c "import ruff" >/dev/null 2>&1; then
    (cd "$ROOT_DIR/backend" && python3 -m ruff check .)
  else
    (
      cd "$ROOT_DIR/backend"
      python3 -m compileall -q config apps tests
      USE_SQLITE_FALLBACK="${USE_SQLITE_FALLBACK:-true}" python3 manage.py check
      USE_SQLITE_FALLBACK="${USE_SQLITE_FALLBACK:-true}" python3 manage.py makemigrations --check --dry-run
    )
  fi

  echo "=== [2/2] Frontend Lint & Module Verification ==="
  if command -v docker >/dev/null 2>&1 && [ -n "$(docker compose ps --status running -q frontend 2>/dev/null)" ]; then
    docker compose exec -T frontend npm run lint
  elif [ -d "$ROOT_DIR/frontend/node_modules" ]; then
    (cd "$ROOT_DIR/frontend" && npm run lint)
  else
    echo "Install frontend dependencies with npm ci before linting." >&2
    return 1
  fi
}

run_test() {
  echo "=== [1/2] Backend Tests ==="
  if command -v docker >/dev/null 2>&1 && [ -n "$(docker compose ps --status running -q backend 2>/dev/null)" ]; then
    docker compose exec -T backend coverage run -m pytest
    docker compose exec -T backend coverage report -m
  elif python3 -c "import pytest, coverage" >/dev/null 2>&1; then
    (cd "$ROOT_DIR/backend" && USE_SQLITE_FALLBACK="${USE_SQLITE_FALLBACK:-true}" python3 -m coverage run -m pytest && python3 -m coverage report -m)
  else
    (cd "$ROOT_DIR/backend" && USE_SQLITE_FALLBACK="${USE_SQLITE_FALLBACK:-true}" python3 manage.py test apps tests -v 2)
  fi

  echo "=== [2/2] Frontend Tests (vitest) ==="
  if command -v docker >/dev/null 2>&1 && [ -n "$(docker compose ps --status running -q frontend 2>/dev/null)" ]; then
    docker compose exec -T frontend npm test -- --run
  elif [ -d "$ROOT_DIR/frontend/node_modules" ]; then
    (cd "$ROOT_DIR/frontend" && npm test -- --run)
  else
    echo "Install frontend dependencies with npm ci before testing." >&2
    return 1
  fi
}

case "$MODE" in
  lint)
    run_lint
    ;;
  test)
    run_test
    ;;
  all)
    run_lint
    run_test
    ;;
  *)
    echo "Usage: $0 {lint|test|all}" >&2
    exit 1
    ;;
esac
