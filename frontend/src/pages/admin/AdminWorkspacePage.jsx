import { AdministrationDirectory } from "../../components/AdministrationDirectory";
import { apiRequest } from "../../api/client";
import { usePolling } from "../../hooks/usePolling";
const fetchFailed = () => apiRequest("/api/v1/outbox/failed/");
import { useState } from "react";

/**
 * Administration & Operations Workspace (Sheet 01 Block 01, Sheet 04 J5, Sheet 05, Sheet 06 M3, Sheet 07 P5, Q4)
 * - Local management of Users, Roles, Regions, Bureaus, Committees, Institutions, and Validity-Bounded Assignments
 * - Operations telemetry: Outbox backlog, failed-job owner queue, audited replay, stale leases, due lag
 * - Strict separation: Technical Admin holds zero regulatory approval authority (Sheet 07 P5)
 */
export function AdminWorkspacePage() {
  const { data: failed, error } = usePolling(fetchFailed);
  const [eventId, setEventId] = useState("");
  const [busy, setBusy] = useState(false);
  const [replayReason, setReplayReason] = useState("");
  const [opsMessage, setOpsMessage] = useState(null);

  async function handleReplaySubmit(e) {
    e.preventDefault();
    if (!replayReason.trim()) {
      setOpsMessage(
        "Operator replay requires an explicit audit reason (Sheet 06 M3).",
      );
      return;
    }
    setBusy(true);
    try {
      const result = await apiRequest(
        `/api/v1/outbox/failed/${eventId}/replay/`,
        { method: "POST", body: JSON.stringify({ reason: replayReason }) },
      );
      setOpsMessage(`Replay saved: ${result.state}`);
    } catch (err) {
      setOpsMessage(err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <section aria-labelledby="admin-heading">
      <h1 id="admin-heading">Administration &amp; Operations Workspace</h1>
      <p>
        Users, Roles, Regions, Bureaus, Committees, Institutions,
        Validity-Bounded Assignments, and Outbox / Failed-Job Operations
        (Technical Admin Holds No Regulatory Authority — Sheet 04 J5, Sheet 05,
        Sheet 07 P5, Q4).
      </p>

      <div className="workspace-grid">
        <div className="card">
          <h2>Regulatory Authority Separation (Sheet 07 P5)</h2>
          <p>
            Technical administrators manage directory entities, validity-bounded
            role assignments, and outbox operations, and are strictly blocked
            from executing scrutiny stages, EVC confirmations, or Competent
            Authority decisions.
          </p>
        </div>

        <div className="card">
          <h2>Outbox Failed-Job Audited Replay (Sheet 06 M3)</h2>
          {error && <p role="alert">{error.message}</p>}
          <form onSubmit={handleReplaySubmit}>
            <label htmlFor="failed-event">Failed event</label>
            <select
              id="failed-event"
              value={eventId}
              onChange={(e) => setEventId(e.target.value)}
              required
            >
              <option value="">Select a failed event</option>
              {failed?.map((ev) => (
                <option key={ev.id} value={ev.id}>
                  {ev.event_type} · {ev.last_error}
                </option>
              ))}
            </select>
            <label htmlFor="replay-reason-input">
              Mandatory Replay Audit Reason
            </label>
            <input
              id="replay-reason-input"
              type="text"
              value={replayReason}
              onChange={(e) => setReplayReason(e.target.value)}
              placeholder="e.g. SMTP relay restored after maintenance"
            />
            <button type="submit" disabled={busy}>
              Replay Failed Outbox Job
            </button>
          </form>
          {opsMessage && <p role="status">{opsMessage}</p>}
        </div>
      </div>
      <AdministrationDirectory />
    </section>
  );
}
