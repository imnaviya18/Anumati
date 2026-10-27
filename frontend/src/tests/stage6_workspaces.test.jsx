import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { AuthProvider } from "../auth/AuthContext";
import { AppRoutes } from "../routes";

describe("Stage 6 Workspaces, Polling Banner, 6 Reports & Role Guards", () => {
  it("blocks TECHNICAL_ADMIN from accessing Officer Regulatory Workspace (Sheet 07 P5)", () => {
    render(
      <AuthProvider
        initialUser={{ username: "tech_admin", roles: ["TECHNICAL_ADMIN"] }}
      >
        <MemoryRouter initialEntries={["/officer"]}>
          <AppRoutes />
        </MemoryRouter>
      </AuthProvider>,
    );
    expect(
      screen.getByRole("alert", { name: /Access Denied/i }),
    ).toBeInTheDocument();
  });

  it("allows REGIONAL_OFFICER into the empty assigned queue", async () => {
    render(
      <AuthProvider
        initialUser={{ username: "ro_north", roles: ["REGIONAL_OFFICER"] }}
      >
        <MemoryRouter initialEntries={["/officer"]}>
          <AppRoutes />
        </MemoryRouter>
      </AuthProvider>,
    );
    expect(
      screen.getByRole("heading", { name: /Officer \/ Committee Workspace/i }),
    ).toBeInTheDocument();

    await waitFor(() => {
      expect(screen.getByText(/Data as of:/i)).toBeInTheDocument();
    });

    expect(
      await screen.findByText(/No applications match/i),
    ).toBeInTheDocument();
  });

  it("renders exact 6 statutory reports in Oversight Workspace with CSV export link", async () => {
    render(
      <AuthProvider
        initialUser={{ username: "auditor", roles: ["OVERSIGHT_AUDITOR"] }}
      >
        <MemoryRouter initialEntries={["/oversight"]}>
          <AppRoutes />
        </MemoryRouter>
      </AuthProvider>,
    );

    const select = await screen.findByLabelText(/Select Statutory Report/i);
    const options = Array.from(select.querySelectorAll("option")).map(
      (o) => o.value,
    );
    expect(options).toEqual([
      "application_pendency",
      "evc_status",
      "undertaking_compliance",
      "document_validity",
      "overdue_cases",
      "region_wise_processing_performance",
    ]);

    const exportLink = screen.getByRole("link", {
      name: /Export application_pendency\.csv/i,
    });
    expect(exportLink).toHaveAttribute(
      "href",
      "/api/v1/reporting/reports/application_pendency/?export=csv",
    );
  });
});
