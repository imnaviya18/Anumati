import { useState } from "react";
import { apiRequest } from "../api/client";
import { usePolling } from "../hooks/usePolling";
const fetchOperations = () => apiRequest("/api/v1/deadlines/");
export function OperationalActions() {
  const { data, error, refresh } = usePolling(fetchOperations);
  const [action, setAction] = useState("extend");
  const [notice, setNotice] = useState(null);
  const [busy, setBusy] = useState(false);
  async function submit(e) {
    e.preventDefault();
    const form = new FormData(e.currentTarget);
    setBusy(true);
    try {
      await apiRequest(`/api/v1/deadlines/${form.get("record")}/${action}/`, {
        method: "POST",
        body: JSON.stringify({
          reason: form.get("reason"),
          due_at:
            action !== "close-escalation"
              ? new Date(form.get("due")).toISOString()
              : undefined,
        }),
      });
      refresh();
      setNotice("Action recorded with audit history.");
    } catch (err) {
      setNotice(err.message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <details className="card">
      <summary>Deadlines & escalation actions</summary>
      {error && <p role="alert">{error.message}</p>}
      {notice && <p role="status">{notice}</p>}
      <form onSubmit={submit}>
        <label htmlFor="deadline-action">Action</label>
        <select
          id="deadline-action"
          value={action}
          onChange={(e) => setAction(e.target.value)}
        >
          <option value="extend">Extend deadline</option>
          <option value="hold">Place deadline on hold</option>
          <option value="close-escalation">Resolve escalation</option>
        </select>
        <label htmlFor="deadline-record">Record</label>
        <select name="record" id="deadline-record" required>
          <option value="">Select record</option>
          {(action === "close-escalation"
            ? data?.escalations
            : data?.deadlines
          )?.map((r) => (
            <option key={r.id} value={r.id}>
              {r.source_type || r.reason} · {r.state}{" "}
              {r.due_at ? `· ${new Date(r.due_at).toLocaleString()}` : ""}
            </option>
          ))}
        </select>
        {action !== "close-escalation" && (
          <>
            <label htmlFor="deadline-due">Revised due date (local time)</label>
            <input
              id="deadline-due"
              name="due"
              type="datetime-local"
              required
            />
          </>
        )}
        <label htmlFor="deadline-reason">Authorised reason</label>
        <textarea id="deadline-reason" name="reason" required />
        <button disabled={busy}>Record action</button>
      </form>
    </details>
  );
}
export function CaseLifecycleActions({
  caseRecord,
  institution = false,
  onRefresh,
}) {
  const [message, setMessage] = useState(null);
  const [busy, setBusy] = useState(false);
  async function submit(e) {
    e.preventDefault();
    const f = new FormData(e.currentTarget);
    setBusy(true);
    try {
      const result = await apiRequest(
        `/api/v1/cases/${caseRecord.id}/lifecycle/${f.get("action")}/`,
        {
          method: "POST",
          body: JSON.stringify({
            expected_version: caseRecord.version,
            reason: f.get("reason"),
          }),
        },
      );
      setMessage(`Saved ${result.case_number}: ${result.status}`);
      onRefresh?.(caseRecord.id);
    } catch (err) {
      setMessage(err.message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <details>
      <summary>Closure or appeal</summary>
      <form onSubmit={submit}>
        <label htmlFor="lifecycle-action">Action</label>
        <select name="action" id="lifecycle-action">
          <option value="appeal">Open linked appeal</option>
          {!institution && (
            <option value="close">Close processing instance</option>
          )}
        </select>
        <label htmlFor="lifecycle-reason">Reason</label>
        <textarea id="lifecycle-reason" name="reason" required />
        <button disabled={busy}>Submit lifecycle action</button>
      </form>
      {message && <p role="status">{message}</p>}
    </details>
  );
}
