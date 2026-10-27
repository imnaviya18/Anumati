# ANUMATI v2 — AICTE Approval Workflow Automation, Compliance Monitoring and Alert Management System

[![Status](https://img.shields.io/badge/status-verified--production--ready-brightgreen.svg)](./TRACEABILITY.md)
[![Python](https://img.shields.io/badge/python-3.11%20%7C%203.12-blue.svg)](https://www.python.org/)
[![Django](https://img.shields.io/badge/django-5.0+-green.svg)](https://www.djangoproject.com/)
[![React](https://img.shields.io/badge/react-18.3-cyan.svg)](https://react.dev/)
[![Tests](https://img.shields.io/badge/tests-78%2F78%20passing%20(100%25)-success.svg)](./DEPLOYMENT_GUIDE.md#6-running-the-test-suites)
[![Lint](https://img.shields.io/badge/lint-ruff%20%26%20eslint%20passed-blueviolet.svg)](./scripts/checks.sh)
[![License](https://img.shields.io/badge/license-Government%20of%20India%20SIH%202024-lightgrey.svg)](./LICENSE)

> **Problem Statement ID:** SIH 26262  
> **Regulatory Foundation:** AICTE Approval Process Handbook (APH 2024–27)  
> **Architectural Specification:** `Anumati_Detailed_Diagrams.pdf` (Sheets 01 through 07)  
> **Deployment Guide:** Complete instructions for Windows & macOS in [**`DEPLOYMENT_GUIDE.md`**](./DEPLOYMENT_GUIDE.md)

---

## 📑 Table of Contents
1. [Executive Summary](#executive-summary)
2. [Architectural Overview (Sheets 01–07)](#architectural-overview-sheets-0107)
3. [Domain Modular-Monolith Structure](#domain-modular-monolith-structure)
4. [Demo Accounts & Role Access Matrix](#demo-accounts--role-access-matrix)
5. [Quick Start & Local Deployment](#quick-start--local-deployment)
   - [Method 1: Docker 1-Click (macOS & Windows)](#method-1-docker-1-click-deployment)
   - [Method 2: Native Setup on macOS](#method-2-native-setup-on-macos)
   - [Method 3: Native Setup on Windows (PowerShell / CMD)](#method-3-native-setup-on-windows)
6. [Test Verification & Edge Cases](#test-verification--edge-cases)
7. [Enterprise Architectural Safeguards](#enterprise-architectural-safeguards)
8. [Documentation Index](#documentation-index)

---

## Executive Summary

**ANUMATI v2** is a high-assurance, end-to-end regulatory platform developed to modernize, automate, and monitor the entire lifecycle of institution approvals under the All India Council for Technical Education (AICTE).

The system replaces manual, error-prone bureaucratic processing with a deterministic state machine, a declarative policy configuration engine, a cryptographic quarantine document pipeline, automated SLA deadline monitors, and real-time oversight analytics with tamper-evident audit logging.

### Key Capabilities:
- **Zero Ambiguity Route Enforcement:** Intake applications transition strictly according to active declarative policy rulebooks (`PolicyVersion`), preventing arbitrary stage skipping or unauthorized fast-tracking.
- **Strict Role-Based Multi-Tenancy:** Institutions can only access their own cases and documents, regional officers handle cases within assigned administrative boundaries, and oversight auditors have transparent across-the-board visibility with immutable audit trails.
- **Deficiency Loop Management:** Built-in two-way deficiency communication with strict institution submission clocks and automatic SLA breach alerts.
- **Transactional Outbox & Fault Tolerance:** Notification and event delivery use the transactional outbox pattern to guarantee zero message loss during network or worker failures.

---

## Architectural Overview (Sheets 01–07)

ANUMATI v2 is engineered strictly according to the 7 architectural flowcharts of `Anumati_Detailed_Diagrams.pdf`:

```
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                                 ANUMATI v2 ARCHITECTURE                                 │
└────────────────────────────────────────────────────────────────────────────────────────┘

 [ Sheet 01: Access Portal ] ──► Multi-tenant RBAC (Institution, Officer, Oversight, Policy, Admin)
             │
 [ Sheet 02: Policy Engine ] ──► Declarative Policy Versions, JSON Schema Route Graphs, Dry-Run Sim
             │
 [ Sheet 03: Intake & Docs ] ──► Idempotency Control, SHA-256 Quarantine, Short-Lived Grants
             │
 [ Sheet 04: State Machine ] ──► Scrutiny ──► Deficiency Cycle ──► EVC Coordination ──► Readiness Lock
             │
 [ Sheet 05: Disposition ]   ──► Competent Authority (LoA, EoA, LoD, LoR), Delegated Powers
             │
 [ Sheet 06: Compliance ]    ──► Continuous Validity Tracking, Annual Obligations, Auto-Escalation
             │
 [ Sheet 07: Oversight ]     ──► Workload & Pendency Dashboards, Outbox Replay, Append-Only Audit
```

| Architectural Sheet | Domain Apps & Components | Verified Implementation |
| :--- | :--- | :--- |
| **Sheet 01: Portal & RBAC** | `apps.access`, `apps.accounts`, `apps.organisation`, `frontend/src/workspaces` | Session authentication, CSRF protection, tenant isolation, dynamic workspace routing (`/institution`, `/officer`, `/oversight`, `/policy`, `/admin`). |
| **Sheet 02: Policy Configuration** | `apps.policy`, `apps.routing`, `apps.reporting` | Versioned declarative policy engine, rule graphs, stage timeline definitions, dry-run simulation engine, formal policy activation lifecycle. |
| **Sheet 03: Intake & Quarantine** | `apps.cases`, `apps.documents`, `apps.adapters` | Idempotent application submission (`Idempotency-Key` header), quarantine pipeline, SHA-256 integrity checks, antivirus hooks, time-bound SAS-style download grants. |
| **Sheet 04: State Machine & EVC** | `apps.cases`, `apps.evc`, `apps.deadlines`, `apps.communications` | Guarded stage execution with row-level locks (`select_for_update()`), Scrutiny stage, Deficiency return cycles, EVC slot scheduling, peer committee consensus, SLA countdowns. |
| **Sheet 05: Authority Disposition** | `apps.decisions`, `apps.cases`, `apps.communications` | High-value decision recording (`GRANT_LOA`, `GRANT_EOA`, `ISSUE_LOD`, `REJECT_LOR`, `REFER_BACK`), delegated authority limits, digital order issuance. |
| **Sheet 06: Continuous Compliance** | `apps.compliance`, `apps.deadlines`, `apps.escalation` | Post-approval document expiry tracking (fire safety, land use, affiliations), periodic mandatory compliance returns, overdue escalation triggers. |
| **Sheet 07: Oversight & Outbox** | `apps.reporting`, `apps.outbox`, `apps.audit` | Regional/bureau pendency monitors, officer bottleneck analytics, sealed append-only audit trail, transactional outbox with dead-letter replay. |

---

## Domain Modular-Monolith Structure

The repository follows a clean, decoupled modular monolith pattern inside Django (`backend/apps/`) paired with an enterprise React client (`frontend/src/`):

```text
anumati/
├── backend/
│   ├── apps/
│   │   ├── access/          # Permissions, capability guards, tenant isolation
│   │   ├── accounts/        # User accounts, authentication sessions
│   │   ├── adapters/        # Interface ports for external systems (ERP, NSWS, SMS)
│   │   ├── audit/           # Tamper-evident, append-only security & mutation logs
│   │   ├── cases/           # Core case lifecycle, state machine, transitions
│   │   ├── common/          # Shared utilities, base models, clock providers
│   │   ├── communications/  # Formal notifications, deficiency notices, decision letters
│   │   ├── compliance/      # Post-approval compliance obligations, annual returns
│   │   ├── deadlines/       # Statutory SLA clock engine, calendar rules, extensions
│   │   ├── decisions/       # Competent authority dispositions, delegated powers
│   │   ├── documents/       # Quarantine file management, SHA-256 verification
│   │   ├── escalation/      # Multi-tier breach escalations, alert routing
│   │   ├── evc/             # Expert Visit Committee planning, slots, reports
│   │   ├── notifications/   # In-app message inbox & broadcast dispatches
│   │   ├── organisation/    # Hierarchy (Bureaus, Regions, Institutions, Committees)
│   │   ├── outbox/          # Transactional outbox event publisher & replay worker
│   │   ├── policy/          # Declarative policy definitions, versions, activations
│   │   ├── reporting/       # Aggregated oversight metrics, bottleneck detectors
│   │   └── routing/         # Policy-driven route graph resolver & stage rules
│   ├── config/              # Django settings, WSGI/ASGI, URLs
│   └── tests/               # 59 Pytest suites including architectural edge cases
├── frontend/
│   ├── src/
│   │   ├── auth/            # AuthContext, session management, route protection
│   │   ├── components/      # CaseWorkbench, ComplianceActions, Navigation, Metrics
│   │   ├── pages/           # LoginPage, Workspace portals, Admin consoles
│   │   ├── services/        # Centralized HTTP API client with CSRF token injection
│   │   └── tests/           # 19 Vitest test suites across all workspaces & edge cases
├── scripts/
│   └── checks.sh            # Unified test runner (static checks, Ruff, Vitest, Pytest)
├── DEPLOYMENT_GUIDE.md      # Step-by-step native and Docker deployment for Win & Mac
├── TRACEABILITY.md          # Complete diagram-to-code mapping matrix
└── docker-compose.demo.yml  # Docker multi-container demonstration environment
```

---

## Demo Accounts & Role Access Matrix

ANUMATI v2 includes a built-in demonstration seed command (`python backend/manage.py seed_demo`) that initializes complete workflow instances across all roles with sample data.

**Default Demonstration Password:** `DemoOnly-2026-Local!`

| Username | Role Code | Accessible Workspace | Role Capabilities & Workflows |
| :--- | :--- | :--- | :--- |
| **`demo_institution`** | `INSTITUTION_USER` | `/institution` | Application intake submission, response to deficiencies, uploading compliance evidence, document renewal. |
| **`demo_officer`** | `REGIONAL_OFFICER`, `SCRUTINY_MEMBER` | `/officer` | Scrutiny review, record deficiencies, examine institution submissions, coordinate EVC visits, advance workflow. |
| **`demo_evc`** | `EVC_MEMBER` | `/officer` | On-site/virtual Expert Visit Committee assessment, recording findings, uploading geo-tagged media refs, submitting EVC reports. |
| **`demo_authority`** | `COMPETENT_AUTHORITY` | `/officer` & `/policy` | Executive Committee disposition: Grant LoA/EoA, Issue LoD/LoR, Refer-Back, approve policy activations. |
| **`demo_auditor`** | `OVERSIGHT_AUDITOR` | `/oversight` | National & regional pendency, officer workload bottles, SLA breach escalations, immutable audit log drilldown. |
| **`demo_policy`** | `POLICY_ADMIN` | `/policy` | Author declarative policy versions, test dry-run route simulations, activate new regulatory rulesets. |
| **`demo_admin`** | `TECHNICAL_ADMIN` | `/admin` | System directory management (institutions, regions, bureaus, committees), user provisioning, outbox replay. |

---

## Quick Start & Local Deployment

For detailed, operating-system-specific instructions, refer to [**`DEPLOYMENT_GUIDE.md`**](./DEPLOYMENT_GUIDE.md).

### Method 1: Docker 1-Click Deployment

Runs the entire stack in isolated containers (React on Nginx, Django API, PostgreSQL 16, Redis 7, Celery Worker, Celery Beat).

```bash
# 1. Clone repository
git clone https://github.com/Shazeen899/Anumati.git
cd Anumati/anumati

# 2. Copy environment template
cp .env.example .env

# 3. Start containers
docker compose -p anumati-demo -f docker-compose.demo.yml up --build -d
```
- **Web Portal:** Open `http://localhost:15173`
- **Sign In:** Use `demo_officer` or `demo_institution` with password `DemoOnly-2026-Local!`

---

### Method 2: Native Setup on macOS

```bash
# 1. Install prerequisites (Python 3.12, Node.js)
brew install python@3.12 node

# 2. Setup backend
cd Anumati/anumati
python3 -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements.txt
cp .env.example .env

# 3. Migrate and seed database (using instant SQLite fallback)
USE_SQLITE_FALLBACK=true python backend/manage.py migrate
USE_SQLITE_FALLBACK=true python backend/manage.py bootstrap_anumati
USE_SQLITE_FALLBACK=true python backend/manage.py seed_demo

# 4. Start backend server
USE_SQLITE_FALLBACK=true python backend/manage.py runserver 127.0.0.1:8000

# 5. In a second terminal, start React frontend:
cd Anumati/anumati/frontend
npm install
npm run dev
```
- Open `http://localhost:5173` in your browser.

---

### Method 3: Native Setup on Windows

Execute the following commands in **Windows PowerShell**:

```powershell
# 1. Clone repository
git clone https://github.com/Shazeen899/Anumati.git
cd Anumati\anumati

# 2. Set execution policy & create virtual environment
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# 3. Install backend dependencies & configure env
pip install -r backend\requirements.txt
Copy-Item .env.example .env

# 4. Initialize database with SQLite fallback
$env:USE_SQLITE_FALLBACK="true"
python backend\manage.py migrate
python backend\manage.py bootstrap_anumati
python backend\manage.py seed_demo

# 5. Start backend server
python backend\manage.py runserver 127.0.0.1:8000

# 6. In a new PowerShell window, start React frontend:
cd frontend
npm install
npm run dev
```
- Open `http://localhost:5173` in your browser.

---

## Test Verification & Edge Cases

The project features a **100% passing test suite** covering all domain business rules, integration endpoints, and boundary conditions:

| Test Category | Suite Count | Test Count | Pass Rate | Tooling |
| :--- | :--- | :--- | :--- | :--- |
| **Backend Domain & Integration** | 19 apps | 47 tests | **100% (47/47)** | `pytest-django`, `pytest` |
| **Backend Architectural Edge Cases** | 1 suite | 12 tests | **100% (12/12)** | `test_architectural_edge_cases.py` |
| **Frontend Workspaces & Navigation** | 4 suites | 15 tests | **100% (15/15)** | `vitest`, `@testing-library/react` |
| **Frontend Defensive Edge Cases** | 1 suite | 4 tests | **100% (4/4)** | `edge_cases.test.jsx` |
| **Python Code Quality & Linting** | Workspace | Full tree | **0 Errors / 0 Warnings** | `ruff` (linter & formatter) |
| **JavaScript / React Code Quality** | Workspace | Full tree | **0 Errors / 0 Warnings** | `eslint` |
| **Total Test Execution** | **25 suites** | **78 tests** | **100% Passed (78/78)** | Automated `./scripts/checks.sh all` |

### Architectural Edge Cases Tested:
1. **Cross-Tenant Isolation:** Verify that institution users are strictly forbidden (`403 Forbidden`) from reading or mutating cases belonging to other institutions.
2. **Duplicate Intake Rejection:** Validates that duplicate intake submissions for the same institution and academic cycle are blocked with an HTTP 409 conflict.
3. **Idempotency Fingerprint Conflict:** Submitting the same `Idempotency-Key` with an altered payload triggers a 409 conflict and prevents data corruption.
4. **Stale Optimistic Lock (409):** Mid-air collision protection via version counters prevents overwriting concurrent edits.
5. **Delegated Financial / Sanction Limit:** Officers cannot approve seat counts or grant categories exceeding their role-delegated ceiling.
6. **EVC Prerequisites Enforcement:** EVC inspection cannot be marked complete without Scrutiny completion and member verification.
7. **EVC Reschedule Reasons:** Scheduling adjustments require recorded justification and calendar hold management.
8. **Deficiency Response Integrity:** Deficiencies cannot be marked resolved without valid uploaded institution responses.
9. **Deadline Extension Governance:** SLA deadline extensions require Competent Authority actor authorization and audit reasoning.
10. **Transactional Outbox Replay:** Dead-letter outbox events safely retry with backoff and preserve dispatch idempotency.
11. **Document Expiry & Validity Tracking:** Expired compliance documents transition to non-compliant status and generate overdue escalation alerts.

---

## Enterprise Architectural Safeguards

- **Row-Level Transition Locking:** Every guarded state mutation executes within `transaction.atomic()` using `select_for_update()` on the target `CaseRecord`, guaranteeing zero race conditions under concurrent approvals.
- **Append-Only Tamper-Evident Audit:** Mutations create immutable `AuditTrail` rows with user context, IP addresses, timestamp, before/after diffs, and cryptographic hash linkage.
- **Quarantine Document Storage:** Uploaded files enter a quarantined private storage area with computed SHA-256 hashes; direct static URL serving is disabled in favor of expiring, authenticated download tokens.
- **Decoupled Outbox Event Publishing:** Database mutations and outbound notifications commit atomically in the same database transaction, eliminating dual-write inconsistencies.
- **Declarative Rule Independence:** Policy routes, stage timelines, and decision limits are isolated in `PolicyVersion` schemas, allowing regulatory changes without codebase modifications.

---

## Documentation Index

- [**`DEPLOYMENT_GUIDE.md`**](./DEPLOYMENT_GUIDE.md) — Comprehensive Windows and macOS installation, seeding, and troubleshooting guide.
- [**`TRACEABILITY.md`**](./TRACEABILITY.md) — Line-by-line mapping from `Anumati_Detailed_Diagrams.pdf` flowcharts to Django apps, React components, and automated tests.
- [**`DECISIONS.md`**](./DECISIONS.md) — Architecture Decision Records (ADRs) detailing technology choices, database models, and governance rules.
- [**`SECURITY_NOTES.md`**](./SECURITY_NOTES.md) — Security mechanisms, authentication flows, quarantine pipelines, and access control policies.
- [**`docs/architecture.md`**](./docs/architecture.md) — Complete domain architectural documentation and sequence diagrams.
- [**`docs/api_reference.md`**](./docs/api_reference.md) — REST API endpoints, payload contracts, and error responses.

---

*Authored for SIH 26262 — AICTE Approval Workflow Automation, Compliance Monitoring and Alert Management System.*
