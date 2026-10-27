import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { it, expect } from "vitest";
import { MemoryRouter } from "react-router-dom";
import { AuthProvider } from "../auth/AuthContext";
import { SyncExceptions } from "../components/SyncExceptions";
import { OversightDetails } from "../components/OversightDetails";
import { PolicyWorkspacePage } from "../pages/policy/PolicyWorkspacePage";

it("submits sync resolution with the observed version and audit reason", async () => {
  const row = {
    id: "exception-1",
    source_id: "LOCAL",
    event_id: "EV-1",
    state: "OPEN",
    version: 4,
    owner: "governor",
    baseline_version: 1,
    current_source_version: 1,
    local_snapshot: { notes: "old" },
    incoming_snapshot: { notes: "new" },
  };
  fetch.mockImplementation(async (path, options) => ({
    ok: true,
    json: async () =>
      options?.method === "POST"
        ? { ...row, state: "RESOLVED" }
        : { results: [row], count: 1 },
  }));
  render(<SyncExceptions />);
  await screen.findByText("LOCAL · EV-1");
  fireEvent.change(screen.getByLabelText("Resolution"), {
    target: { value: "ACCEPT_SOURCE" },
  });
  fireEvent.change(screen.getByLabelText("Recorded reason"), {
    target: { value: "Verified synthetic source" },
  });
  fireEvent.click(
    screen.getByRole("button", { name: "Record reconciliation" }),
  );
  await screen.findByText("Reconciliation recorded with audit history.");
  expect(fetch).toHaveBeenCalledWith(
    "/api/v1/policy/sync-exceptions/exception-1/resolve/",
    expect.objectContaining({
      body: JSON.stringify({
        action: "ACCEPT_SOURCE",
        expected_version: 4,
        reason: "Verified synthetic source",
      }),
    }),
  );
});

it("displays bureau workload and escalation owners with read-only case drill-down", async () => {
  fetch.mockImplementation(async (path) => ({
    ok: true,
    json: async () =>
      path.includes("/cases/")
        ? { results: [], count: 0 }
        : {
            escalations: [
              {
                id: "e",
                case_number: "CASE-DEMO",
                owner: "officer",
                reason: "Evidence overdue",
                state: "OPEN",
              },
            ],
          },
  }));
  render(
    <OversightDetails
      snapshot={{
        status_by_bureau: [
          { responsible_bureau__name: "Demo Bureau", count: 3 },
        ],
        workload_by_officer: [
          {
            assigned_officer__username: "reviewer",
            stage_type: "SCRUTINY",
            active_cases: 2,
          },
        ],
      }}
      region="DEMO"
      bureau="B1"
    />,
  );
  expect(screen.getByText("Demo Bureau")).toBeInTheDocument();
  expect(screen.getByText("reviewer")).toBeInTheDocument();
  expect(await screen.findByText("Evidence overdue")).toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: "Execute Guarded Command" }),
  ).not.toBeInTheDocument();
  expect(fetch).toHaveBeenCalledWith(
    expect.stringContaining("bureau_code=B1"),
    expect.anything(),
  );
});

it("requires authority for policy approval and sends the approval reason", async () => {
  const policy = {
    id: "p1",
    policy_code: "DEMO",
    version_number: 2,
    state: "DRY_RUN_PASSED",
    is_demonstration: true,
    configuration: {},
    validation_report: { valid: true },
    dry_run_report: { passed: true },
  };
  fetch.mockImplementation(async (path, options) => ({
    ok: true,
    json: async () =>
      path.includes("sync-exceptions")
        ? { results: [], count: 0 }
        : options?.method === "POST"
          ? { ...policy, state: "APPROVED" }
          : [policy],
  }));
  render(
    <AuthProvider initialUser={{ roles: ["COMPETENT_AUTHORITY"] }}>
      <MemoryRouter>
        <PolicyWorkspacePage />
      </MemoryRouter>
    </AuthProvider>,
  );
  await screen.findByText("DEMO · v2");
  expect(
    screen.getByRole("button", { name: "activate", exact: true }),
  ).toBeDisabled();
  fireEvent.change(
    screen.getByLabelText("Approval reason (competent authority)"),
    { target: { value: "Reviewed demo regression results" } },
  );
  fireEvent.click(screen.getByRole("button", { name: "approve", exact: true }));
  await waitFor(() =>
    expect(fetch).toHaveBeenCalledWith(
      "/api/v1/policy/p1/approve/",
      expect.objectContaining({
        body: JSON.stringify({ reason: "Reviewed demo regression results" }),
      }),
    ),
  );
});

it("role switching ignores the previous account's inaccessible destination", async () => {
  const { AppRoutes } = await import("../routes");
  render(
    <AuthProvider initialUser={{ roles: ["OVERSIGHT_AUDITOR"] }}>
      <MemoryRouter
        initialEntries={[
          { pathname: "/login", state: { from: "/institution" } },
        ]}
      >
        <AppRoutes />
      </MemoryRouter>
    </AuthProvider>,
  );
  expect(
    await screen.findByRole("heading", { name: "Oversight / Audit Workspace" }),
  ).toBeInTheDocument();
  expect(
    screen.queryByRole("heading", { name: "Access Denied" }),
  ).not.toBeInTheDocument();
});
