import { CaseAssignmentPanel } from "./CaseAssignmentPanel";
import { useCallback, useState } from "react";
import { apiRequest } from "../api/client";
import { usePolling } from "../hooks/usePolling";
const roles = [
  "INSTITUTION_USER",
  "SCRUTINY_MEMBER",
  "EVC_MEMBER",
  "REGIONAL_OFFICER",
  "BUREAU_OFFICER",
  "COMMITTEE_MEMBER",
  "COMPETENT_AUTHORITY",
  "OVERSIGHT_AUDITOR",
  "POLICY_ADMIN",
  "TECHNICAL_ADMIN",
];
export function AdministrationDirectory() {
  const [refresh, setRefresh] = useState(0);
  const [notice, setNotice] = useState(null);
  const [busy, setBusy] = useState(false);
  const [entity, setEntity] = useState("REGION");
  const fetcher = useCallback(
    async () => ({
      users: await apiRequest("/api/v1/auth/users/"),
      directory: await apiRequest("/api/v1/organisation/"),
      refresh,
    }),
    [refresh],
  );
  const { data, error } = usePolling(fetcher);
  async function submit(e, path, extra = {}) {
    e.preventDefault();
    const form = e.currentTarget;
    const payload = { ...Object.fromEntries(new FormData(form)), ...extra };
    Object.keys(payload).forEach((k) => {
      if (payload[k] === "") delete payload[k];
    });
    if (payload.delegated_powers)
      payload.delegated_powers = payload.delegated_powers
        .split(",")
        .map((s) => s.trim())
        .filter(Boolean);
    setBusy(true);
    try {
      await apiRequest(path, { method: "POST", body: JSON.stringify(payload) });
      setNotice("Saved successfully.");
      form.reset();
      setRefresh((r) => r + 1);
    } catch (err) {
      setNotice(err.message);
    } finally {
      setBusy(false);
    }
  }
  const userSelect = (id) => (
    <>
      <label htmlFor={id}>User</label>
      <select id={id} name="user_id" required>
        <option value="">Select user</option>
        {data?.users.map((u) => (
          <option key={u.id} value={u.id}>
            {u.username}
          </option>
        ))}
      </select>
    </>
  );
  const scopeSelect = (name, label, items) => (
    <>
      <label htmlFor={name}>{label}</label>
      <select id={name} name={name}>
        <option value="">Select if applicable</option>
        {items?.map((i) => (
          <option key={i.id} value={i.id}>
            {i.name}
          </option>
        ))}
      </select>
    </>
  );
  return (
    <section>
      <h2>Directory & access administration</h2>
      {error && <p role="alert">{error.message}</p>}
      {notice && <p role="status">{notice}</p>}
      <div className="workspace-grid">
        <article className="card">
          <h3>Create user</h3>
          <form onSubmit={(e) => submit(e, "/api/v1/auth/users/")}>
            <label htmlFor="new-user">Username</label>
            <input id="new-user" name="username" required autoComplete="off" />
            <label htmlFor="new-email">Email</label>
            <input id="new-email" name="email" type="email" />
            <label htmlFor="new-password">Initial password</label>
            <input
              id="new-password"
              name="password"
              type="password"
              minLength="8"
              autoComplete="new-password"
              required
            />
            <button disabled={busy}>Create user</button>
          </form>
        </article>
        <article className="card">
          <h3>Create directory record</h3>
          <label htmlFor="entity-kind">Record type</label>
          <select
            id="entity-kind"
            value={entity}
            onChange={(e) => setEntity(e.target.value)}
          >
            {["REGION", "BUREAU", "INSTITUTION", "COMMITTEE"].map((x) => (
              <option key={x}>{x}</option>
            ))}
          </select>
          <form
            onSubmit={(e) =>
              submit(e, "/api/v1/organisation/", { entity_type: entity })
            }
          >
            <label htmlFor="entity-code">Code / permanent ID</label>
            <input id="entity-code" name="code" required />
            <label htmlFor="entity-name">Name</label>
            <input id="entity-name" name="name" required />
            {["INSTITUTION", "COMMITTEE"].includes(entity) &&
              scopeSelect("region_id", "Region", data?.directory.regions)}
            {entity === "INSTITUTION" && (
              <>
                <label htmlFor="entity-state">State</label>
                <input id="entity-state" name="state_name" required />
              </>
            )}
            {entity === "COMMITTEE" && (
              <>
                <label htmlFor="committee-kind">Committee type</label>
                <select id="committee-kind" name="committee_type">
                  {["SCRUTINY", "RE_SCRUTINY", "EVC", "SHC", "SAC", "SCSC"].map(
                    (x) => (
                      <option key={x}>{x}</option>
                    ),
                  )}
                </select>
              </>
            )}
            <button disabled={busy}>Create record</button>
          </form>
        </article>
        <article className="card">
          <h3>Assign role and scope</h3>
          <form onSubmit={(e) => submit(e, "/api/v1/access/role-assignments/")}>
            {userSelect("role-user")}
            <label htmlFor="new-role">Role</label>
            <select name="role" id="new-role">
              {roles.map((r) => (
                <option key={r}>{r}</option>
              ))}
            </select>
            {scopeSelect(
              "institution_id",
              "Institution scope",
              data?.directory.institutions,
            )}
            <label htmlFor="role-region-id">Region ID (regional roles)</label>
            <select name="region_id" id="role-region-id">
              <option value="">None</option>
              {data?.directory.regions.map((r) => (
                <option key={r.id} value={r.id}>
                  {r.name}
                </option>
              ))}
            </select>
            {scopeSelect("bureau_id", "Bureau scope", data?.directory.bureaus)}
            {scopeSelect(
              "committee_id",
              "Committee scope",
              data?.directory.committees,
            )}
            <label htmlFor="delegated-powers">
              Delegated powers (comma separated authorised references)
            </label>
            <input id="delegated-powers" name="delegated_powers" />
            <label htmlFor="role-reason">Assignment reason</label>
            <textarea id="role-reason" name="reason" required />
            <button disabled={busy}>Assign role</button>
          </form>
        </article>
        <CaseAssignmentPanel />
      </div>
    </section>
  );
}
