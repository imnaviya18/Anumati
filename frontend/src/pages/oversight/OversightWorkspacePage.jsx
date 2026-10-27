import { OversightDetails } from "../../components/OversightDetails";
import { useCallback, useState } from "react";
import { apiFetch } from "../../api/client";
import { usePolling } from "../../hooks/usePolling";

const STATUTORY_REPORTS = [
  { code: "application_pendency", label: "1. Application Pendency Report" },
  { code: "evc_status", label: "2. EVC Status Report" },
  { code: "undertaking_compliance", label: "3. Undertaking Compliance Report" },
  { code: "document_validity", label: "4. Document Validity Report" },
  { code: "overdue_cases", label: "5. Overdue Cases Report" },
  {
    code: "region_wise_processing_performance",
    label: "6. Region-Wise Processing Performance Report",
  },
];

/**
 * Oversight / Audit Workspace (Sheet 01 Block 07 & 09, Sheet 04 J6, PS Sections B & F.3)
 * - Real-time authenticated polling dashboard with visible "data as of" timestamp
 * - Exact 6 statutory reports with CSV export
 * - Immutable hash-chained audit trail inspection
 */
export function OversightWorkspacePage() {
  const [selectedReport, setSelectedReport] = useState("application_pendency");
  const [regionFilter, setRegionFilter] = useState("");
  const [bureauFilter, setBureauFilter] = useState("");

  const fetchDashboard = useCallback(async () => {
    return apiFetch(
      `/api/v1/reporting/dashboard/?region_code=${encodeURIComponent(regionFilter)}&bureau_code=${encodeURIComponent(bureauFilter)}`,
    );
  }, [regionFilter, bureauFilter]);

  const { data, dataAsOf, loading, error } = usePolling(fetchDashboard, 30000);

  const csvUrl = `/api/v1/reporting/reports/${selectedReport}/?export=csv${
    regionFilter ? `&region_code=${encodeURIComponent(regionFilter)}` : ""
  }`;

  return (
    <section aria-labelledby="oversight-heading">
      <h1 id="oversight-heading">Oversight / Audit Workspace</h1>
      <p>
        Review regional and bureau pendency, assigned workload, escalations and
        case history.
      </p>

      <label htmlFor="bureau-filter">Filter dashboard by bureau code</label>
      <input
        id="bureau-filter"
        value={bureauFilter}
        onChange={(e) => setBureauFilter(e.target.value)}
      />
      <div className="polling-banner" aria-live="polite">
        <strong>Data as of:</strong> {dataAsOf || "Loading..."}
      </div>

      {loading && <p role="status">Loading oversight dashboard...</p>}
      {error && (
        <p role="alert">Error loading oversight data: {error.message}</p>
      )}

      {!loading && data && (
        <div className="workspace-grid">
          <div className="card">
            <h2>National / Regional Pendency Overview</h2>
            <p>Total Cases in Scope: {data.total_visible_cases ?? 0}</p>
            <p>Overdue Deadlines: {data.timeline_alerts?.overdue_count ?? 0}</p>
            <p>
              Open Escalations:{" "}
              {data.timeline_alerts?.open_escalations_count ?? 0}
            </p>
          </div>

          <div className="card">
            <h2>Statutory Reports &amp; CSV Export (PS Section F.3)</h2>
            <label htmlFor="report-select">
              Select Statutory Report (Exact 6 Reports)
            </label>
            <select
              id="report-select"
              value={selectedReport}
              onChange={(e) => setSelectedReport(e.target.value)}
            >
              {STATUTORY_REPORTS.map((r) => (
                <option key={r.code} value={r.code}>
                  {r.label}
                </option>
              ))}
            </select>

            <label htmlFor="region-filter-input">
              Filter by Region Code (Optional)
            </label>
            <input
              id="region-filter-input"
              type="text"
              value={regionFilter}
              onChange={(e) => setRegionFilter(e.target.value)}
              placeholder="e.g. NRO, SRO, WRO"
            />

            <p>
              <a href={csvUrl} download={`${selectedReport}.csv`}>
                Export {selectedReport}.csv
              </a>
            </p>
          </div>
        </div>
      )}
      <OversightDetails
        snapshot={data}
        region={regionFilter}
        bureau={bureauFilter}
      />
    </section>
  );
}
