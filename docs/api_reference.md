# API Reference — ANUMATI v2 (Sheets 01, 05, 06)

## 1. Request Boundary Contracts
- **Base Path:** `/api/v1/`
- **Authentication:** Django session cookie (`sessionid`) + `X-CSRFToken` header on all mutating requests (`POST`, `PUT`, `PATCH`, `DELETE`).
- **Correlation:** Every request accepts or generates `X-Correlation-ID` and echoes it in the response headers and audit/outbox records.
- **Guarded Decision Commands (Sheet 06 K1–K6):**
  - Header `Idempotency-Key`: Required on state-mutating workflow and decision endpoints.
  - Payload field `expected_version`: Required integer matching `Case.version`; returns `HTTP 409 Conflict` when stale.

## 2. Stage 0 Health & System Boundary Endpoints
- `GET /api/v1/health/` — Liveness and readiness check verifying Django, PostgreSQL connection, and adapter port configuration status (`data_as_of` UTC timestamp included).
- `GET /api/v1/adapters/status/` — Lists external adapter ports and confirms their disabled (`not_configured`) state.
