import { useAuth } from "../../auth/AuthContext";
import { OperationalActions } from "../../components/OperationalActions";
import { Notifications } from "../../components/Notifications";
import { CaseWorkbench } from "../../components/CaseWorkbench";
export function OfficerWorkspacePage() {
  const { user } = useAuth();
  return (
    <section>
      <h1>Officer / Committee Workspace</h1>
      <p>
        Review assigned applications, record findings and execute authorised
        actions.
      </p>
      <CaseWorkbench />
      <Notifications />
      {user?.roles?.some((r) =>
        ["REGIONAL_OFFICER", "BUREAU_OFFICER", "COMPETENT_AUTHORITY"].includes(
          r,
        ),
      ) && <OperationalActions />}
    </section>
  );
}
