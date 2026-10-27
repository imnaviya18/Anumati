import { useSearchParams } from "react-router-dom";
import { Notifications } from "../../components/Notifications";
import { useAuth } from "../../auth/AuthContext";
import { CaseWorkbench } from "../../components/CaseWorkbench";
import { useCallback, useState } from "react";
import { apiFetch } from "../../api/client";
import { usePolling } from "../../hooks/usePolling";

/**
 * Institution Workspace (Sheet 01, Sheet 02 A1/B2, Sheet 03 E1/F2, PS Sections A, D, E)
 * - Application intake & status tracking
 * - Deficiency response submission
 * - Undertaking evidence & document validity renewal upload to quarantine
 * - In-app notifications
 */
const fetchDirectory = () => apiFetch("/api/v1/organisation/");
export function InstitutionWorkspacePage() {
  const { user } = useAuth();
  const [, setParams] = useSearchParams();
  const { data: directory } = usePolling(fetchDirectory);
  const [busy, setBusy] = useState(false);
  const [institutionId, setInstitutionId] = useState(
    user?.scope?.institution_ids?.[0] || "",
  );
  const [sourceId, setSourceId] = useState("");
  const [academicCycle, setAcademicCycle] = useState("2026-27");
  const [applicationCategory, setApplicationCategory] = useState("EOA");
  const [submitStatus, setSubmitStatus] = useState(null);

  const fetchDashboard = useCallback(async () => {
    return apiFetch("/api/v1/reporting/dashboard/");
  }, []);

  const { data, dataAsOf, loading, error } = usePolling(fetchDashboard, 30000);

  async function handleIntakeSubmit(e) {
    e.preventDefault();
    if (!sourceId.trim()) {
      setSubmitStatus("Source Application ID is required.");
      return;
    }
    setBusy(true);
    try {
      const result = await apiFetch("/api/v1/cases/", {
        method: "POST",
        body: JSON.stringify({
          institution_id: institutionId,
          source_id: sourceId,
          academic_cycle: academicCycle,
          application_category: applicationCategory,
        }),
      });
      setSubmitStatus(`Saved ${result.case_number}: ${result.status}`);
      setSourceId("");
      setParams({ case: result.id });
    } catch (err) {
      setSubmitStatus(`Unable to submit: ${err.message}`);
    } finally {
      setBusy(false);
    }
  }

  return (
    <section aria-labelledby="inst-heading">
      <h1 id="inst-heading">Institution Workspace</h1>
      <p>
        Submit applications, respond to observations, upload evidence and renew
        supporting documents.
      </p>

      <div className="polling-banner" aria-live="polite">
        <strong>Data as of:</strong> {dataAsOf || "Loading..."}
      </div>

      {loading && (
        <p role="status">Loading institution cases and compliance status...</p>
      )}
      {error && (
        <p role="alert">Error loading workspace data: {error.message}</p>
      )}

      {!loading && data && (
        <div className="workspace-grid">
          <div className="card">
            <h2>Pendency &amp; Timeline Alerts</h2>
            <p>Total Scoped Cases: {data.total_visible_cases ?? 0}</p>
            <p>
              Approaching Deadlines (72h):{" "}
              {data.timeline_alerts?.approaching_72h_count ?? 0}
            </p>
            <p>Overdue Deadlines: {data.timeline_alerts?.overdue_count ?? 0}</p>
            {data.total_visible_cases === 0 && (
              <p className="empty-state">
                No active applications in current scope.
              </p>
            )}
          </div>

          <div className="card">
            <h2>Submit an application</h2>
            <form onSubmit={handleIntakeSubmit}>
              <label htmlFor="institution-id">Institution</label>
              <select
                id="institution-id"
                value={institutionId}
                onChange={(e) => setInstitutionId(e.target.value)}
                required
              >
                <option value="">Select institution</option>
                {(user?.scope?.institution_ids || []).map((id) => (
                  <option key={id} value={id}>
                    {directory?.institutions?.find((i) => i.id === id)?.name ||
                      id}
                  </option>
                ))}
              </select>
              <label htmlFor="source-id-input">Source Application ID</label>
              <input
                id="source-id-input"
                type="text"
                value={sourceId}
                onChange={(e) => setSourceId(e.target.value)}
                placeholder="e.g. AICTE-2026-001"
              />
              <label htmlFor="cycle-input">Academic Cycle</label>
              <input
                id="cycle-input"
                type="text"
                value={academicCycle}
                onChange={(e) => setAcademicCycle(e.target.value)}
              />
              <label htmlFor="category-select">Application Category</label>
              <select
                id="category-select"
                value={applicationCategory}
                onChange={(e) => setApplicationCategory(e.target.value)}
              >
                <option value="EOA">Extension of Approval (EoA)</option>
                <option value="NEW_INSTITUTION">New Institution (LoA)</option>
              </select>
              <button type="submit" disabled={busy}>
                {busy ? "Submitting…" : "Submit Intake"}
              </button>
            </form>
            {submitStatus && <p role="status">{submitStatus}</p>}
          </div>
        </div>
      )}
      <CaseWorkbench institution />
      <Notifications />
    </section>
  );
}
