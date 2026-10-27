"""Read-only action discovery; command services still recheck under lock."""
from django.core.exceptions import PermissionDenied
from apps.access.services import resolve_actor_scope, check_stage_execution_access


def available_actions(user, case):
    scope = resolve_actor_scope(user)
    actions = []
    if case.status in {"POLICY_REVIEW_REQUIRED", "SUBMITTED"}:
        actions.append({"code":"RESOLVE_ROUTE","label":"Retry policy routing"})
    if "INSTITUTION_USER" in scope.roles and case.institution_id in scope.institution_ids and case.status == "DEFICIENCY_PENDING":
        actions.append({"code":"RESPOND","label":"Respond to deficiency"})
    if case.status == "IN_STAGE_PROCESSING":
        stage = case.stage_instances.filter(stage_type=case.current_stage_type,status__in=["PENDING","IN_PROGRESS"]).order_by('-iteration_number').first()
        if stage:
            try:
                check_stage_execution_access(user,case,stage,"COMPLETE_STAGE")
            except PermissionDenied:
                pass
            else:
                if stage.stage_type != "EVC":
                    actions.extend([{"code":"COMPLETE_STAGE","label":"Complete review","stage_id":str(stage.id)}, {"code":"RETURN_FOR_DEFICIENCY","label":"Request clarification","stage_id":str(stage.id)}])
    if "COMPETENT_AUTHORITY" in scope.roles and case.status == "READY_FOR_DISPOSITION":
        for outcome in ["GRANT_EOA","GRANT_LOA","ISSUE_LOD","REJECT_LOR","REFER_BACK"]:
            if outcome in scope.delegated_powers:
                actions.append({"code":"DECIDE_"+outcome,"label":outcome.replace('_',' ').title(),"delegated_power_ref":outcome})
    return actions
