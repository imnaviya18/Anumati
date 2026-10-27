/**
 * Local fetch wrapper with CSRF, correlation ID, and idempotency key support
 * Source: Sheet 01 Block 01, Sheet 05, Sheet 06 K1
 */

export function getCsrfToken() {
  const match = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
  return match ? decodeURIComponent(match[1]) : "";
}

export async function apiRequest(path, options = {}) {
  const headers = {
    Accept: "application/json",
    ...(options.body && !(options.body instanceof FormData)
      ? { "Content-Type": "application/json" }
      : {}),
    ...(options.headers || {}),
  };

  const method = (options.method || "GET").toUpperCase();
  if (!["GET", "HEAD", "OPTIONS", "TRACE"].includes(method)) {
    const csrf = getCsrfToken();
    if (csrf) {
      headers["X-CSRFToken"] = csrf;
    }
  }

  const response = await fetch(path, {
    credentials: "same-origin",
    ...options,
    method,
    headers,
  });

  const data = await response.json().catch(() => null);
  if (!response.ok) {
    const error = new Error(data?.detail || `HTTP ${response.status}`);
    error.status = response.status;
    error.payload = data;
    throw error;
  }
  if (!["GET", "HEAD", "OPTIONS"].includes(method))
    window.dispatchEvent(new Event("anumati:data-changed"));
  return data;
}

export const apiFetch = apiRequest;
