import { useCallback, useState } from "react";
import { apiRequest } from "../api/client";
import { usePolling } from "../hooks/usePolling";
export function ComplianceActions({ institution = false, caseRecord = null }) {
  const fetchCompliance = useCallback(async () => {
    const [validity, obligations, documents] = await Promise.all([
      apiRequest("/api/v1/compliance/validity/"),
      apiRequest("/api/v1/compliance/obligations/"),
      apiRequest(
        `/api/v1/documents/${caseRecord ? `?case_id=${caseRecord.id}` : ""}`,
      ),
    ]);
    const valList = Array.isArray(validity)
      ? validity
      : validity?.results || [];
    const obligList = Array.isArray(obligations)
      ? obligations
      : obligations?.results || [];
    const docList = Array.isArray(documents)
      ? documents
      : documents?.results || [];
    return {
      documents: docList,
      validity: caseRecord
        ? valList.filter(
            (v) => v.institution_code === caseRecord.institution_code,
          )
        : valList,
      obligations: caseRecord
        ? obligList.filter((o) => o.case_number === caseRecord.case_number)
        : obligList,
    };
  }, [caseRecord]);
  const { data, error, refresh } = usePolling(fetchCompliance);
  const [kind, setKind] = useState("renewal");
  const [message, setMessage] = useState(null);
  const [busy, setBusy] = useState(false);
  async function submit(e) {
    e.preventDefault();
    const f = new FormData(e.currentTarget);
    setBusy(true);
    try {
      let path, payload;
      if (kind === "register") {
        path = "/api/v1/compliance/validity/";
        payload = {
          document_version_id: f.get("document"),
          valid_from: f.get("from"),
          valid_until: f.get("until"),
        };
      } else if (kind === "renewal") {
        path = `/api/v1/compliance/validity/${f.get("record")}/${institution ? "submit" : "review"}/`;
        payload = institution
          ? { document_version_id: f.get("document") }
          : {
              accept: f.get("outcome") === "accept",
              valid_from: f.get("from"),
              valid_until: f.get("until"),
              notes: f.get("notes"),
            };
      } else {
        const [obligation, submission] = f.get("submission").split(":");
        path = `/api/v1/compliance/obligations/${obligation}/verify/`;
        payload = {
          submission_id: submission,
          is_fulfilled: f.get("outcome") === "accept",
          finding_notes: f.get("notes"),
        };
      }
      const result = await apiRequest(path, {
        method: "POST",
        body: JSON.stringify(payload),
      });
      refresh();
      setMessage(`Saved: ${result.state || "pending review"}`);
    } catch (err) {
      setMessage(err.message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <section className="card">
      <h2>{institution ? "Submit a renewal" : "Compliance verification"}</h2>
      {error && <p role="alert">{error.message}</p>}
      {message && <p role="status">{message}</p>}
      {!institution && (
        <>
          <label htmlFor="compliance-kind">Review type</label>
          <select
            id="compliance-kind"
            value={kind}
            onChange={(e) => setKind(e.target.value)}
          >
            <option value="renewal">Document renewal</option>
            <option value="register">
              Register accepted document validity
            </option>
            <option value="obligation">Obligation evidence</option>
          </select>
        </>
      )}
      <form onSubmit={submit}>
        {kind === "register" ? (
          <>
            <label htmlFor="register-document">Clean document</label>
            <select id="register-document" name="document" required>
              <option value="">Select document</option>
              {data?.documents
                .filter((d) => d.lifecycle_state === "CLEAN")
                .map((d) => (
                  <option key={d.id} value={d.id}>
                    {d.original_filename} · {d.document_type}
                  </option>
                ))}
            </select>
            <label htmlFor="register-from">Validity begins</label>
            <input id="register-from" name="from" type="date" required />
            <label htmlFor="register-until">Validity ends</label>
            <input id="register-until" name="until" type="date" required />
          </>
        ) : kind === "renewal" ? (
          <>
            <label htmlFor="renewal-record">Validity record</label>
            <select id="renewal-record" name="record" required>
              <option value="">Select record</option>
              {data?.validity.map((v) => (
                <option key={v.id} value={v.id}>
                  {v.document_type} · {v.institution_code} · {v.state}
                </option>
              ))}
            </select>
            {institution ? (
              <>
                <label htmlFor="renewal-document">New document version</label>
                <select id="renewal-document" name="document" required>
                  <option value="">Select uploaded document</option>
                  {data?.documents.map((d) => (
                    <option key={d.id} value={d.id}>
                      {d.original_filename} · v{d.version_number}
                    </option>
                  ))}
                </select>
              </>
            ) : (
              <>
                <label htmlFor="valid-from">New validity begins</label>
                <input type="date" id="valid-from" name="from" />
                <label htmlFor="valid-until">New validity ends</label>
                <input type="date" id="valid-until" name="until" />
              </>
            )}
          </>
        ) : (
          <>
            <label htmlFor="verification-submission">Evidence submission</label>
            <select id="verification-submission" name="submission" required>
              <option value="">Select pending submission</option>
              {data?.obligations.flatMap((o) =>
                (o.submissions || [])
                  .filter((s) => !s.reviewed_at)
                  .map((s) => (
                    <option key={s.id} value={`${o.id}:${s.id}`}>
                      {o.obligation_code} · {s.document_version_id}
                    </option>
                  )),
              )}
            </select>
          </>
        )}
        {!institution && (
          <>
            <label htmlFor="compliance-outcome">Outcome</label>
            <select id="compliance-outcome" name="outcome">
              <option value="accept">Accept / fulfilled</option>
              <option value="reject">Request clarification</option>
            </select>
            <label htmlFor="compliance-notes">Finding</label>
            <textarea id="compliance-notes" name="notes" required />
          </>
        )}
        <button disabled={busy}>Save compliance action</button>
      </form>
    </section>
  );
}
