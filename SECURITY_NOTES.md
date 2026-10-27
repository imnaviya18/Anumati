# SECURITY NOTES — ANUMATI v2 (SIH 26262)

This document tracks the security controls required by `Anumati_Detailed_Diagrams.pdf` (Sheets 01, 05, 06, 07 P1–P5, N5) and Problem Statement 26262, together with their implementation locations and proving tests.

## 1. Access Control & Scoped Authorisation (Sheet 01 Block 01, Sheet 07 P1, Q2)
- **Deny-by-default permission enforcement:** Every read, write, list, search, export, download, and background job checks the actor's active role, institution scope, region scope, bureau scope, committee/case assignment scope, and validity period (`backend/apps/access/`).
- **Separation of Technical and Regulatory Authority (Sheet 07 P5):** Technical administrators (`TECHNICAL_ADMIN`) manage system operations and user/organisation records but are explicitly blocked at the service and API layers from executing regulatory transitions, recording scrutiny/EVC findings, accepting compliance evidence, extending deadlines, or issuing approval decisions.
- **Session & CSRF Security (Sheet 05, Sheet 07 P1):** Same-origin HTTP-only session cookies, strict CSRF protection on all mutating `/api/` endpoints, request size limits, and login rate limiting.

## 2. Append-Only Audit Mechanism (Sheet 01 Block 09, Sheet 07 N5)
- **Database-Level Append-Only Protection:**
  1. Audit records are written to the `audit` schema/tables where the application runtime database role holds `INSERT` and `SELECT` privileges only (`REVOKE UPDATE, DELETE, TRUNCATE`).
  2. A PostgreSQL before-update/delete trigger (`prevent_audit_mutation`) raises a hard exception if any update or delete is attempted even by a superuser/migration connection during normal runtime.
- **Periodic Sealed Exports:**
  1. Sealed audit batches are exported with SHA-256 hash chains and manifest signatures to a separate archive directory outside the application's mutable media storage.
- **Proving Tests:** `backend/apps/audit/tests/test_append_only.py` (Stage 2 & Stage 7) verifies that `UPDATE` and `DELETE` statements against audit rows fail at the database level.

## 3. Private File Storage & Quarantine Lifecycle (Sheet 01 Block 11, Sheet 03 E1, Sheet 05, Sheet 07 P2)
- **Upload Quarantine Pipeline:**
  1. Uploaded files are stored outside web-accessible static roots with immutable version UUIDs and SHA-256 checksums in `QUARANTINED` state.
  2. Asynchronous validation checks file size bounds, allowed extensions, MIME types, and magic-byte file signatures.
  3. Files that fail validation transition to `REJECTED`; scanner/worker outages leave files in `QUARANTINED`.
  4. Unaccepted, quarantined, or rejected files cannot be downloaded by reviewers or used to satisfy obligations (`Sheet 07 Q2`).
  5. Human compliance acceptance (`E3`/`E4`) is strictly separate from scan cleanliness (`E1`/`E2`).

## 4. Secret Management, Log Redaction & Dependency Pinning (Sheet 05, Sheet 07 P5)
- All secrets (`DJANGO_SECRET_KEY`, database credentials, bootstrap admin password) are loaded exclusively from environment variables (`.env.example` provided).
- Structured JSON/key-value logging attaches `X-Correlation-ID` across API -> service -> outbox -> Celery worker attempts while redacting passwords, session tokens, CSRF tokens, and authorization headers (`backend/apps/common/logging.py`).
- All Python (`backend/requirements.txt`) and Node (`frontend/package.json`) dependencies are pinned to exact versions.
