import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { AuthProvider } from "../auth/AuthContext";
import { AppRoutes } from "../routes";
describe("Authenticated workspace routing", () => {
  for (const [path, role, heading] of [
    ["institution", "INSTITUTION_USER", "Institution Workspace"],
    ["officer", "REGIONAL_OFFICER", "Officer / Committee Workspace"],
    ["oversight", "OVERSIGHT_AUDITOR", "Oversight / Audit Workspace"],
    ["policy", "POLICY_ADMIN", "Policy Administration Workspace"],
  ]) {
    it(`opens ${path} for its role`, () => {
      render(
        <AuthProvider initialUser={{ username: "test", roles: [role] }}>
          <MemoryRouter initialEntries={[`/${path}`]}>
            <AppRoutes />
          </MemoryRouter>
        </AuthProvider>,
      );
      expect(
        screen.getByRole("heading", { name: heading }),
      ).toBeInTheDocument();
    });
  }
  it("redirects unauthenticated users to login", () => {
    render(
      <AuthProvider initialUser={null}>
        <MemoryRouter initialEntries={["/officer"]}>
          <AppRoutes />
        </MemoryRouter>
      </AuthProvider>,
    );
    expect(
      screen.getByRole("heading", { name: "Sign in to Anumati" }),
    ).toBeInTheDocument();
    expect(screen.queryByText("Assigned case queue")).not.toBeInTheDocument();
  });
});
