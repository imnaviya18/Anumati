import { NavLink } from "react-router-dom";
import { useState } from "react";
import { useAuth } from "../auth/AuthContext";
import { workspaceLinks as links } from "../workspaces";
export function AppLayout({ children }) {
  const { user, signOut } = useAuth();
  const [error, setError] = useState(null);
  return (
    <div className="app-shell">
      <a className="skip-link" href="#main-content">
        Skip to main content
      </a>
      <div className="utility-bar">
        <span>
          LOCAL DEMONSTRATION · Synthetic institutions · Not an AICTE production
          service
        </span>
        <span>English</span>
      </div>
      <header className="app-header">
        <NavLink className="app-brand" to="/">
          <span className="brand-mark" aria-hidden="true">
            A
          </span>
          <span>
            <strong>ANUMATI</strong>
            <span className="app-subtitle">
              Integrated approval & compliance portal
            </span>
          </span>
        </NavLink>
        <div className="account">
          {user ? (
            <>
              <span>{user.username}</span>
              <button
                onClick={async () => {
                  try {
                    await signOut();
                  } catch (err) {
                    setError(err.message);
                  }
                }}
              >
                Sign out
              </button>
            </>
          ) : (
            <span>Transparent processes. Accountable decisions.</span>
          )}
        </div>
      </header>
      <nav aria-label="Workspace Navigation" className="app-nav">
        <NavLink to="/">Home</NavLink>
        {links
          .filter(([, , roles]) => user?.roles?.some((r) => roles.includes(r)))
          .map(([path, label]) => (
            <NavLink key={path} to={path}>
              {label}
            </NavLink>
          ))}
      </nav>
      <main id="main-content" className="app-main" tabIndex="-1">
        {error && <p role="alert">{error}</p>}
        {children}
      </main>
      <footer>
        <strong>ANUMATI</strong>
        <span>
          Approval workflow · Compliance monitoring · Alert management
        </span>
        <span>Prototype · Authorised institutional access</span>
      </footer>
    </div>
  );
}
