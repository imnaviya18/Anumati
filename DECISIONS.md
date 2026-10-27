# ARCHITECTURAL & ENGINEERING DECISIONS — ANUMATI v2 (SIH 26262)

Every non-obvious architectural and implementation decision is recorded here with its exact source reference from `Anumati_Detailed_Diagrams.pdf` (Sheets 01–07) or Problem Statement 26262.

## DEC-001: Modular Monolith in Django + React Single-Page Application
- **Source:** Sheet 01 header & middle banner (`DJANGO DOMAIN SERVICES | one modular backend; explicit commands, scoped queries and atomic database transactions`), Sheet 05 (`All domain services share one Django codebase`).
- **Decision:** Structure the backend as one Django project (`config/`) with 18 explicitly bounded domain apps under `backend/apps/` (`accounts`, `access`, `organisation`, `cases`, `routing`, `evc`, `decisions`, `compliance`, `documents`, `policy`, `deadlines`, `escalation`, `notifications`, `communications`, `outbox`, `audit`, `reporting`, `adapters`, `common`). Each domain app separates `models.py`, `services.py` (mutations/business rules), `selectors.py` (scoped reads), `api/` (DRF views/serializers), `migrations/`, and `tests/`.

## DEC-002: Zero Extra Libraries Outside Approved Tech Stack
- **Source:** Prompt `STRICT TECH STACK (nothing else)` & Sheet 01, 05.
- **Decision:**
  - Backend uses only Python 3.12, `Django`, `djangorestframework`, `psycopg[binary]`, `celery`, `redis`, and `pytest` / `pytest-django` / `coverage` / `ruff` for testing and linting.
  - Frontend uses only `react`, `react-dom`, `react-router-dom`, and `vite` / `@vitejs/plugin-react` / `vitest` / `@testing-library/react` / `@testing-library/jest-dom` / `jsdom` / `eslint` / `prettier` for build, test, and lint.
  - No UI component kits, no third-party state libraries, no external HTTP clients (uses local `fetch` wrapper), and no ClamAV/OCR/AI libraries.

## DEC-003: Append-Only Audit Enforcement via Separate PostgreSQL Role & Schema + Sealed Exports
- **Source:** Sheet 01 (Block 09), Sheet 06 (L2), Sheet 07 (N5: `Restrict audit update/delete; protect independent retention. Hashes alone do not stop privileged rewrites`), and Prompt (`Audit: append-only; enforced by a separate write-only database role and schema, plus periodic sealed exports to a location the application cannot modify`).
- **Decision:** Audit records reside in a dedicated schema/table with database-level triggers and role permissions revoking `UPDATE`, `DELETE`, and `TRUNCATE` from the application database role, complemented by a sealed export command writing immutable, SHA-256-manifested bundles to a write-once export volume. Full mechanism and proving tests are documented in `SECURITY_NOTES.md` and implemented in Stage 2 & Stage 7.

## DEC-004: Guarded Decision Command & Single-Transaction Atomic Write Set
- **Source:** Sheet 06 (K1–K6, L1–L4).
- **Decision:** Every state-mutating workflow command requires authentication, deny-by-default scope check, idempotency key + SHA-256 payload fingerprint, `SELECT ... FOR UPDATE` row lock on the case aggregate, expected version check (returning HTTP 409 on mismatch), and single-transaction commit of domain state + decision + obligations/deadlines + append-only audit + durable outbox event + saved idempotency response, with zero network I/O inside `transaction.atomic()`.
