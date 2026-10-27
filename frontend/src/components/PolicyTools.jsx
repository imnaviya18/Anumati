import { useState } from "react";
import { apiRequest } from "../api/client";
import { usePolling } from "../hooks/usePolling";
const fetchPolicies = () => apiRequest("/api/v1/policy/");
export function PolicyTools() {
  const { data, error } = usePolling(fetchPolicies);
  const [id, setId] = useState("");
  const [config, setConfig] = useState("{}");
  const [notice, setNotice] = useState(null);
  const [busy, setBusy] = useState(false);
  async function save(e) {
    e.preventDefault();
    const f = new FormData(e.currentTarget);
    setBusy(true);
    try {
      await apiRequest(`/api/v1/policy/${id}/edit/`, {
        method: "POST",
        body: JSON.stringify({
          reason: f.get("reason"),
          changes: JSON.parse(config),
        }),
      });
      setNotice(
        "Draft saved. Validation and dry-run must be repeated before activation.",
      );
    } catch (err) {
      setNotice(err.message);
    } finally {
      setBusy(false);
    }
  }
  async function migrate(e) {
    e.preventDefault();
    const f = new FormData(e.currentTarget);
    setBusy(true);
    try {
      const result = await apiRequest("/api/v1/policy/migrate/", {
        method: "POST",
        body: JSON.stringify({
          source_policy_id: f.get("source"),
          target_policy_id: f.get("target"),
          case_ids: f
            .get("cases")
            .split(/[\s,]+/)
            .filter(Boolean),
          reason: f.get("reason"),
        }),
      });
      setNotice(
        `Migration recorded for ${result.affected_case_ids.length} cases.`,
      );
    } catch (err) {
      setNotice(err.message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <section>
      <h2>Configuration provenance & controlled changes</h2>
      {error && <p role="alert">{error.message}</p>}
      {notice && <p role="status">{notice}</p>}
      <p>
        Research drafts are not approved regulations. Production activation
        requires rule sources, effective dates, versions, approving authority
        and completed owner validation.
      </p>
      <div className="workspace-grid">
        <article className="card">
          <h3>Edit versioned draft</h3>
          <form onSubmit={save}>
            <label htmlFor="policy-edit">Policy version</label>
            <select
              id="policy-edit"
              value={id}
              onChange={(e) => {
                setId(e.target.value);
                setConfig(
                  JSON.stringify(
                    data.find((p) => p.id === e.target.value)?.configuration ||
                      {},
                    null,
                    2,
                  ),
                );
              }}
              required
            >
              <option value="">Select draft</option>
              {data
                ?.filter((p) =>
                  ["DRAFT", "VALIDATED", "DRY_RUN_PASSED"].includes(p.state),
                )
                .map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.policy_code} v{p.version_number} · {p.state} ·{" "}
                    {p.is_demonstration
                      ? "DEMONSTRATION"
                      : "Pending authoritative approval"}
                  </option>
                ))}
            </select>
            <label htmlFor="policy-config">
              Routes, timelines, calendars, permissions, exceptions and
              provenance
            </label>
            <textarea
              id="policy-config"
              value={config}
              onChange={(e) => setConfig(e.target.value)}
              rows="18"
            />
            <label htmlFor="policy-edit-reason">Change reason</label>
            <textarea id="policy-edit-reason" name="reason" required />
            <button disabled={busy}>Save draft configuration</button>
          </form>
        </article>
        <article className="card">
          <h3>Explicit open-case migration</h3>
          <form onSubmit={migrate}>
            <label htmlFor="migration-source">Current policy</label>
            <select id="migration-source" name="source" required>
              <option value="">Select source</option>
              {data?.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.policy_code} v{p.version_number}
                </option>
              ))}
            </select>
            <label htmlFor="migration-target">Active target policy</label>
            <select id="migration-target" name="target" required>
              <option value="">Select target</option>
              {data
                ?.filter((p) => p.state === "ACTIVE")
                .map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.policy_code} v{p.version_number}
                  </option>
                ))}
            </select>
            <label htmlFor="migration-cases">Case IDs (comma separated)</label>
            <textarea id="migration-cases" name="cases" required />
            <label htmlFor="migration-reason">
              Authorised migration reason
            </label>
            <textarea id="migration-reason" name="reason" required />
            <button disabled={busy}>Migrate selected cases</button>
          </form>
        </article>
      </div>
    </section>
  );
}
