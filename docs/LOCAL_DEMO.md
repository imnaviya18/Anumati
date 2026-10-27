# Anumati local demonstration

Open http://127.0.0.1:15173/ . This is synthetic local data, not an AICTE production service.

## Start or stop

From the project directory:

```sh
docker compose -p anumati-demo -f docker-compose.demo.yml up --build -d
docker compose -p anumati-demo -f docker-compose.demo.yml ps
# Stop while retaining the demonstration database and evidence files:
docker compose -p anumati-demo -f docker-compose.demo.yml down
```

The stack contains React served by Nginx, Django, PostgreSQL 16, Redis 7, Celery worker and Celery Beat. Only the frontend binds to host loopback port 15173. Project-specific named volumes retain synthetic records. This stack does not use the existing application database. Startup migrations and synthetic seeding are repeatable.

## Accounts

All demo accounts use password `DemoOnly-2026-Local!`. These are intentionally public local demonstration credentials; never reuse them for production.

| Username | Workspace |
| --- | --- |
| demo_institution | Intake, evidence and compliance for two synthetic institutions |
| demo_officer | Assigned scrutiny, evidence review and compliance |
| demo_evc | Demonstration EVC committee |
| demo_authority | Demonstration regulatory decisions |
| demo_policy | Draft policy administration |
| demo_admin | Technical administration; no regulatory authority |
| demo_auditor | Scoped reporting and oversight |

Sign out before switching roles. Initial synthetic applications are assigned to the demo officer. Institution and case UUIDs are still used in some administration forms; case details expose the relevant IDs.

## Policies and approval gates

`DEMO-ONLY-2026` is active only for synthetic local workflows. Its times and decision rules are illustrative.

`APH-2024-2027-RESEARCH-DRAFT` remains DRAFT and non-demonstration. Source configuration: `docs/policy/aph_2024_2027_draft.json`. The 2026–27 addendum, amendments, annual calendar and internal administrative procedures are pending validation. No hosting provider or government domain is presumed authorised.

`ALLOW_AUTHORITATIVE_POLICY_ACTIVATION` defaults to false. Keep it false until the responsible owner approves the configuration and production rollout separately. Enabling that setting alone does not satisfy the rule provenance, effective-date, validation and approval checks. Production settings disallow demonstration policies.

## Reproduce verification

```sh
python3 scripts/smoke_demo.py
python3 scripts/smoke_workspaces.py
cd frontend
npm ci
npm test
npm run lint
npm run build
npm run format:check
```

The smoke test adds a new synthetic case and document each run and exercises the actual worker; it does not send external messages. Run it only against this seeded demonstration. Backend tests require a disposable PostgreSQL database with test-database creation permission; configure POSTGRES_HOST, POSTGRES_PORT, POSTGRES_DB, POSTGRES_USER and POSTGRES_PASSWORD, then run `.venv/bin/pytest -c backend/pytest.ini backend` from the repository root.

Final evidence: See the current reports for final backend/frontend test counts, actual HTTP/worker smoke, seed repeat, migration checks, lint and builds. See `test-reports/current-postgres.txt`, `current-frontend.txt`, `demo-http-smoke.json` and `demo-stack-build.txt`.

## Architecture feature coverage

See `ARCHITECTURE_WORKSPACE_ACCEPTANCE.md` for each listed workspace feature, source-boundary details and verification evidence. Policy changes now require a separate competent-authority approval before activation.

## Outstanding production work

See `IMPLEMENTATION_REVIEW_2026-10-27.md` for the full audit and limits. Approved policy catalogue, owner-approved hosting/secrets/TLS, identity hardening, antivirus, external integrations and operational recovery/load verification remain outstanding. Some administration workflows still use IDs or JSON; comprehensive browser coverage is not claimed. Passing tests does not establish that the entire project has no bugs.
