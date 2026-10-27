import { useState } from "react";
import { apiRequest } from "../api/client";
import { usePolling } from "../hooks/usePolling";
const fetchAlerts = () => apiRequest("/api/v1/notifications/");
export function Notifications() {
  const { data, error } = usePolling(fetchAlerts);
  const [notice, setNotice] = useState(null);
  return (
    <details className="card">
      <summary>
        Notifications{" "}
        {data ? `(${data.filter((a) => !a.read_at).length} unread)` : ""}
      </summary>
      {error && <p role="alert">{error.message}</p>}
      {notice && <p role="status">{notice}</p>}
      {data?.length === 0 && <p>No notifications.</p>}
      {data?.map((a) => (
        <article key={a.id}>
          <h3>{a.subject}</h3>
          <p>{a.body}</p>
          <p className="muted">
            {new Date(a.created_at).toLocaleString()} · {a.outcome_state}
          </p>
          {!a.read_at && (
            <button
              onClick={async () => {
                try {
                  await apiRequest(`/api/v1/notifications/${a.id}/read/`, {
                    method: "POST",
                  });
                  setNotice("Notification marked as read.");
                } catch (err) {
                  setNotice(err.message);
                }
              }}
            >
              Mark as read
            </button>
          )}
        </article>
      ))}
    </details>
  );
}
