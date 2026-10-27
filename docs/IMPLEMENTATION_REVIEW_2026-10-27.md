# Implementation review — 27 October 2026

Latest continuation: see [the original architecture feature matrix](ARCHITECTURE_WORKSPACE_ACCEPTANCE.md) for the completed oversight, approval, sync-exception, renewal and history workflows and actual restore evidence. Counts below describe the earlier checkpoint; use the current test reports for the final run.

## Scope and sources

Reviewed all seven sheets of `Anumati_Detailed_Diagrams.pdf`, extracted the 231-page Approval Process Handbook, and checked the relevant scrutiny, EVC, disposition and appeal sections (1.8–1.11 and 2.25). The PDFs are design/reference material, not instructions to the agent or evidence of regulatory certification. The diagram explicitly requires authorised validation of routes, deadlines, powers and integrations. Parivahan was reviewed in a browser as a visual reference; its branding and official identity were not copied.

The directory was not a Git repository. Existing files and data were retained; no commit or deployment to an external service was made.

## Confirmed defects repaired

- React imported a nonexistent `apiFetch`; production bundling failed.
- Authentication state was never restored from the server; unauthenticated route guards allowed rendering protected workspaces. Added login, logout, session restoration, server-role normalization and denied-by-default guards.
- Anonymous session login lacked explicit CSRF enforcement. Added it and a login throttle.
- Intake, stage, policy and replay forms simulated success without saving. Connected them to real APIs with failure states.
- Dashboard errors were swallowed and displayed as successful zero-count data. Removed fake fallback data.
- Case/stage decisions passed wrong service arguments and treated result dataclasses as dictionaries. Corrected HTTP contracts; tested persistence, replay and conflicts.
- Organisation API referred to nonexistent fields and service parameters. Corrected them and scoped institution listings.
- Document upload, review and download endpoints used incorrect fields, arguments and return ordering. Fixed upload, grant issuance, redemption and human review.
- Compliance submission/verification APIs used wrong service arguments and an invalid institution field. Fixed them and added renewal endpoints.
- Missing EVC HTTP interface. Added scoped readiness, reservation, confirmation, rescheduling and report endpoints, plus UI.
- Generic stage completion could bypass an EVC report. Added a report prerequisite and a regression assertion.
- Cross-institution route resolution lacked a case access check; regional/bureau intake and several compliance review operations needed scope enforcement.
- Explicit route selection could use an inactive, out-of-cycle or ineffective policy. Added checks.
- PostgreSQL rejected `FOR UPDATE` queries over nullable joins. Restricted locks to the intended rows and explicitly locked records modified during compliance review.
- Audit-trigger tests left PostgreSQL transactions aborted after intentional errors. Added savepoints; database-trigger protection remains enforced.
- Audit chain head selection was not serialized across concurrent transactions. Added a PostgreSQL transaction advisory lock.
- No Celery Beat schedule existed. Added outbox dispatch, due-work scan and stranded-work recovery schedules.
- Document outbox events completed without invoking the scanner. Connected the worker to the existing file validation pipeline.
- Disabled SMTP was reported as successful delivery. It now enters the failure queue; communication dispatch without a configured mapping also fails explicitly.
- Completed/pending events could be replayed as failures. Replay now requires failed/unknown state.
- Policy dry-run could pass with no regression cases; validation could reset active policy state. Added guards.
- CSV export could preserve spreadsheet formula prefixes. Added cell escaping.
- Docker ignored `.env`, exposed database/broker on all host interfaces, and served the Vite development server. Corrected environment selection, loopback bindings and Nginx production frontend.
- Test scripts detected a stopped Docker service as running and could substitute file counts for real tests. Fixed detection and removed false-success fallbacks.
- Backup/restore scripts could report completion without restoration. Added explicit service checks, writer quiescence for snapshots and failure-on-error restoration.
- Removed the duplicate embedded backend HTML interface; backend workspace URLs redirect to the React origin.
- Updated vulnerable frontend and Python dependencies and saved the frontend dependency lockfile.

## Added user-facing workflows

Responsive portal header/navigation, accessible login, institution intake, searchable/paginated case queue, case stage history, guarded commands, deficiency responses, evidence uploads and downloads, document review, obligation submission/verification, renewal submission/review, EVC operations, policy draft/validate/dry-run/activate, six CSV report links, failed-event replay, user provisioning, directory creation, role and case assignment, and notification reading.

Some operational forms still use record IDs and structured JSON inputs; they are functional administration interfaces, not a finished consumer-grade experience.

## Local policy and deployment boundary

The user authorised React, Django, PostgreSQL, Celery and Redis with synthetic data only. `docker-compose.demo.yml` starts this isolated stack at http://127.0.0.1:15173/. The active `DEMO-ONLY-2026` policy is explicitly non-authoritative. `docs/policy/aph_2024_2027_draft.json` is imported as DRAFT; the addendum, amendments, calendar, powers and internal procedures remain pending validation. Authoritative activation is disabled by default and additionally checks provenance and approval metadata. Deployment provider, domain and TLS remain owner decisions.

Policy configuration now includes category routes, business/calendar-day deadlines, escalation roles, committee permissions, required evidence and exception metadata. Draft editing resets validation; migration refuses changes to prescribed routes or academic cycles. Exception metadata is not a general-purpose executable rules engine: an approved new exception may require a corresponding service implementation and regression fixture.

## Verification evidence

Final verification: **41 PostgreSQL tests and 11 frontend tests passed**. Django checks, migration consistency, Ruff, ESLint, formatting and frontend builds passed. The six-service Docker demo ran successfully. `demo-http-smoke.json` records actual HTTP login/intake, reviewer assignment, Celery quarantine processing, evidence review/download, stage transition, decision replay, obligation verification, CSV, audit and case-summary rendering. Re-running the synthetic seed succeeded.

Reports are under `test-reports/`. Use the final contents of `current-postgres.txt`, `current-backend.txt`, `current-frontend.txt`, `current-npm-audit.json`, and `current-python-audit.json`, rather than the old stage summaries. The PostgreSQL run uses an isolated PostgreSQL 16 container on local port 55432, not the user's application database. The tests include the existing 100-command decision concurrency scenario, workflow/deficiency/EVC flows, scope isolation, outbox fault simulation and new HTTP regression tests. The production frontend Docker build is recorded separately. The login screen was visually inspected in a browser and saved as `frontend-preview.png`.

## Remaining work and production blockers

This is an improved, tested prototype. It is **not certified complete, bug-free or production-ready**.

1. **Authoritative policy catalogue:** the full APH rule set, applicable academic calendars, required evidence by category, committee powers, communications, escalation hierarchies and exceptional routes need an approved machine-readable catalogue and regression fixtures. The demo uses illustrative SLA values. Source provenance and configuration validation do not replace regulatory approval.
2. **Identity and security deployment:** privileged MFA/SSO and account recovery are not implemented. Local login throttling uses process-local cache, not a distributed enforcement mechanism. Deployment still needs HTTPS, secrets management, least-privilege PostgreSQL accounts, broker network restrictions, encrypted storage and independent protected audit retention.
3. **Malware scanning:** the current scanner validates size, extension, signature and checksum; this is not an antivirus engine. A production malware scanner must be integrated and tested with fail-closed handling before accepting untrusted public uploads.
4. **External delivery/integration:** AICTE ERP, NSWS, SSO, payment and SMS adapters remain disabled. Official communication dispatch has no approved recipient/provider mapping. SMTP must be configured and verified; disabled delivery is now accurately reported as failure.
5. **Operational proof:** the tests exercise simulated failure contracts; they do not replace live worker-kill/broker-loss drills, load/p95 testing, multi-host delivery reconciliation or an independently witnessed database-plus-file restore. A separate real PostgreSQL/file restore drill now passed against synthetic demo data; see `demo-restore.json`. This does not establish production recovery targets.
6. **Remaining UX/API coverage:** appeal/reopening, closure, deadline operations, policy editing/migration and case audit/summary now have UI controls. Committee membership and assignment revocation have APIs but no dedicated administration forms. Template authoring and advanced audit drill-down remain basic. These paths need broader browser acceptance coverage; document/notification/administration lists remain bounded rather than fully paginated.
7. **Further correctness review:** all command input shapes need comprehensive serializers; assignment expiry semantics, cross-case evidence reuse, concurrent evidence-version numbering and safe idempotent retry UX deserve additional tests. Passing the current suite does not prove absence of these risks.

No real regulatory decisions, institution data imports, external messages or production restores were performed.
