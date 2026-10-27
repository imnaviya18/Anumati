import { SyncExceptions } from "../../components/SyncExceptions";
import { useAuth } from "../../auth/AuthContext";

import { PolicyTools } from "../../components/PolicyTools";
import { apiRequest } from "../../api/client";
import { usePolling } from "../../hooks/usePolling";

import { useState } from "react";
const fetchPolicies = () => apiRequest("/api/v1/policy/");

/**
 * Policy Administration Workspace (Sheet 01 Block 05, Sheet 04 J1-J3, Sheet 07 P3-P4)
 * - Draft -> Validate -> Dry-Run -> Approve -> Activate lifecycle
 * - Versioned communication templates & escalation hierarchies
 * - Explicit authorised policy migration for open cases
 */
export function PolicyWorkspacePage() {
  const { user } = useAuth();

  const [approvalReason, setApprovalReason] = useState("");
  const { data: policies, error, refresh } = usePolling(fetchPolicies);
  const [demoRules, setDemoRules] = useState(false);
  const [effectiveFrom, setEffectiveFrom] = useState("");
  const [effectiveUntil, setEffectiveUntil] = useState("");
  const [rules, setRules] = useState("[]");
  const [version, setVersion] = useState(1);
  const [regression, setRegression] = useState("[]");
  const [busy, setBusy] = useState(false);
  const [policyCode, setPolicyCode] = useState("APH-2026");
  const [academicCycle, setAcademicCycle] = useState("2026-27");
  const [lifecycleNotice, setLifecycleNotice] = useState(null);

  async function handleDraftSubmit(e) {
    e.preventDefault();
    setBusy(true);
    try {
      const saved = await apiRequest("/api/v1/policy/", {
        method: "POST",
        body: JSON.stringify({
          policy_code: policyCode,
          is_demonstration: demoRules,
          ...(effectiveFrom
            ? { effective_from: new Date(effectiveFrom).toISOString() }
            : {}),
          ...(effectiveUntil
            ? { effective_until: new Date(effectiveUntil).toISOString() }
            : {}),
          academic_cycle: academicCycle,
          version_number: Number(version),
          route_rules: JSON.parse(rules),
          regression_cases: JSON.parse(regression),
        }),
      });
      refresh();
      setLifecycleNotice(
        `Saved draft ${saved.policy_code} version ${saved.version_number}.`,
      );
    } catch (err) {
      setLifecycleNotice(err.message);
    } finally {
      setBusy(false);
    }
  }
  async function action(id, name) {
    setBusy(true);
    try {
      const saved = await apiRequest(`/api/v1/policy/${id}/${name}/`, {
        method: "POST",
        body: JSON.stringify({ reason: approvalReason }),
      });
      setLifecycleNotice(`Policy state: ${saved.state}`);
      refresh();
    } catch (err) {
      setLifecycleNotice(err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <section aria-labelledby="policy-heading">
      <h1 id="policy-heading">Policy Administration Workspace</h1>
      <p>
        Policy Governance Lifecycle: Draft &rarr; Validate &rarr; Dry-Run &rarr;
        Approve &rarr; Activate, Effective-Dated Templates, and Explicit Case
        Migration.
      </p>

      <div className="workspace-grid">
        <div className="card">
          <h2>Draft New Policy Version</h2>
          <form onSubmit={handleDraftSubmit}>
            <label className="checkbox-row">
              <input
                type="checkbox"
                checked={demoRules}
                onChange={(e) => setDemoRules(e.target.checked)}
              />
              Demonstration rules only (never authoritative)
            </label>
            <label htmlFor="policy-from">Effective from (local time)</label>
            <input
              id="policy-from"
              type="datetime-local"
              value={effectiveFrom}
              onChange={(e) => setEffectiveFrom(e.target.value)}
            />
            <label htmlFor="policy-until">Effective until (local time)</label>
            <input
              id="policy-until"
              type="datetime-local"
              value={effectiveUntil}
              onChange={(e) => setEffectiveUntil(e.target.value)}
            />
            <label htmlFor="policy-code-input">Policy Code</label>
            <input
              id="policy-code-input"
              type="text"
              value={policyCode}
              onChange={(e) => setPolicyCode(e.target.value)}
            />
            <label htmlFor="policy-cycle-input">Academic Cycle</label>
            <input
              id="policy-cycle-input"
              type="text"
              value={academicCycle}
              onChange={(e) => setAcademicCycle(e.target.value)}
            />
            <label htmlFor="policy-version">Version number</label>
            <input
              id="policy-version"
              type="number"
              min="1"
              required
              value={version}
              onChange={(e) => setVersion(e.target.value)}
            />
            <label htmlFor="routes-json">Route rules (JSON array)</label>
            <textarea
              id="routes-json"
              value={rules}
              onChange={(e) => setRules(e.target.value)}
            />
            <label htmlFor="regression-json">
              Regression cases (JSON array)
            </label>
            <textarea
              id="regression-json"
              value={regression}
              onChange={(e) => setRegression(e.target.value)}
            />
            <button type="submit" disabled={busy}>
              Create Draft Policy
            </button>
          </form>
          {lifecycleNotice && <p role="status">{lifecycleNotice}</p>}
        </div>

        <div className="card">
          <h2>Policy Safeguards</h2>
          <ul>
            <li>
              Declarative route, timeline, calendar, and escalation data only
              (no arbitrary code).
            </li>
            <li>
              Existing open cases keep their pinned policy version upon
              activation of a new version.
            </li>
            <li>
              Case migration requires explicit scope, recorded reason,
              authorisation, and audit.
            </li>
          </ul>
        </div>
      </div>
      {error && <p role="alert">{error.message}</p>}
      <h2>Policy versions</h2>
      <label htmlFor="approval-reason">
        Approval reason (competent authority)
      </label>
      <textarea
        id="approval-reason"
        value={approvalReason}
        onChange={(e) => setApprovalReason(e.target.value)}
      />
      {policies?.map((p) => (
        <article className="card" key={p.id}>
          <h3>
            {p.policy_code} · v{p.version_number}
          </h3>
          <p>{p.state}</p>
          {["validate", "dry-run", "approve", "activate"].map((a) => (
            <button
              key={a}
              disabled={
                busy ||
                (a === "validate" &&
                  !["DRAFT", "VALIDATED"].includes(p.state)) ||
                (a === "dry-run" &&
                  !["VALIDATED", "DRY_RUN_PASSED"].includes(p.state)) ||
                (a === "approve" &&
                  (!user?.roles?.includes("COMPETENT_AUTHORITY") ||
                    p.state !== "DRY_RUN_PASSED")) ||
                (a === "activate" && p.state !== "APPROVED")
              }
              onClick={() => action(p.id, a)}
            >
              {a}
            </button>
          ))}
          <p>
            {p.is_demonstration
              ? "DEMONSTRATION RULES"
              : "Research draft: authoritative activation blocked until approved"}
          </p>
          {p.approval_reason && <p>Approval: {p.approval_reason}</p>}
          <pre>{JSON.stringify(p.validation_report, null, 2)}</pre>
          <pre>{JSON.stringify(p.dry_run_report, null, 2)}</pre>
        </article>
      ))}
      <PolicyTools />
      <SyncExceptions />
    </section>
  );
}
