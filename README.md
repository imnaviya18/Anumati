Local synthetic demo: see [startup, accounts and test commands](docs/LOCAL_DEMO.md).

> **Current status (27 October 2026):** See [implementation review](docs/IMPLEMENTATION_REVIEW_2026-10-27.md) for verified repairs, test evidence and remaining production blockers. Earlier stage summaries overstate completeness.

# ANUMATI v2 (SIH 26262)

**Integrated AICTE Approval Workflow Automation, Compliance Monitoring and Alert Management System**

ANUMATI v2 is a self-contained modular-monolith prototype built strictly from `Anumati_Detailed_Diagrams.pdf` (Sheets 01–07) and Problem Statement 26262 / AICTE Approval Process Handbook (APH 2024-27).

## Architecture & Tech Stack
- **Frontend:** React JS (functional components, hooks), React Router, local `fetch` wrapper, Vitest + React Testing Library, ESLint + Prettier, plain CSS.
- **Backend:** Python + Django + Django REST Framework (modular monolith), Session Auth + CSRF.
- **Database:** PostgreSQL (system of record for cases, stages, assignments, decisions, obligations, deadlines, outbox, leases, and append-only audit).
- **Asynchronous Execution:** Celery + Celery Beat with Redis as message broker only (durable intent owned by PostgreSQL outbox and due-work registers).
- **Private File Storage:** Local versioned object storage with SHA-256 checksums, upload quarantine pipeline, and short-lived download grants.
- **External Systems:** Self-contained runtime (`docker compose up`) with zero external network calls; AICTE ERP, NSWS, SSO, and SMS are implemented strictly as disabled interface ports (`backend/apps/adapters/`), and SMTP email delivery is disabled by default.

## Quick Start
```bash
cp .env.example .env
docker compose up --build -d
make test
make lint
```

## Documentation Index
- [`TRACEABILITY.md`](./TRACEABILITY.md) — Complete mapping of every diagram element and problem statement clause to code locations and tests.
- [`OPEN_QUESTIONS.md`](./OPEN_QUESTIONS.md) — Decisions required from the engineering lead/competent authority, source conflict resolutions, and policy-driven data catalogue.
- [`DECISIONS.md`](./DECISIONS.md) — Architectural and engineering decisions with source references.
- [`SECURITY_NOTES.md`](./SECURITY_NOTES.md) — Access control, append-only DB audit role, quarantine pipeline, and proving tests.
- [`PROGRESS.md`](./PROGRESS.md) — Gated stage progress and test report links.
- [`docs/architecture.md`](./docs/architecture.md) — Runtime and domain architecture.
- [`docs/api_reference.md`](./docs/api_reference.md) — REST API boundary and command contracts.
- [`docs/role_guides.md`](./docs/role_guides.md) — Workspace and role operational guides.
- [`docs/recovery_runbook.md`](./docs/recovery_runbook.md) — Outbox reconciliation, backup, and restore runbook.

## Local development without Docker

```bash
python3 -m venv .venv
.venv/bin/pip install -r backend/requirements.txt
cd frontend && npm ci && cd ..
USE_SQLITE_FALLBACK=true .venv/bin/python backend/manage.py migrate
USE_SQLITE_FALLBACK=true .venv/bin/python backend/manage.py runserver 127.0.0.1:8000
# In a second terminal:
cd frontend && npm run dev
```

Open http://localhost:5173. Create the initial technical account using `bootstrap_anumati` with explicit `BOOTSTRAP_ADMIN_USERNAME`, `BOOTSTRAP_ADMIN_EMAIL` and `BOOTSTRAP_ADMIN_PASSWORD` environment values. The bootstrap does not create regulatory users or approved policy data. SQLite is for development; run concurrency acceptance tests against PostgreSQL.

Docker now serves compiled React assets through Nginx at port 5173. `/api/` stays same-origin. The configuration is a local deployment; production TLS and hardened service credentials are not supplied.
