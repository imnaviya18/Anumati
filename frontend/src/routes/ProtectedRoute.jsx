import { Navigate, useLocation } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";
export function ProtectedRoute({ allowedRoles, children }) {
  const { user, loading } = useAuth();
  const location = useLocation();
  if (loading) return <p role="status">Checking your session…</p>;
  if (!user)
    return <Navigate to="/login" state={{ from: location.pathname }} replace />;
  if (!user.roles?.some((role) => allowedRoles.includes(role)))
    return (
      <section role="alert" aria-label="Access Denied">
        <h2>Access Denied</h2>
        <p>Your active roles do not permit access to this workspace.</p>
      </section>
    );
  return children;
}
