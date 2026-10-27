import { useCallback, useState } from "react";
import { apiRequest } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import { usePolling } from "../hooks/usePolling";
const readFile = (file) =>
  new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result.split(",")[1]);
    reader.onerror = () => reject(new Error("Unable to read file"));
    reader.readAsDataURL(file);
  });
export function EvidenceWorkspace({
  institution = false,
  readOnly = false,
  caseRecord = null,
}) {
  const { user } = useAuth();
  const [notice, setNotice] = useState(null);
  const [busy, setBusy] = useState(false);
  const [revision, setRevision] = useState(0);
  const fetcher = useCallback(async () => {
    const [documents, obligations, validity, directory] = await Promise.all([
      apiRequest(
        `/api/v1/documents/${caseRecord ? `?case_id=${caseRecord.id}` : ""}`,
      ),
      apiRequest("/api/v1/compliance/obligations/"),
      apiRequest("/api/v1/compliance/validity/"),
      apiRequest("/api/v1/organisation/"),
    ]);
    return {
      documents,
      obligations: caseRecord
        ? obligations.filter((o) => o.case_number === caseRecord.case_number)
        : obligations,
      validity: caseRecord
        ? validity.filter(
            (v) => v.institution_code === caseRecord.institution_code,
          )
        : validity,
      directory,
      revision,
    };
  }, [revision, caseRecord]);
  const { data, error } = usePolling(fetcher);
  async function run(action) {
    setBusy(true);
    setNotice(null);
    try {
      await action();
      setRevision((r) => r + 1);
    } catch (err) {
      setNotice(err.message);
    } finally {
      setBusy(false);
    }
  }
  async function upload(e) {
    e.preventDefault();
    const form = new FormData(e.currentTarget);
    const file = form.get("file");
    await run(async () => {
      if (file.size > 25 * 1024 * 1024)
        throw new Error("Maximum file size is 25 MB.");
      const result = await apiRequest("/api/v1/documents/", {
        method: "POST",
        body: JSON.stringify({
          institution_id: caseRecord?.institution_id || form.get("institution"),
          case_id: caseRecord?.id || form.get("case") || null,
          document_type: form.get("type"),
          original_filename: file.name,
          declared_mime_type: file.type,
          content_base64: await readFile(file),
        }),
      });
      setNotice(
        `Received document ${result.id}. Scan status: ${result.lifecycle_state}. Receipt time is preserved.`,
      );
    });
  }
  async function submitEvidence(e) {
    e.preventDefault();
    const form = new FormData(e.currentTarget);
    await run(async () => {
      await apiRequest(
        `/api/v1/compliance/obligations/${form.get("obligation")}/submit/`,
        {
          method: "POST",
          body: JSON.stringify({ document_version_id: form.get("document") }),
        },
      );
      setNotice("Evidence submitted for review.");
    });
  }
  async function review(e) {
    e.preventDefault();
    const form = new FormData(e.currentTarget);
    await run(async () => {
      await apiRequest(`/api/v1/documents/${form.get("document")}/review/`, {
        method: "POST",
        body: JSON.stringify({
          accept: form.get("outcome") === "accept",
          notes: form.get("notes"),
        }),
      });
      setNotice("Document review recorded.");
    });
  }
  async function download(id) {
    await run(async () => {
      const grant = await apiRequest(
        `/api/v1/documents/${id}/download-grant/`,
        { method: "POST" },
      );
      const a = document.createElement("a");
      a.href = `/api/v1/documents/${id}/download-grant/?token=${encodeURIComponent(grant.grant_token)}`;
      a.download = "";
      document.body.append(a);
      a.click();
      a.remove();
    });
  }
  return (
    <section>
      <h2>Evidence & continuing compliance</h2>
      {error && <p role="alert">{error.message}</p>}
      {notice && <p role="status">{notice}</p>}
      <div className="workspace-grid">
        {institution && (
          <article className="card">
            <h3>Upload supporting evidence</h3>
            <form onSubmit={upload}>
              {caseRecord ? (
                <p>
                  For {caseRecord.case_number} · {caseRecord.institution_name}
                </p>
              ) : (
                <>
                  <label htmlFor="upload-inst">Institution</label>
                  <select id="upload-inst" name="institution" required>
                    {user.scope?.institution_ids?.map((id) => (
                      <option key={id} value={id}>
                        {data?.directory?.institutions?.find((i) => i.id === id)
                          ?.name || id}
                      </option>
                    ))}
                  </select>
                  <label htmlFor="upload-case">Case ID (optional)</label>
                  <input id="upload-case" name="case" />
                </>
              )}
              <label htmlFor="upload-type">Document type</label>
              <input id="upload-type" name="type" required />
              <label htmlFor="upload-file">Document file</label>
              <input
                id="upload-file"
                name="file"
                type="file"
                accept=".pdf,.png,.jpg,.jpeg"
                required
              />
              <button disabled={busy}>Upload to quarantine</button>
            </form>
          </article>
        )}
        {data && !readOnly && (
          <article className="card">
            <h3>
              {institution ? "Submit obligation evidence" : "Review document"}
            </h3>
            <form onSubmit={institution ? submitEvidence : review}>
              {institution && (
                <>
                  <label htmlFor="obligation">Obligation</label>
                  <select name="obligation" id="obligation" required>
                    <option value="">Select obligation</option>
                    {data.obligations.map((o) => (
                      <option key={o.id} value={o.id}>
                        {o.obligation_code} · {o.state}
                      </option>
                    ))}
                  </select>
                </>
              )}
              <label htmlFor="evidence-document">Document version</label>
              <select id="evidence-document" name="document" required>
                <option value="">Select document</option>
                {data.documents.map((d) => (
                  <option key={d.id} value={d.id}>
                    {d.original_filename} · v{d.version_number} ·{" "}
                    {d.lifecycle_state}
                  </option>
                ))}
              </select>
              {!institution && (
                <>
                  <label htmlFor="review-outcome">Outcome</label>
                  <select id="review-outcome" name="outcome">
                    <option value="accept">Accept</option>
                    <option value="reject">Request clarification</option>
                  </select>
                  <label htmlFor="review-notes">Review finding</label>
                  <textarea name="notes" id="review-notes" required />
                </>
              )}
              <button disabled={busy}>Save evidence action</button>
            </form>
          </article>
        )}
      </div>
      {data && (
        <>
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>Document</th>
                  <th>Version</th>
                  <th>Scan</th>
                  <th>Access</th>
                </tr>
              </thead>
              <tbody>
                {data.documents.map((d) => (
                  <tr key={d.id}>
                    <td>{d.original_filename}</td>
                    <td>{d.version_number}</td>
                    <td>{d.lifecycle_state}</td>
                    <td>
                      <button
                        disabled={busy || d.lifecycle_state !== "CLEAN"}
                        onClick={() => download(d.id)}
                      >
                        Download
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <h3>Continuing obligations</h3>
          {data.obligations.length === 0 && (
            <p>No obligations in your scope.</p>
          )}
          {data.obligations.map((o) => (
            <p key={o.id}>
              <strong>{o.obligation_code}</strong> · {o.condition_text} ·{" "}
              {o.state} · Due {new Date(o.due_at).toLocaleDateString()}
            </p>
          ))}
          <h3>Document validity</h3>
          {data.validity.length === 0 && (
            <p>No accepted validity records in your scope.</p>
          )}
          {data.validity.map((v) => (
            <p key={v.id}>
              {v.document_type} · {v.state} · Valid until {v.valid_until}
            </p>
          ))}
        </>
      )}
    </section>
  );
}
