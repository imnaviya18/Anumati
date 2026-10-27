import { useCallback, useRef, useState } from "react";
import { apiRequest } from "../api/client";
import { usePolling } from "../hooks/usePolling";
export function EvcWorkspace({ caseRecord = null }) {
  const fetchEvc = useCallback(async () => {
    const records = await apiRequest("/api/v1/evc/");
    return caseRecord
      ? records.filter((c) => c.case_id === caseRecord.id)
      : records;
  }, [caseRecord]);
  const fetchDirectory = useCallback(
    () => apiRequest("/api/v1/organisation/"),
    [],
  );
  const { data: directory } = usePolling(fetchDirectory);
  const pendingCommand = useRef(null);
  const { data, error, refresh } = usePolling(fetchEvc);
  const [selected, setSelected] = useState("");
  const [action, setAction] = useState("reserve");
  const [message, setMessage] = useState(null);
  const [busy, setBusy] = useState(false);
  async function submit(e) {
    e.preventDefault();
    const f = new FormData(e.currentTarget);
    setBusy(true);
    try {
      const payload = { reason: f.get("reason") };
      if (action === "ready") {
        payload.case_id = caseRecord?.id || f.get("case");
        payload.stage_instance_id =
          caseRecord?.stage_instances.find(
            (s) =>
              s.stage_type === "EVC" &&
              ["PENDING", "IN_PROGRESS"].includes(s.status),
          )?.id || f.get("stage");
      }
      if (action === "reserve") {
        payload.committee_id = f.get("committee");
        payload.slot_start = new Date(f.get("start")).toISOString();
        payload.slot_end = new Date(f.get("end")).toISOString();
      }
      if (action === "confirm") payload.confirmed = true;
      if (action === "report") {
        payload.expected_version = data.find(
          (c) => c.id === selected,
        )?.case_version;
        payload.observations = { findings: f.get("observations") };
        payload.video_recording_ref = f.get("video");
        payload.gps_coordinates = f.get("gps");
        payload.evidence_version_ids = JSON.parse(f.get("evidence") || "[]");
      }
      if (action === "report") {
        const signature = JSON.stringify({ selected, payload });
        if (pendingCommand.current?.signature !== signature)
          pendingCommand.current = { signature, key: crypto.randomUUID() };
        payload.idempotency_key = pendingCommand.current.key;
      }
      const result = await apiRequest(
        action === "ready"
          ? "/api/v1/evc/"
          : `/api/v1/evc/${selected}/${action}/`,
        { method: "POST", body: JSON.stringify(payload) },
      );
      refresh();
      setMessage(`EVC action saved: ${result.status || "report recorded"}`);
    } catch (err) {
      setMessage(err.message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <section className="card">
      <h2>EVC scheduling & reports</h2>
      {error && <p role="alert">{error.message}</p>}
      {message && <p role="status">{message}</p>}
      {data?.map((c) => (
        <details key={c.id}>
          <summary>
            {c.case_number} · {c.status}
          </summary>
          <p>{c.blocker_reason || "No recorded blocker"}</p>
          <p>
            {c.scheduled_start
              ? new Date(c.scheduled_start).toLocaleString()
              : "Not scheduled"}
          </p>
          <p>{c.report_summary || "Report pending"}</p>
          <pre>{JSON.stringify(c.observations, null, 2)}</pre>
        </details>
      ))}
      <form onSubmit={submit}>
        <label htmlFor="evc-action">EVC action</label>
        <select
          id="evc-action"
          value={action}
          onChange={(e) => setAction(e.target.value)}
        >
          <option value="ready">Verify readiness</option>
          <option value="reserve">Reserve committee slot</option>
          <option value="confirm">Confirm schedule</option>
          <option value="reschedule">Request rescheduling</option>
          <option value="report">Submit evaluation report</option>
        </select>
        {action === "ready" ? (
          caseRecord ? (
            <p>
              Readiness for {caseRecord.case_number} ·{" "}
              {caseRecord.current_stage_type}
            </p>
          ) : (
            <>
              <label htmlFor="evc-case">Case ID</label>
              <input id="evc-case" name="case" required />
              <label htmlFor="evc-stage">Stage ID</label>
              <input id="evc-stage" name="stage" required />
            </>
          )
        ) : (
          <>
            <label htmlFor="evc-record">EVC record</label>
            <select
              id="evc-record"
              value={selected}
              onChange={(e) => setSelected(e.target.value)}
              required
            >
              <option value="">Select EVC record</option>
              {data?.map((c) => (
                <option value={c.id} key={c.id}>
                  {c.case_number} · {c.status}
                </option>
              ))}
            </select>
          </>
        )}
        {action === "reserve" && (
          <>
            <label htmlFor="evc-committee">Committee</label>
            <select id="evc-committee" name="committee" required>
              <option value="">Select committee</option>
              {directory?.committees
                ?.filter((c) => c.committee_type === "EVC")
                .map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.name}
                  </option>
                ))}
            </select>
            <label htmlFor="evc-start">Start (your local time)</label>
            <input id="evc-start" name="start" type="datetime-local" required />
            <label htmlFor="evc-end">End (your local time)</label>
            <input id="evc-end" name="end" type="datetime-local" required />
          </>
        )}
        {action === "report" && (
          <>
            <label htmlFor="evc-observations">Observations</label>
            <textarea id="evc-observations" name="observations" required />
            <label htmlFor="evc-video">Video recording reference</label>
            <input id="evc-video" name="video" required />
            <label htmlFor="evc-gps">GPS coordinates (physical visits)</label>
            <input id="evc-gps" name="gps" />
            <label htmlFor="evc-evidence">
              Evidence version IDs (JSON array)
            </label>
            <textarea id="evc-evidence" name="evidence" defaultValue="[]" />
          </>
        )}
        <label htmlFor="evc-reason">Reason / report summary</label>
        <textarea id="evc-reason" name="reason" required />
        <button disabled={busy}>Save EVC action</button>
      </form>
    </section>
  );
}
