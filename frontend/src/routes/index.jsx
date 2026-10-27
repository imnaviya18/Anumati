import { HomePage } from "../pages/HomePage";
import { LoginPage } from "../pages/LoginPage";
import { Route, Routes } from "react-router-dom";
import { AppLayout } from "../components/AppLayout";
import { InstitutionWorkspacePage } from "../pages/institution/InstitutionWorkspacePage";
import { OfficerWorkspacePage } from "../pages/officer/OfficerWorkspacePage";
import { OversightWorkspacePage } from "../pages/oversight/OversightWorkspacePage";
import { PolicyWorkspacePage } from "../pages/policy/PolicyWorkspacePage";
import { AdminWorkspacePage } from "../pages/admin/AdminWorkspacePage";
import { ProtectedRoute } from "./ProtectedRoute";

export function AppRoutes() {
  return (
    <AppLayout>
      <Routes>
        <Route path="/" element={<HomePage />} />
        <Route path="/login" element={<LoginPage />} />
        <Route
          path="*"
          element={
            <section>
              <h1>Page not found</h1>
              <a href="/">Return home</a>
            </section>
          }
        />
        <Route
          path="/institution"
          element={
            <ProtectedRoute allowedRoles={["INSTITUTION_USER"]}>
              <InstitutionWorkspacePage />
            </ProtectedRoute>
          }
        />
        <Route
          path="/officer"
          element={
            <ProtectedRoute
              allowedRoles={[
                "SCRUTINY_MEMBER",
                "EVC_MEMBER",
                "REGIONAL_OFFICER",
                "BUREAU_OFFICER",
                "COMMITTEE_MEMBER",
                "COMPETENT_AUTHORITY",
              ]}
            >
              <OfficerWorkspacePage />
            </ProtectedRoute>
          }
        />
        <Route
          path="/oversight"
          element={
            <ProtectedRoute
              allowedRoles={[
                "OVERSIGHT_AUDITOR",
                "COMPETENT_AUTHORITY",
                "REGIONAL_OFFICER",
                "BUREAU_OFFICER",
              ]}
            >
              <OversightWorkspacePage />
            </ProtectedRoute>
          }
        />
        <Route
          path="/policy"
          element={
            <ProtectedRoute
              allowedRoles={["POLICY_ADMIN", "COMPETENT_AUTHORITY"]}
            >
              <PolicyWorkspacePage />
            </ProtectedRoute>
          }
        />
        <Route
          path="/admin"
          element={
            <ProtectedRoute allowedRoles={["TECHNICAL_ADMIN"]}>
              <AdminWorkspacePage />
            </ProtectedRoute>
          }
        />
      </Routes>
    </AppLayout>
  );
}
