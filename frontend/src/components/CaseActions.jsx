import { useCallback, useRef, useState } from "react";
import { apiRequest } from "../api/client";
import { usePolling } from "../hooks/usePolling";
export function CaseActions({ caseRecord, onSaved }) {
  const actions = caseRecord.available_actions || [];
  const [choice, setChoice] = useState(""),
    [notice, setNotice] = useState(null),
    [busy, setBusy] = useState(false);
  const identity = useRef(null);
  const selected = actions.find((a) => a.code === choice) || actions[0];
  const fetchDocs = useCallback(
    () => apiRequest(`/api/v1/documents/?case_id=${caseRecord.id}`),
    [caseRecord.id],
  );
  const { data: documents, error } = usePolling(fetchDocs);
  async function submit(e) {
    e.preventDefault();
    const f = new FormData(e.currentTarget);
    const action = selected.code;
    const reason = f.get("reason");
    const evidence = f.getAll("evidence");
    let path,
      payload = { expected_version: caseRecord.version, reason };
    setBusy(true);
    setNotice(null);
    try {
      if (action === "RESPOND") {
        path = `/api/v1/cases/${caseRecord.id}/deficiencies/${f.get("cycle")}/respond/`;
        payload = {
          ...payload,
          response_text: reason,
          evidence_version_ids: evidence,
        };
      } else if (action === "RESOLVE_ROUTE")
        path = `/api/v1/cases/${caseRecord.id}/resolve-route/`;
      else if (action.startsWith("DECIDE_")) {
        path = `/api/v1/decisions/cases/${caseRecord.id}/decide/`;
        payload = {
          ...payload,
          outcome: action.slice(7),
          reasons: reason,
          delegated_power_ref: selected.delegated_power_ref,
          reviewed_evidence_version_ids: evidence,
          refer_back_stage_type: f.get("destination") || "",
          obligations_specs: f.get("obligation_code")
            ? [
                {
                  obligation_code: f.get("obligation_code"),
                  condition_text: f.get("condition"),
                  due_days: Number(f.get("due_days")),
                },
              ]
            : [],
        };
      } else {
        path = `/api/v1/cases/${caseRecord.id}/stages/${selected.stage_id}/transition/`;
        const finding = f.get("finding");
        payload = {
          ...payload,
          action,
          findings: evidence.length
            ? evidence.map((id) => ({ document_version_id: id, finding }))
            : [{ finding }],
        };
      }
      const signature = JSON.stringify({ path, payload });
      if (identity.current?.signature !== signature)
        identity.current = { signature, key: crypto.randomUUID() };
      payload.idempotency_key = identity.current.key;
      await apiRequest(path, { method: "POST", body: JSON.stringify(payload) });
      setNotice(
        "Saved. The case, queue and related panels have been refreshed.",
      );
      onSaved?.();
    } catch (err) {
      setNotice(
        err.status === 409
          ? "This case has changed. Review the refreshed case before retrying."
          : err.message,
      );
      onSaved?.();
    } finally {
      setBusy(false);
    }
  }
  return (
    <section>
      <h3>Next action</h3>
      {error && <p role="alert">{error.message}</p>}
      {notice && <p role="status">{notice}</p>}
      {!selected ? (
        <p>
          No review command is available for your role at this stage. Check the
          case status, assignments or EVC workflow.
        </p>
      ) : (
        <form onSubmit={submit}>
          <label htmlFor="case-action">Available action</label>
          <select
            id="case-action"
            value={selected.code}
            onChange={(e) => setChoice(e.target.value)}
          >
            {actions.map((a) => (
              <option value={a.code} key={a.code}>
                {a.label}
              </option>
            ))}
          </select>
          {selected.code === "RESPOND" && (
            <>
              <label htmlFor="response-cycle">Clarification request</label>
              <select id="response-cycle" name="cycle" required>
                {caseRecord.deficiency_cycles?.map((c, i) => (
                  <option key={c.id} value={c.id}>
                    Request {i + 1}
                  </option>
                ))}
              </select>
            </>
          )}
          {["COMPLETE_STAGE", "RETURN_FOR_DEFICIENCY"].includes(
            selected.code,
          ) && (
            <>
              <label htmlFor="review-finding">
                Finding or requested clarification
              </label>
              <textarea id="review-finding" name="finding" required />
            </>
          )}
          {selected.code !== "RESOLVE_ROUTE" && (
            <fieldset>
              <legend>Supporting evidence</legend>
              {documents
                ?.filter(
                  (d) =>
                    d.lifecycle_state === "CLEAN" &&
                    (!selected.code.startsWith("DECIDE_") ||
                      d.acceptance_status === "ACCEPTED"),
                )
                .map((d) => (
                  <label className="checkbox-row" key={d.id}>
                    <input type="checkbox" name="evidence" value={d.id} />
                    {d.original_filename} · version {d.version_number} ·{" "}
                    {d.acceptance_status}
                  </label>
                ))}
              {documents?.length === 0 && (
                <p>Upload evidence in the case evidence panel below.</p>
              )}
            </fieldset>
          )}
          {selected.code === "DECIDE_REFER_BACK" && (
            <>
              <label htmlFor="refer-destination">Return to stage</label>
              <select id="refer-destination" name="destination" required>
                {caseRecord.prescribed_stages?.map((s) => (
                  <option key={s}>{s}</option>
                ))}
              </select>
            </>
          )}
          {selected.code.startsWith("DECIDE_") &&
            selected.code !== "DECIDE_REFER_BACK" && (
              <details>
                <summary>Add a continuing obligation (optional)</summary>
                <label htmlFor="ob-code">Obligation code</label>
                <input id="ob-code" name="obligation_code" />
                <label htmlFor="ob-condition">Condition</label>
                <textarea id="ob-condition" name="condition" />
                <label htmlFor="ob-days">
                  Due in calendar days (demo rule)
                </label>
                <input
                  type="number"
                  id="ob-days"
                  name="due_days"
                  min="1"
                  defaultValue="30"
                />
              </details>
            )}
          <label htmlFor="case-reason">Recorded reason / response</label>
          <textarea id="case-reason" name="reason" required />
          <button disabled={busy}>
            {busy ? "Saving…" : "Save case action"}
          </button>
        </form>
      )}
    </section>
  );
}
