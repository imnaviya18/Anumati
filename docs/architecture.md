# Architecture Overview — ANUMATI v2 (Sheets 01, 05, 06, 07)

## 1. System Topology
- **React JS Frontend (`frontend/`):** Serves the four workspaces defined on Sheet 01 (`institution`, `officer`, `oversight`, `policy` + `admin`). Communicates with Django exclusively over same-origin `/api` using session authentication and CSRF tokens.
- **Django Modular Monolith (`backend/`):** Implements all 18 domain modules sharing a single PostgreSQL database (`10 SYSTEM OF RECORD`).
- **PostgreSQL (`db`):** Owns authoritative domain state, versioned case files, deadlines, idempotency keys, append-only audit records, and durable outbox/lease queues.
- **Redis (`redis`) & Celery (`worker`, `beat`):** Redis acts strictly as a transient message transport for task IDs. Celery Beat triggers periodic due-work scans and outbox reconciliation; Celery workers claim leased work and execute external/background attempts outside database transactions.
- **Private File Storage (`PRIVATE_STORAGE_ROOT`):** Local versioned object store with SHA-256 checksums, upload quarantine (`QUARANTINED -> SCANNING -> CLEAN / REJECTED`), and short-lived download grants.
- **External Adapters (`backend/apps/adapters/`):** Disabled interface ports for AICTE ERP, NSWS, SSO, Payment Gateway, and SMS; optional SMTP email backend disabled by default.

## 2. Layering Rules
- `api/`: Request parsing, authentication/CSRF enforcement, correlation ID attachment, response formatting.
- `services.py`: Command validation, scoped authorization checks, row locking (`SELECT ... FOR UPDATE`), state transitions, atomic writes (`transaction.atomic()`).
- `selectors.py`: Scoped read queries, pagination, and reporting projections without N+1 queries.
- `models.py`: Relational schema, foreign keys, check constraints, unique constraints, and queue indexes.
