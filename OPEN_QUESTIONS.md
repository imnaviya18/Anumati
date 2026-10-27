# OPEN QUESTIONS & COMPETENT AUTHORITY DECISIONS — ANUMATI v2 (SIH 26262)

Per the strict scope and source-of-truth rules, nothing outside `Anumati_Detailed_Diagrams.pdf` (Sheets 01–07) and Problem Statement 26262 / AICTE Approval Process Handbook (APH 2024-27) is assumed or hardcoded. Items below record:
1. **Decisions required from you (Engineering Lead / Product Owner)** before or during subsequent stages.
2. **Source conflicts** identified and resolved per the instructions.
3. **Regulatory parameters** implemented strictly as policy-driven, effective-dated configuration data (via the `policy` governance workflow) awaiting formal validation by the AICTE Competent Authority.

## 1. Decisions Required from You Before Stage 1 Proceeds

### OQ-1: Role Matrix & Delegated Regulatory Powers (Administration & Stage 1 Scope)
**Context from Sources:**
- **Problem Statement & Diagrams (Sheet 01, 02, 04, 07 P5):** Name the following workspace groups and actors:
  1. `INSTITUTION_USER` (Institution / Applicant / Promoter representative — submits applications, deficiency responses, undertaking evidence, document renewals; scoped strictly to their assigned `Institution`).
  2. `SCRUTINY_MEMBER` / `RE_SCRUTINY_MEMBER` (Scrutiny / Re-Scrutiny Committee member — evaluates assigned scrutiny stages and records evidence-linked findings; APH 1.8, 2.23.1, Annexure-16.3/16.4).
  3. `EVC_MEMBER` / `EVC_CHAIR` (Expert Visit Committee member / chairman — confirms readiness/slot, conducts online/physical visit, submits EVC observations and report; APH 1.9, Annexure-16.5; Sheet 04 G1–G5).
  4. `REGIONAL_OFFICER` (Regional Officer / Regional Office (RO) / Regional Committee (RC) — constitutes EVC per APH Def 29, monitors regional pendency/workload, reviews assigned regional stages/compliance/renewals, owns regional escalations; scoped to assigned `Region`).
  5. `BUREAU_OFFICER` (Regulation Bureau / Approval Bureau / Policy & Academic Planning Bureau / PGRC officer — schedules Scrutiny/SHC/SAC per APH 1.8(b), 2.24(d), places consolidated lists/observations before EC/SHC/SAC, verifies compliance/documents, owns bureau-level escalations; scoped to assigned `Bureau` / regions).
  6. `SHC_MEMBER` / `SAC_MEMBER` / `SCSC_MEMBER` (Standing Hearing Committee / Standing Appellate Committee / Standing Complaint Scrutiny Committee member/chairman — records hearing/appeal/complaint recommendations; APH Def 53–55, 1.11, 2.23.3, 2.24, 7.10, Annexure-16.6/16.7).
  7. `COMPETENT_AUTHORITY` (Executive Committee (EC) / Council / Chairman / Vice-Chairman / Member Secretary — exercises delegated authority in panel C1–C2 to record authoritative decisions: LoA, EoA, LoD, LoR, Speaking Order, refer-back, punitive/restoration decisions, and deadline extensions/holds; APH 1.10, 1.11(e), 2.25, 7.3, Annexure-16.1/16.2; Sheet 02 C1–C2, Sheet 03 D4).
  8. `OVERSIGHT_AUDITOR` (Oversight / Audit user — read-only drill-down across pendency, workload, escalations, case history, and the six statutory reports; Sheet 01, Sheet 04 J6).
  9. `POLICY_ADMIN` (Policy Governance administrator — drafts, validates, dry-runs, and activates effective-dated policy versions and authorised migrations; Sheet 01, Sheet 04 J1–J3).
  10. `TECHNICAL_ADMIN` / `OPS_ADMIN` (System / Operations administrator — manages users, role assignments, organisation master records, operational health metrics, and audited outbox replay, but **never holds regulatory authority** to evaluate stages, accept evidence, extend deadlines, or record case decisions; Sheet 07 P5).

**Question / Confirmation Needed:**
- Do you approve this 10-role canonical role matrix and separation of duties for Stage 1 implementation, or do you want any specific role names merged, split, or renamed?

### OQ-2: Malware / Content Scanner in Quarantine Pipeline (Stage 3 Scope)
**Context from Sources:**
- **Diagrams (Sheet 01 Block 11, Sheet 03 E1, Sheet 05 Private File Storage, Sheet 07 P2):** Specify `Received -> quarantine -> scanning -> clean / rejected` where scan outage leaves the file quarantined and human compliance acceptance is a separate business review.
- **Prompt Rule:** Explicitly states: *"Malware scanning (for example a local ClamAV daemon) would be an addition to this stack: do not add it. Implement the quarantine pipeline with type, size and signature checks plus mandatory human acceptance, and list the scanner as a decision for me in OPEN_QUESTIONS.md."*

**Question / Confirmation Needed:**
- Shall we keep the external malware scanner strictly as a disabled pluggable interface hook (defaulting to the built-in deterministic magic-byte signature, MIME-type, extension, and size validator + simulated scan-outage toggle for fault testing Q2/Q3), with no third-party daemon added to `docker-compose.yml`?

### OQ-3: SMTP Email Delivery Configuration (Stage 3 & 6 Scope)
**Context from Sources:**
- **Prompt Rule:** *"Email: send only through Django's standard SMTP backend pointed at an organisation-owned mail server via environment variables; disabled by default. When disabled, notifications are in-app only. No SMS."*

**Question / Confirmation Needed:**
- We have configured `EMAIL_DELIVERY_ENABLED=false` by default in `.env.example` and Django settings so all notifications persist in-app and outbox delivery records completion locally unless `EMAIL_DELIVERY_ENABLED=true` is explicitly set with an internal SMTP host. Please confirm if any specific SMTP headers or envelope formats are required when enabled.

## 2. Recorded Source Conflicts & Resolutions

### SC-1: Technology Stack Resolution
- **Observation:** Sheet 01 and Sheet 07 footer note that the original problem statement/notes had stack ambiguity, and explicitly state: *"Stack conflict resolved in favour of React JS / Django / PostgreSQL + Celery / Redis."*
- **Resolution:** Followed `Anumati_Detailed_Diagrams.pdf` and prompt rules strictly: React JS + Django + DRF + PostgreSQL + Celery + Celery Beat + Redis.

### SC-2: Optional OCR / AI Assistance Mentioned in Diagrams vs. Prompt Prohibition
- **Observation:** Sheet 01 (Block 09: *"Optional OCR is reviewed assistance*"*), Sheet 03 (F2: *"OCR suggestions require confirmation*"*), and Sheet 05 (*"AI assistance optional, outside authoritative decisions"*) mention optional OCR/AI with an asterisk (`* Proposed enhancements`). However, the prompt strictly mandates: *"No LLM/AI/OCR... Electronic case summaries: generated from structured case data through fixed, versioned templates (no AI)"*.
- **Resolution:** Zero AI/ML/OCR code or libraries are included anywhere in the system. Document validity dates and metadata are entered as structured fields and verified by authorised human reviewers; case summaries are rendered deterministically from versioned templates.

### SC-3: External Portals (NSWS, Payment Gateway, YouTube Video Links, External Portals)
- **Observation:** APH 2024-27 references external portals such as National Single Window System (NSWS, Clause 1.3.1/1.4.1), AICTE online payment gateway (Clause 1.4.2), YouTube video links for EVC (Annexure-1 Clause 1.2(ix)), and MoE IIC/ABC portals (Clause 6.51/6.53). The prompt mandates: *"NO EXTERNAL APIs — Fully self-contained; runs with `docker compose up`; nothing may need network access at runtime. AICTE systems, identity/SSO and any other external system from the diagrams are built as DISABLED interface ports only."*
- **Resolution:** Application intake accepts `source_id` / payment receipt metadata as structured fields or authorised import commands (Sheet 02 A1), video/evidence references are handled as local metadata/private versioned files, and all external integrations (`aicte_erp`, `nsws_intake`, `sso_identity`, `payment_gateway`, `sms_gateway`) are implemented strictly as disabled interface ports in `backend/apps/adapters/` returning clear `"not_configured"` status.

## 3. Regulatory Rules Implemented Strictly as Policy-Driven Data (Not Hardcoded)

In accordance with Sheet 01 (Block 05), Sheet 02 (A2), Sheet 04 (J1–J3), Sheet 07 (P3–P4), and the DATA RULES:
1. **Approval Route Combinations:** APH Table 2.3 (e.g., Self-Disclosure only, Scrutiny only, Scrutiny + EVC, Scrutiny + EVC + SHC/SAC, Only EVC) are evaluated from effective-dated `PolicyVersion` JSON rules, never hardcoded `if/else` chains.
2. **Academic Calendar & Cut-off Deadlines:** Public Notice cut-off dates (APH 1.2, 2.2, 4.3), appeal windows (e.g., 7 days from LoD/decision per APH 1.11(a), 2.24(a)), Security Deposit submission windows (15 days per APH 2.25(f)), and EVC scheduling/completion SLA thresholds (including distinct rules for New Institutions under Chapter I vs Existing Institutions under Chapter II) are stored in policy-governed calendars and timeline rules.
3. **Undertaking & Document Validity Rules:** Minimum lease durations (30 years total / live lease >= max course duration per APH 2.1(e), 6.17(a)), Structural Stability Certificate renewal intervals (5 years after 30 years from completion per APH 6.17(h)), Fire Safety Certificate validity, and advance reminder offsets are configured via policy data.
4. **Multi-Level Escalation Hierarchies:** Escalation thresholds, target roles/officials, and reminder cadences are configured via policy data.
