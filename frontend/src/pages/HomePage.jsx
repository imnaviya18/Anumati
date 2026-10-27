import { Link } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";
import { workspaceLinks, canOpenWorkspace } from "../workspaces";
import { LoginPage } from "./LoginPage";
import { usePolling } from "../hooks/usePolling";
import { apiRequest } from "../api/client";
const readHealth = () => apiRequest("/api/v1/health/");
const features = {
  "/institution": [
    "Submit and track applications",
    "Respond to deficiencies",
    "Upload case evidence",
    "Track obligations and renewals",
  ],
  "/officer": [
    "Assigned case review and findings",
    "Evidence verification",
    "EVC scheduling and reports",
    "Authorised decisions and referrals",
    "Compliance review",
    "Deadlines and escalation actions",
  ],
  "/oversight": [
    "Regional and bureau pendency",
    "Officer and committee workload",
    "Ageing and bottlenecks",
    "Escalation register",
    "Case history and evidence",
    "Reports and CSV exports",
  ],
  "/policy": [
    "Draft rules and provenance",
    "Validation and regression preview",
    "Approve changes and activate versions",
    "Controlled case migration",
    "Sync exception reconciliation",
  ],
  "/admin": [
    "Users and directory",
    "Role and scope assignments",
    "Case reviewer assignments",
    "Failed delivery replay",
  ],
};
export function HomePage() {
  const { user, loading } = useAuth();
  const { data: health, error } = usePolling(readHealth, 30000);
  if (loading) return <p role="status">Checking your session…</p>;
  if (!user) return <LoginPage />;
  return (
    <section>
      <h1>Your service dashboard</h1>
      <p>
        Welcome, {user.username}. These workspaces and features reflect your
        active access. Select a case once to carry its context through review,
        evidence and compliance.
      </p>
      <p role="status">
        {error
          ? "Unable to verify service connection"
          : health?.database === "connected"
            ? "Connected to the shared application database"
            : "Checking database connection…"}
      </p>
      <div className="workspace-grid">
        {workspaceLinks
          .filter(([path]) => canOpenWorkspace(user, path))
          .map(([path, label]) => (
            <article className="card" key={path}>
              <h2>{label}</h2>
              <ul>
                {features[path].map((feature) => (
                  <li key={feature}>{feature}</li>
                ))}
              </ul>
              <Link className="workspace-link" to={path}>
                Open {label}
              </Link>
            </article>
          ))}
      </div>
      {!workspaceLinks.some(([path]) => canOpenWorkspace(user, path)) && (
        <p>No workspace role is assigned. Contact your access administrator.</p>
      )}
      <p className="muted">
        Demonstration data and rules only. External AICTE synchronization is not
        connected.
      </p>
    </section>
  );
}
