import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { MemoryRouter } from "react-router-dom";
import { AuthProvider } from "../auth/AuthContext";
import { CaseWorkbench } from "../components/CaseWorkbench";
import { OversightDetails } from "../components/OversightDetails";
import { SyncExceptions } from "../components/SyncExceptions";

describe("Frontend Architectural Edge Cases", () => {
  it("displays server error alert and does not crash when case API returns 500", async () => {
    fetch.mockImplementation(async (path) => {
      if (path.includes("/api/v1/cases/")) {
        return {
          ok: false,
          status: 500,
          statusText: "Internal Server Error",
          text: async () => "Database unavailable",
          json: async () => ({ detail: "Database cluster failover in progress" }),
        };
      }
      return { ok: true, json: async () => ({}) };
    });

    render(
      <AuthProvider initialUser={{ roles: ["REGIONAL_OFFICER"] }}>
        <MemoryRouter>
          <CaseWorkbench />
        </MemoryRouter>
      </AuthProvider>
    );

    // Should render the failure alert gracefully rather than crashing
    expect(await screen.findByRole("alert")).toBeInTheDocument();
  });

  it("renders oversight metrics cleanly when datasets are empty or null", async () => {
    fetch.mockImplementation(async () => ({
      ok: true,
      json: async () => ({ escalations: [] }),
    }));

    render(
      <MemoryRouter>
        <OversightDetails
          snapshot={{
            status_by_region: [],
            status_by_bureau: [],
            workload_by_officer: [],
            workload_by_committee: [],
            ageing: [],
            bottlenecks: [],
            unassigned_stages: 0,
          }}
          region=""
          bureau=""
        />
      </MemoryRouter>
    );

    expect(screen.getByText("Regional pendency")).toBeInTheDocument();
    expect(screen.getByText("Bureau pendency")).toBeInTheDocument();
    expect(screen.getByText("Stages awaiting assignment: 0")).toBeInTheDocument();
    const emptyNotices = screen.getAllByText("No records in this scope.");
    expect(emptyNotices.length).toBeGreaterThan(0);
  });

  it("read-only case workbench suppresses mutation action buttons", async () => {
    const mockCase = {
      id: "case-edge-1",
      case_number: "CASE-READONLY-1",
      status: "READY_FOR_DISPOSITION",
      version: 1,
      institution_name: "Test Inst",
      academic_cycle: "2026-27",
      application_category: "EOA",
    };

    fetch.mockImplementation(async (path) => ({
      ok: true,
      json: async () =>
        path.includes("/cases/case-edge-1/")
          ? mockCase
          : { results: [mockCase], count: 1 },
    }));

    render(
      <AuthProvider initialUser={{ roles: ["OVERSIGHT_AUDITOR"] }}>
        <MemoryRouter initialEntries={["/?case=case-edge-1"]}>
          <CaseWorkbench readOnly />
        </MemoryRouter>
      </AuthProvider>
    );

    await screen.findByRole("heading", { name: "CASE-READONLY-1" });
    // In read-only mode, mutation action buttons are omitted
    expect(screen.queryByRole("button", { name: "Execute Guarded Command" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Assign Reviewer" })).not.toBeInTheDocument();
  });

  it("sync exceptions renders empty queue notice when no conflicts exist", async () => {
    fetch.mockImplementation(async () => ({
      ok: true,
      json: async () => ({ results: [], count: 0 }),
    }));

    render(
      <MemoryRouter>
        <SyncExceptions />
      </MemoryRouter>
    );

    expect(await screen.findByText("No open sync exceptions.")).toBeInTheDocument();
  });
});
