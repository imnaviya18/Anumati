import { useCallback, useState } from "react";
import { apiRequest } from "../api/client";
import { usePolling } from "../hooks/usePolling";
export function CaseAssignmentPanel({ caseRecord = null }) {
  const [chosen, setChosen] = useState(""),
    [notice, setNotice] = useState(null),
    [busy, setBusy] = useState(false);
  const caseId = caseRecord?.id || chosen;
  const fetcher = useCallback(
    () => apiRequest(`/api/v1/access/assignment-options/?case_id=${caseId}`),
    [caseId],
  );
  const { data, error } = usePolling(fetcher);
  const current = data?.cases?.find((c) => c.id === caseId);
  async function submit(e) {
    e.preventDefault();
    const f = new FormData(e.currentTarget);
    setBusy(true);
    try {
      await apiRequest("/api/v1/access/case-assignments/", {
        method: "POST",
        body: JSON.stringify({
          case_id: caseId,
          stage_id: f.get("stage"),
          user_id: f.get("reviewer"),
          reason: f.get("reason"),
        }),
      });
      setNotice(
        "Reviewer assigned. The case is now available in their review queue.",
      );
    } catch (err) {
      setNotice(err.message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <details className="card">
      <summary>Assign case reviewer</summary>
      {error && <p role="alert">{error.message}</p>}
      {notice && <p role="status">{notice}</p>}
      <form onSubmit={submit}>
        {!caseRecord && (
          <>
            <label htmlFor="assign-case">Application</label>
            <select
              id="assign-case"
              value={caseId}
              onChange={(e) => setChosen(e.target.value)}
              required
            >
              <option value="">Select application</option>
              {data?.cases?.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.case_number} · {c.institution}
                </option>
              ))}
            </select>
          </>
        )}
        <label htmlFor="assign-stage">Active stage</label>
        <select id="assign-stage" name="stage" required>
          <option value="">Select stage</option>
          {current?.stages.map((s) => (
            <option key={s.id} value={s.id}>
              {s.stage_type} · {s.status}
            </option>
          ))}
        </select>
        <label htmlFor="assign-reviewer">Eligible reviewer</label>
        <select id="assign-reviewer" name="reviewer" required>
          <option value="">Select reviewer</option>
          {data?.reviewers?.map((u) => (
            <option key={u.id} value={u.id}>
              {u.username}
            </option>
          ))}
        </select>
        <label htmlFor="assign-reason">Assignment reason</label>
        <textarea id="assign-reason" name="reason" required />
        <button disabled={busy || !caseId}>Assign reviewer</button>
      </form>
    </details>
  );
}
