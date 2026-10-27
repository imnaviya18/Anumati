import { createContext, useContext, useEffect, useState } from "react";
import { apiRequest } from "../api/client";
const AuthContext = createContext(null);
const normalize = (actor) => ({
  ...actor,
  roles: actor.scope?.roles || actor.roles || [],
});
export function AuthProvider({ children, initialUser }) {
  const [user, setUser] = useState(initialUser ? normalize(initialUser) : null);
  const [loading, setLoading] = useState(initialUser === undefined);
  const [error, setError] = useState(null);
  useEffect(() => {
    if (initialUser !== undefined) return;
    let active = true;
    apiRequest("/api/v1/auth/me/")
      .then((actor) => {
        if (active) setUser(normalize(actor));
      })
      .catch((err) => {
        if (active && ![401, 403].includes(err.status)) setError(err.message);
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [initialUser]);
  async function signIn(username, password) {
    await apiRequest("/api/v1/auth/csrf/");
    const actor = await apiRequest("/api/v1/auth/login/", {
      method: "POST",
      body: JSON.stringify({ username, password }),
    });
    setUser(normalize(actor));
    setError(null);
  }
  async function signOut() {
    await apiRequest("/api/v1/auth/logout/", { method: "POST" });
    setUser(null);
  }
  return (
    <AuthContext.Provider
      value={{ user, setUser, loading, error, signIn, signOut }}
    >
      {children}
    </AuthContext.Provider>
  );
}
export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside AuthProvider");
  return ctx;
}
