import { CaseAssignmentPanel } from "./CaseAssignmentPanel";
import { useAuth } from "../auth/AuthContext";
import { EvidenceWorkspace } from "./EvidenceWorkspace";
import { ComplianceActions } from "./ComplianceActions";
import { EvcWorkspace } from "./EvcWorkspace";
import { CaseActions } from "./CaseActions";
import { CaseLifecycleActions } from "./OperationalActions";
import { CaseHistory } from "./CaseHistory";
import { useCallback, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { apiRequest } from "../api/client";
import { usePolling } from "../hooks/usePolling";
export function CaseWorkbench({
  institution = false,
  readOnly = false,
  region = "",
  bureau = "",
}) {
  const { user } = useAuth();
  const canAssign = user?.roles?.some((r) =>
    ["REGIONAL_OFFICER", "BUREAU_OFFICER", "COMPETENT_AUTHORITY"].includes(r),
  );
  const canReview = user?.roles?.some((r) =>
    [
      "SCRUTINY_MEMBER",
      "REGIONAL_OFFICER",
      "BUREAU_OFFICER",
      "COMPETENT_AUTHORITY",
    ].includes(r),
  );
  const [params, setParams] = useSearchParams();
  const caseId = params.get("case");
  const [page, setPage] = useState(1),
    [query, setQuery] = useState("");
  const fetcher = useCallback(
    () =>
      apiRequest(
        `/api/v1/cases/?page=${page}&q=${encodeURIComponent(query)}&region_code=${encodeURIComponent(region)}&bureau_code=${encodeURIComponent(bureau)}`,
      ),
    [page, query, region, bureau],
  );
  const { data, error, loading, dataAsOf } = usePolling(fetcher);
  const fetchDetail = useCallback(
    () =>
      caseId ? apiRequest(`/api/v1/cases/${caseId}/`) : Promise.resolve(null),
    [caseId],
  );
  const {
    data: detail,
    error: detailError,
    refresh: refreshDetail,
  } = usePolling(fetchDetail);
  const selected = detail?.id === caseId ? detail : null;
  function open(id) {
    const next = new URLSearchParams(params);
    next.set("case", id);
    setParams(next);
  }
  return (
    <section className="case-workbench">
      <h2>
        {readOnly
          ? "Case history & evidence drill-down"
          : institution
            ? "Your applications"
            : "Assigned case queue"}
      </h2>
      <label htmlFor="case-search">
        Search case number or institution code
      </label>
      <input
        id="case-search"
        value={query}
        onChange={(e) => {
          setQuery(e.target.value);
          setPage(1);
        }}
      />
      <p className="muted">Data as of: {dataAsOf || "Awaiting response"}</p>
      {loading && <p role="status">Loading cases…</p>}
      {error && <p role="alert">Unable to load cases: {error.message}</p>}
      {data && (
        <>
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>Application</th>
                  <th>Institution</th>
                  <th>Status</th>
                  <th>Stage</th>
                  <th>Action</th>
                </tr>
              </thead>
              <tbody>
                {data.results.map((c) => (
                  <tr key={c.id}>
                    <td>{c.case_number}</td>
                    <td>{c.institution_name}</td>
                    <td>{c.status.replaceAll("_", " ")}</td>
                    <td>{c.current_stage_type || "—"}</td>
                    <td>
                      <button onClick={() => open(c.id)}>Open case</button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {data.results.length === 0 && (
            <p className="empty-state">
              No applications match your current scope and search.
            </p>
          )}
          <div className="pagination">
            <button
              disabled={!data.previous}
              onClick={() => setPage((p) => p - 1)}
            >
              Previous
            </button>
            <span>
              Page {page} · {data.count} applications
            </span>
            <button disabled={!data.next} onClick={() => setPage((p) => p + 1)}>
              Next
            </button>
          </div>
        </>
      )}
      {selected && (
        <div className="card">
          <h2>{selected.case_number}</h2>
          <p>
            {selected.institution_name} · {selected.region_code}
          </p>
          <button
            onClick={() => {
              const next = new URLSearchParams(params);
              next.delete("case");
              setParams(next);
            }}
          >
            Close case details
          </button>
          <CaseHistory caseId={selected.id} />
          {!readOnly && canAssign && (
            <CaseAssignmentPanel caseRecord={selected} />
          )}

          {!readOnly && (
            <CaseLifecycleActions
              caseRecord={selected}
              institution={institution}
              onRefresh={refreshDetail}
            />
          )}
          <p>
            {selected.status} · Version {selected.version}
          </p>
          <ol>
            {selected.stage_instances.map((s) => (
              <li key={s.id}>
                {s.stage_type} · {s.status} · {s.completion_reason}
                {s.findings?.length > 0 && (
                  <pre>{JSON.stringify(s.findings, null, 2)}</pre>
                )}
              </li>
            ))}
          </ol>
          <h3>Deficiency & response history</h3>
          {(selected.deficiency_history || []).map((c) => (
            <article key={c.id}>
              <pre>{JSON.stringify(c.deficiencies_recorded, null, 2)}</pre>
              <p>{c.institution_response || "Awaiting institution response"}</p>
              <p>
                {c.responded_at
                  ? new Date(c.responded_at).toLocaleString()
                  : "Open"}
              </p>
            </article>
          ))}
          {!readOnly && (
            <CaseActions
              key={selected.id}
              caseRecord={selected}
              onSaved={refreshDetail}
            />
          )}
          <EvidenceWorkspace
            key={`evidence-${selected.id}`}
            caseRecord={selected}
            institution={institution}
            readOnly={readOnly || (!institution && !canReview)}
          />
          {!readOnly && (institution || canReview) && (
            <ComplianceActions
              key={`compliance-${selected.id}`}
              institution={institution}
              caseRecord={selected}
            />
          )}
          {!institution &&
            !readOnly &&
            selected.prescribed_stages?.includes("EVC") && (
              <EvcWorkspace key={`evc-${selected.id}`} caseRecord={selected} />
            )}
        </div>
      )}
      {detailError && <p role="alert">{detailError.message}</p>}
    </section>
  );
}
