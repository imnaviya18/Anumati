import { canOpenWorkspace, workspaceLinks } from "../workspaces";
import { useState } from "react";
import { Navigate, useLocation } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";
export function homeFor(user) {
  const match = workspaceLinks.find(([, , roles]) =>
    user?.roles?.some((role) => roles.includes(role)),
  );
  return match ? match[0] : "/";
}
export function LoginPage() {
  const { user, loading, signIn, error: sessionError } = useAuth();
  const location = useLocation();
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  if (loading) return <p role="status">Checking your session…</p>;
  if (user)
    return (
      <Navigate
        to={
          canOpenWorkspace(user, location.state?.from)
            ? location.state.from
            : homeFor(user)
        }
        replace
      />
    );
  async function submit(e) {
    e.preventDefault();
    const form = new FormData(e.currentTarget);
    setBusy(true);
    setError(null);
    try {
      await signIn(form.get("username"), form.get("password"));
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="login-layout">
      <section className="intro">
        <span className="eyebrow">INSTITUTIONAL SERVICES PORTAL</span>
        <h1>One place for every step of approval.</h1>
        <p>
          Submit applications, respond to observations and track compliance
          through a connected institutional workspace.
        </p>
        <div className="service-steps">
          <p>01 · Apply & track</p>
          <p>02 · Review & respond</p>
          <p>03 · Maintain compliance</p>
        </div>
      </section>
      <section className="card login-card">
        <span className="eyebrow">SECURE ACCESS</span>
        <h2>Sign in to Anumati</h2>
        <p>Use the account provided by your administrator.</p>
        <form onSubmit={submit}>
          <label htmlFor="username">Username</label>
          <input
            id="username"
            name="username"
            autoComplete="username"
            required
          />
          <label htmlFor="password">Password</label>
          <input
            id="password"
            name="password"
            type="password"
            autoComplete="current-password"
            required
          />
          <button disabled={busy}>{busy ? "Signing in…" : "Sign in"}</button>
        </form>
        {(error || sessionError) && <p role="alert">{error || sessionError}</p>}
        <p className="muted">
          Need access? Contact your institution’s designated administrator.
        </p>
      </section>
    </div>
  );
}
