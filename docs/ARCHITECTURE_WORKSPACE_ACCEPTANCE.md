# Original architecture: workspace acceptance

Updated 27 October 2026. Re-read all seven pages directly from the original architecture PDF, including the operational diagram on sheet 04. The PDF is a specification/reference, not authority to activate regulatory rules or deploy externally.

## Four workspace feature matrix

| Original feature | Implementation | Verification |
| --- | --- | --- |
| Institution applications | Scoped, searchable, paginated intake and case detail | HTTP intake and scope tests; browser sign-in |
| Deficiency responses | Recorded deficiencies, institution response with evidence and expected version, new re-review stage, preserved response history | Real HTTP return → response → re-scrutiny journey |
| Evidence uploads | Private versioned upload, asynchronous Celery scan, human review, short-lived downloads | Actual worker scan; quarantine/access tests |
| Renewal status | Accepted validity registration, pending renewal, human acceptance/clarification, prior accepted version retained until review | Real HTTP registration → renewal → verification |
| Officer / committee assigned cases | Scope-filtered queues with stage assignments and server-enforced action authority | Scope/isolation tests and actual officer journey |
| Scrutiny findings | Persisted findings, exact document references, stage history, guarded stage completion | HTTP scrutiny/re-scrutiny; wrong-case evidence regression |
| EVC reports | Readiness, reservation, human confirmation, rescheduling, observations/evidence/report, saved report display | Actual committee report plus identical retry; scheduling domain tests |
| Authorised decisions | Delegated-power check, expected version, stable retry key, reviewed evidence, refer-back destination and decision-linked obligations | Final EOA/LoA HTTP journeys; concurrency/idempotency suite |
| Regional / bureau pendency | Region and bureau filters, separate total/pending counts | Filter/isolation test; browser table inspection |
| Workload | Officer and committee workload, pending-age bands, stage bottlenecks, unassigned-stage count | Dashboard API assertions and browser inspection |
| Escalations | Scoped owned escalation register with reasons/state/resolution; authorised deadline actions | Existing deadline tests; register and operation UI |
| Case history | Read-only oversight drill-down, findings, deficiencies/responses, audit history, generated summary and authorised evidence access | HTTP case history/summary; browser route verification |
| Draft rules | Versioned configuration, provenance, effective dates, calendars, routes, requirements and permissions | Policy HTTP creation/edit/validation tests |
| Approval of changes | Separate APPROVED state, competent-authority permission, recorded approval reason/time/user, immutable approved version | Negative and positive API tests |
| Version activation | Requires explicit approval, retains pinned case versions, controlled migration; production activation gate retained | HTTP draft → validate → dry-run → approve → activate using isolated synthetic cycle |
| Sync exceptions | Persisted paginated queue, owner, source/event identity, immutable snapshots, duplicate detection, version conflict checks, reassign/keep-local/accept-source, audited resolution | API permission/deduplication/stale-resolution tests; real HTTP reconciliation |

## Sync source boundary

The adapter is explicitly LOCAL_MOCK. It accepts only reference fields (`display_name`, `reference`, `notes`) and is enabled only in development when demonstration policies are allowed. Reconciliation modifies a separate reference mirror. It cannot overwrite an application, decision or active policy. Original/incoming values and ownership changes remain in the audit trail. Live source authentication and field ownership contracts require the approved integration owner; this is not represented as a working live AICTE integration.

## Verification evidence

Final automated verification: **47 PostgreSQL tests and 15 React tests passed**, plus the actual four-workspace HTTP journey and database/file restore drill.

- `test-reports/current-postgres.txt`: current full PostgreSQL regression run.
- `test-reports/current-frontend.txt`: current React tests.
- `test-reports/workspaces-http-smoke.json`: actual four-workspace HTTP acceptance using PostgreSQL, Redis, Celery worker and Beat.
- `test-reports/demo-http-smoke.json`: prior actual decision replay, obligation and download acceptance.
- `test-reports/demo-restore.json`: actual `pg_dump` / `pg_restore` into a separate disposable database, private-file archive extraction, checksum and audit-link verification. The original demo database was not replaced.
- `test-reports/demo-stack-build.txt`: final Docker build/start.
- Workspace screenshots are under `test-reports/`.

Commands and accounts are in `LOCAL_DEMO.md`. Every new smoke run creates additional synthetic records; policy lifecycle tests use a distinct synthetic academic cycle to avoid changing the running 2026–27 demonstration route.

## Limits of the original architecture claim

The listed four-workspace workflows are implemented locally. This does not certify the full production architecture. Privileged MFA/approved SSO, production antivirus, external provider authentication/delivery, independent protected retention, multi-host failure drills, production load targets, RPO/RTO and owner-approved hosting/TLS remain production work. Some administration inputs still use record IDs and structured JSON; comprehensive usability testing is not claimed. Optional OCR is not implemented. The researched APH configuration remains a non-authoritative DRAFT with addendum/amendment/calendar/internal-procedure validation pending.

No test suite proves absence of bugs. Do not describe this local demonstration as a fully approved AICTE production system.
