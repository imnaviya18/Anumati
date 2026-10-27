import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { expect, it } from "vitest";
import { AuthProvider } from "../auth/AuthContext";
import { AppRoutes } from "../routes";
function mount(path, user) {
  render(
    <AuthProvider initialUser={user}>
      <MemoryRouter initialEntries={[path]}>
        <AppRoutes />
      </MemoryRouter>
    </AuthProvider>,
  );
}
it("submits credentials with a CSRF bootstrap and reads server roles", async () => {
  const requests = [];
  fetch.mockImplementation(async (path, opts) => {
    requests.push([path, opts]);
    return {
      ok: true,
      json: async () =>
        path.endsWith("login/")
          ? { username: "auditor", scope: { roles: ["OVERSIGHT_AUDITOR"] } }
          : path.includes("/cases/")
            ? { results: [], count: 0 }
            : { total_visible_cases: 0 },
    };
  });
  mount("/login", null);
  fireEvent.change(screen.getByLabelText("Username"), {
    target: { value: "auditor" },
  });
  fireEvent.change(screen.getByLabelText("Password"), {
    target: { value: "secret" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
  expect(
    await screen.findByRole("heading", { name: "Oversight / Audit Workspace" }),
  ).toBeInTheDocument();
  expect(requests[0][0]).toBe("/api/v1/auth/csrf/");
  expect(JSON.parse(requests[1][1].body)).toEqual({
    username: "auditor",
    password: "secret",
  });
});
it("persists institution intake instead of displaying a simulated success", async () => {
  fetch.mockImplementation(async (path, options) => ({
    ok: true,
    json: async () =>
      ["/documents/", "/compliance/", "/evc/", "/notifications/"].some((part) =>
        path.includes(part),
      )
        ? []
        : options?.method === "POST"
          ? { case_number: "CASE-001", status: "POLICY_REVIEW_REQUIRED" }
          : path.includes("/cases/")
            ? { results: [], count: 0 }
            : { total_visible_cases: 0 },
  }));
  mount("/institution", {
    username: "institution",
    scope: { roles: ["INSTITUTION_USER"], institution_ids: ["inst-1"] },
  });
  fireEvent.change(await screen.findByLabelText("Source Application ID"), {
    target: { value: "SRC-001" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Submit Intake" }));
  expect(await screen.findByText(/Saved CASE-001/)).toBeInTheDocument();
  expect(fetch).toHaveBeenCalledWith(
    "/api/v1/cases/",
    expect.objectContaining({
      method: "POST",
      body: expect.stringContaining('"institution_id":"inst-1"'),
    }),
  );
});
it("shows server failures without inventing zero-count dashboard data", async () => {
  fetch.mockResolvedValue({
    ok: false,
    status: 503,
    json: async () => ({ detail: "Service unavailable" }),
  });
  mount("/oversight", { roles: ["OVERSIGHT_AUDITOR"] });
  await waitFor(() =>
    expect(screen.getAllByRole("alert")[0]).toHaveTextContent(
      "Service unavailable",
    ),
  );
  expect(screen.queryByText(/Total Cases in Scope/)).not.toBeInTheDocument();
});
