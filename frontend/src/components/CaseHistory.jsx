import { useState } from "react";
import { apiRequest } from "../api/client";
export function CaseHistory({ caseId }) {
  const [history, setHistory] = useState(null);
  const [summary, setSummary] = useState(null);
  const [error, setError] = useState(null);
  return (
    <details>
      <summary>Audit history & case summary</summary>
      <button
        onClick={async () => {
          try {
            setHistory(
              await apiRequest(`/api/v1/audit/events/?case_id=${caseId}`),
            );
          } catch (err) {
            setError(err.message);
          }
        }}
      >
        Load audit history
      </button>
      <button
        onClick={async () => {
          try {
            setSummary(
              await apiRequest(
                `/api/v1/communications/cases/${caseId}/summary/`,
                { method: "POST", body: "{}" },
              ),
            );
          } catch (err) {
            setError(err.message);
          }
        }}
      >
        Generate case summary
      </button>
      {error && <p role="alert">{error}</p>}
      {summary && (
        <article>
          <h3>{summary.rendered_subject}</h3>
          <pre>{summary.rendered_body}</pre>
        </article>
      )}
      {history?.map((h) => (
        <article key={h.id}>
          <p>
            <strong>{h.action}</strong> ·{" "}
            {new Date(h.occurred_at).toLocaleString()} · {h.actor_role}
          </p>
          <p>{h.reason}</p>
        </article>
      ))}
    </details>
  );
}
