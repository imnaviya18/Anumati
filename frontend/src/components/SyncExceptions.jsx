import { useCallback, useState } from "react";
import { apiRequest } from "../api/client";
import { usePolling } from "../hooks/usePolling";
export function SyncExceptions() {
  const [page, setPage] = useState(1),
    [state, setState] = useState("OPEN");
  const [notice, setNotice] = useState(null),
    [busy, setBusy] = useState(false);
  const fetcher = useCallback(
    () =>
      apiRequest(`/api/v1/policy/sync-exceptions/?page=${page}&state=${state}`),
    [page, state],
  );
  const { data, error, refresh } = usePolling(fetcher);
  async function submit(e, item) {
    e.preventDefault();
    const f = new FormData(e.currentTarget);
    setBusy(true);
    setNotice(null);
    try {
      const body = item
        ? {
            action: f.get("action"),
            expected_version: item.version,
            reason: f.get("reason"),
            ...(f.get("owner") ? { owner_id: Number(f.get("owner")) } : {}),
          }
        : {
            event_id: f.get("event"),
            source_id: f.get("source"),
            reason: f.get("reason"),
            payload: JSON.parse(f.get("payload")),
          };
      await apiRequest(
        item
          ? `/api/v1/policy/sync-exceptions/${item.id}/resolve/`
          : "/api/v1/policy/sync-exceptions/",
        { method: "POST", body: JSON.stringify(body) },
      );
      setNotice(
        item
          ? "Reconciliation recorded with audit history."
          : "Mock event saved to the owned review queue.",
      );
      refresh();
    } catch (err) {
      setNotice(err.message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <section>
      <h2>Sync exceptions & source reconciliation</h2>
      <p>
        Local mock reference data only. Accepting source data updates the
        reference mirror; it cannot change cases, decisions or active policy.
        Live AICTE adapters remain disabled.
      </p>
      {error && <p role="alert">{error.message}</p>}
      {notice && <p role="status">{notice}</p>}
      <details className="card">
        <summary>Submit a demonstration source event</summary>
        <form onSubmit={(e) => submit(e)}>
          <label htmlFor="sync-source">Source record ID</label>
          <input id="sync-source" name="source" required maxLength="128" />
          <label htmlFor="sync-event">Unique source event ID</label>
          <input id="sync-event" name="event" required maxLength="128" />
          <label htmlFor="sync-payload">Source fields (JSON)</label>
          <textarea
            id="sync-payload"
            name="payload"
            defaultValue={
              '{"display_name":"Synthetic reference","reference":"DEMO","notes":"Local only"}'
            }
            required
          />
          <label htmlFor="sync-reason">Review reason</label>
          <textarea id="sync-reason" name="reason" required />
          <button disabled={busy}>Queue mock event for review</button>
        </form>
      </details>
      <label htmlFor="sync-state">Exception state</label>
      <select
        id="sync-state"
        value={state}
        onChange={(e) => {
          setState(e.target.value);
          setPage(1);
        }}
      >
        <option>OPEN</option>
        <option>RESOLVED</option>
      </select>
      {data?.results.map((item) => (
        <article className="card" key={item.id}>
          <h3>
            {item.source_id} · {item.event_id}
          </h3>
          <p>
            {item.state} · Owner: {item.owner} · Revision {item.version}
          </p>
          <p>{item.reason}</p>
          <div className="workspace-grid">
            <div>
              <h4>Previous local values</h4>
              <pre>{JSON.stringify(item.local_snapshot, null, 2)}</pre>
            </div>
            <div>
              <h4>Incoming source values</h4>
              <pre>{JSON.stringify(item.incoming_snapshot, null, 2)}</pre>
            </div>
          </div>
          {item.state === "OPEN" &&
            item.current_source_version !== item.baseline_version && (
              <p role="alert">
                Source record changed since this event. Keep local and submit a
                fresh event to review current values.
              </p>
            )}
          {item.state === "OPEN" ? (
            <form onSubmit={(e) => submit(e, item)}>
              <label htmlFor={`action-${item.id}`}>Resolution</label>
              <select id={`action-${item.id}`} name="action">
                <option value="KEEP_LOCAL">Keep local values</option>
                <option value="ACCEPT_SOURCE">
                  Accept source into reference mirror
                </option>
                <option value="REASSIGN">Reassign review owner</option>
              </select>
              <label htmlFor={`owner-${item.id}`}>
                New policy governor user ID (reassignment only)
              </label>
              <input
                id={`owner-${item.id}`}
                name="owner"
                type="number"
                min="1"
              />
              <label htmlFor={`reason-${item.id}`}>Recorded reason</label>
              <textarea id={`reason-${item.id}`} name="reason" required />
              <button disabled={busy}>Record reconciliation</button>
            </form>
          ) : (
            <p>
              {item.resolution}: {item.resolution_reason}
            </p>
          )}
        </article>
      ))}
      {data?.count === 0 && <p>No {state.toLowerCase()} sync exceptions.</p>}
      <button disabled={!data?.previous} onClick={() => setPage((p) => p - 1)}>
        Previous exceptions
      </button>
      <span> Page {page} </span>
      <button disabled={!data?.next} onClick={() => setPage((p) => p + 1)}>
        Next exceptions
      </button>
    </section>
  );
}
