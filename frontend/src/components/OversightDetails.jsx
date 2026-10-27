import { usePolling } from "../hooks/usePolling";
import { apiRequest } from "../api/client";
import { CaseWorkbench } from "./CaseWorkbench";
const fetchEscalations = () => apiRequest("/api/v1/deadlines/");
function DataTable({ title, rows = [], columns }) {
  return (
    <article className="card">
      <h2>{title}</h2>
      {rows.length ? (
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                {columns.map(([key, label]) => (
                  <th key={key}>{label}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((row, i) => (
                <tr key={i}>
                  {columns.map(([key]) => (
                    <td key={key}>{row[key] ?? "Unassigned"}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <p>No records in this scope.</p>
      )}
    </article>
  );
}
export function OversightDetails({ snapshot, region, bureau }) {
  const { data, error } = usePolling(fetchEscalations);
  return (
    <>
      <div className="workspace-grid">
        <DataTable
          title="Regional pendency"
          rows={snapshot?.status_by_region}
          columns={[
            ["region__name", "Region"],
            ["count", "Total cases"],
            ["pending_count", "Pending cases"],
          ]}
        />
        <DataTable
          title="Bureau pendency"
          rows={snapshot?.status_by_bureau}
          columns={[
            ["responsible_bureau__name", "Bureau"],
            ["count", "Total cases"],
            ["pending_count", "Pending cases"],
          ]}
        />
        <DataTable
          title="Officer workload"
          rows={snapshot?.workload_by_officer}
          columns={[
            ["assigned_officer__username", "Officer"],
            ["stage_type", "Stage"],
            ["active_cases", "Active stages"],
          ]}
        />
        <DataTable
          title="Committee workload"
          rows={snapshot?.workload_by_committee}
          columns={[
            ["assigned_committee__code", "Committee"],
            ["stage_type", "Stage"],
            ["active_cases", "Active stages"],
          ]}
        />
        <DataTable
          title="Pending case ageing"
          rows={snapshot?.ageing}
          columns={[
            ["band", "Age"],
            ["count", "Cases"],
          ]}
        />
        <DataTable
          title="Stage bottlenecks"
          rows={snapshot?.bottlenecks}
          columns={[
            ["stage_type", "Stage"],
            ["status", "Status"],
            ["pending_count", "Pending"],
          ]}
        />
      </div>
      <p>
        Stages awaiting assignment: {snapshot?.unassigned_stages ?? "Loading"}
      </p>
      {error && <p role="alert">{error.message}</p>}
      <DataTable
        title="Escalation register (all authorised scope)"
        rows={data?.escalations}
        columns={[
          ["case_number", "Case"],
          ["owner", "Owner"],
          ["reason", "Blocker / reason"],
          ["state", "State"],
          ["closure_reason", "Resolution"],
        ]}
      />
      <CaseWorkbench readOnly region={region} bureau={bureau} />
    </>
  );
}
