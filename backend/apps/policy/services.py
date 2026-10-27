"""Policy governance services: draft -> validate -> dry-run -> approve -> activate & migration (Sheet 01 Block 05, Sheet 04 J1-J3, Sheet 07 P3-P4)."""
from __future__ import annotations

from typing import Any
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import connection, transaction
from django.conf import settings
from django.utils import timezone

from apps.access.models import RoleCode
from apps.access.services import ActorScopeSnapshot, resolve_actor_scope
from apps.audit.services import record_audit_event
from apps.cases.models import ApplicationCase, CaseStatus, StageType
from apps.policy.models import PolicyMigrationRecord, PolicyVersion
from apps.routing.services import evaluate_policy_route


VALID_STAGE_VALUES = {choice[0] for choice in StageType.choices}


def _assert_policy_governor(actor: Any) -> ActorScopeSnapshot:
    scope = resolve_actor_scope(actor)
    if RoleCode.TECHNICAL_ADMIN in scope.roles and not (
        scope.roles & {RoleCode.POLICY_ADMIN, RoleCode.COMPETENT_AUTHORITY}
    ):
        raise PermissionDenied("TECHNICAL_ADMIN holds no policy governance authority (Sheet 07 P5).")
    if not (scope.roles & {RoleCode.POLICY_ADMIN, RoleCode.COMPETENT_AUTHORITY}):
        raise PermissionDenied("Actor is not authorised for policy governance.")
    return scope


@transaction.atomic
def draft_policy_version(
    *,
    actor: Any,
    policy_code: str,
    version_number: int,
    academic_cycle: str,
    calendar_version: str = "CAL-v1",
    route_rules: list[dict[str, Any]] | None = None,
    stage_timelines: dict[str, Any] | None = None,
    evc_rules: dict[str, Any] | None = None,
    undertaking_rules: list[dict[str, Any]] | None = None,
    document_validity_rules: dict[str, Any] | None = None,
    escalation_hierarchies: dict[str, Any] | None = None,
    calendar_holidays: list[str] | None = None,
    regression_cases: list[dict[str, Any]] | None = None,
    effective_from: Any = None,
    effective_until: Any = None,
    is_demonstration: bool = True,
    provenance: dict | None = None,
    document_requirements: dict | None = None,
    committee_permissions: dict | None = None,
    exception_rules: dict | None = None,
    deadline_triggers: dict | None = None,
) -> PolicyVersion:
    """Create a DRAFT policy version (Sheet 04 J1)."""
    scope = _assert_policy_governor(actor)
    if not policy_code.strip() or not academic_cycle.strip() or version_number < 1:
        raise ValidationError("Policy code, academic cycle and a positive version are required.")
    if effective_until and effective_until <= (effective_from or timezone.now()):
        raise ValidationError("Effective end must be after effective start.")
    policy = PolicyVersion.objects.create(
        policy_code=policy_code,
        version_number=version_number,
        academic_cycle=academic_cycle,
        state=PolicyVersion.PolicyState.DRAFT,
        effective_from=effective_from or timezone.now(),
        effective_until=effective_until,
        calendar_version=calendar_version,
        route_rules=route_rules or [],
        stage_timelines=stage_timelines or {},
        evc_rules=evc_rules or {},
        undertaking_rules=undertaking_rules or [],
        document_validity_rules=document_validity_rules or {},
        escalation_hierarchies=escalation_hierarchies or {},
        calendar_holidays=calendar_holidays or [],
        regression_cases=regression_cases or [],
        is_demonstration=is_demonstration,
        provenance=provenance or {},
        document_requirements=document_requirements or {},
        committee_permissions=committee_permissions or {},
        exception_rules=exception_rules or {},
        deadline_triggers=deadline_triggers or {},
        created_by=actor,
    )
    record_audit_event(
        actor=actor,
        actor_role=",".join(sorted(scope.roles)),
        actor_scope=scope.to_audit_dict(),
        action="POLICY_DRAFT_CREATED",
        target_type="PolicyVersion",
        target_id=str(policy.id),
        policy_version_ref=f"{policy.policy_code}@v{policy.version_number}",
        inputs_snapshot={
            "policy_code": policy_code,
            "version_number": version_number,
            "academic_cycle": academic_cycle,
        },
    )
    return policy


@transaction.atomic
def validate_policy_version(
    *,
    actor: Any,
    policy: PolicyVersion,
) -> PolicyVersion:
    """Validate policy version for missing/conflicting routes, invalid stage references, unintended loops, and affected cases (Sheet 04 J2, Sheet 07 P3)."""
    scope = _assert_policy_governor(actor)
    PolicyVersion.objects.select_for_update().get(pk=policy.pk)
    policy.refresh_from_db()
    if policy.state not in {PolicyVersion.PolicyState.DRAFT, PolicyVersion.PolicyState.VALIDATED}:
        raise ValidationError("Only draft or validated policies can be validated; activated history is immutable.")
    if not isinstance(policy.route_rules, list) or any(not isinstance(rule, dict) for rule in policy.route_rules):
        raise ValidationError("Route rules must be a list of objects.")
    errors: list[str] = []
    warnings: list[str] = []

    if not policy.route_rules:
        errors.append("route_rules must not be empty.")

    seen_condition_signatures: set[str] = set()
    for idx, rule in enumerate(policy.route_rules or []):
        route_code = rule.get("route_code")
        conditions = rule.get("conditions")
        stages = rule.get("stages") or rule.get("prescribed_stages")
        if not route_code:
            errors.append(f"Rule index {idx} missing route_code.")
        if not isinstance(conditions, dict) or not conditions:
            errors.append(f"Route '{route_code}' must specify non-empty conditions.")
        else:
            sig = repr(sorted((k, repr(v)) for k, v in conditions.items()))
            if sig in seen_condition_signatures:
                errors.append(f"Conflicting duplicate conditions in route '{route_code}'.")
            seen_condition_signatures.add(sig)

        if not isinstance(stages, list) or not stages:
            errors.append(f"Route '{route_code}' must specify a non-empty ordered stage list.")
        else:
            if len(stages) != len(set(stages)):
                errors.append(f"Unintended stage loop/duplicate in route '{route_code}': {stages}")
            for stage in stages:
                if stage not in VALID_STAGE_VALUES:
                    errors.append(f"Route '{route_code}' references invalid stage '{stage}'.")

    affected_open_cases_count = ApplicationCase.objects.filter(
        academic_cycle=policy.academic_cycle,
    ).exclude(
        status=CaseStatus.CLOSED,
    ).count()

    report = {
        "valid": len(errors) == 0,
        "errors": errors,
        "warnings": warnings,
        "affected_open_cases_in_cycle": affected_open_cases_count,
        "validated_at": timezone.now().isoformat(),
    }
    policy.validation_report = report
    if errors:
        policy.save(update_fields=["validation_report", "updated_at"])
        raise ValidationError(f"Policy validation failed: {'; '.join(errors)}")

    policy.state = PolicyVersion.PolicyState.VALIDATED
    policy.save(update_fields=["state", "validation_report", "updated_at"])
    record_audit_event(
        actor=actor,
        actor_role=",".join(sorted(scope.roles)),
        actor_scope=scope.to_audit_dict(),
        action="POLICY_VALIDATED",
        target_type="PolicyVersion",
        target_id=str(policy.id),
        policy_version_ref=f"{policy.policy_code}@v{policy.version_number}",
        inputs_snapshot=report,
    )
    return policy


@transaction.atomic
def run_policy_dry_run(
    *,
    actor: Any,
    policy: PolicyVersion,
) -> PolicyVersion:
    """Execute deterministic dry-run against regression cases to prove reproducibility and no default-to-approval (Sheet 04 J2, Sheet 07 P3)."""
    scope = _assert_policy_governor(actor)
    PolicyVersion.objects.select_for_update().get(pk=policy.pk)
    policy.refresh_from_db()
    if policy.state not in {PolicyVersion.PolicyState.VALIDATED, PolicyVersion.PolicyState.DRY_RUN_PASSED}:
        raise ValidationError("Policy must be VALIDATED before running dry-run.")

    regression_cases = policy.regression_cases or []
    if not isinstance(regression_cases, list) or not regression_cases or any(not isinstance(item, dict) for item in regression_cases):
        raise ValidationError("A non-empty list of regression cases is required before activation.")
    results: list[dict[str, Any]] = []
    failures: list[str] = []

    for idx, reg in enumerate(regression_cases):
        case_name = reg.get("name", f"case_{idx}")
        app_cat = reg.get("application_category", "")
        inst_cat = reg.get("institution_category", "")
        is_new = bool(reg.get("is_new_institution", False))
        extra = reg.get("extra_attributes", {})
        expected_route = reg.get("expected_route_code")
        expect_ambiguous_or_missing = bool(reg.get("expect_review_required", False))

        res1 = evaluate_policy_route(
            policy=policy,
            application_category=app_cat,
            institution_category=inst_cat,
            is_new_institution=is_new,
            extra_attributes=extra,
        )
        res2 = evaluate_policy_route(
            policy=policy,
            application_category=app_cat,
            institution_category=inst_cat,
            is_new_institution=is_new,
            extra_attributes=extra,
        )
        if res1 != res2:
            failures.append(f"Regression '{case_name}' produced non-deterministic output.")

        matched_count = res1["matched_count"]
        selected_code = res1["selected_route"]["route_code"] if res1["selected_route"] else None

        if expect_ambiguous_or_missing:
            if matched_count == 1:
                failures.append(
                    f"Regression '{case_name}' expected POLICY_REVIEW_REQUIRED (matched_count != 1) but matched '{selected_code}'."
                )
            else:
                results.append(
                    {
                        "name": case_name,
                        "status": "POLICY_REVIEW_REQUIRED_AS_EXPECTED",
                        "matched_count": matched_count,
                    }
                )
        else:
            if matched_count != 1:
                failures.append(
                    f"Regression '{case_name}' expected single route '{expected_route}', got matched_count={matched_count}."
                )
            elif expected_route and selected_code != expected_route:
                failures.append(
                    f"Regression '{case_name}' expected route '{expected_route}', got '{selected_code}'."
                )
            else:
                results.append({"name": case_name, "status": "MATCHED", "route_code": selected_code})

    dry_run_report = {
        "passed": len(failures) == 0,
        "total_regression_cases": len(regression_cases),
        "results": results,
        "failures": failures,
        "executed_at": timezone.now().isoformat(),
    }
    policy.dry_run_report = dry_run_report
    if failures:
        policy.save(update_fields=["dry_run_report", "updated_at"])
        raise ValidationError(f"Policy dry-run failed: {'; '.join(failures)}")

    policy.state = PolicyVersion.PolicyState.DRY_RUN_PASSED
    policy.save(update_fields=["state", "dry_run_report", "updated_at"])
    record_audit_event(
        actor=actor,
        actor_role=",".join(sorted(scope.roles)),
        actor_scope=scope.to_audit_dict(),
        action="POLICY_DRY_RUN_PASSED",
        target_type="PolicyVersion",
        target_id=str(policy.id),
        policy_version_ref=f"{policy.policy_code}@v{policy.version_number}",
        inputs_snapshot=dry_run_report,
    )
    return policy


@transaction.atomic
def approve_and_activate_policy_version(
    *,
    actor: Any,
    policy: PolicyVersion,
) -> PolicyVersion:
    """Approve and activate a dry-run-verified policy version without retroactively changing pinned open cases (Sheet 04 J3, Sheet 07 P4)."""
    scope = _assert_policy_governor(actor)
    if connection.vendor == "postgresql":
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_xact_lock(%s)", [26262005])
    PolicyVersion.objects.select_for_update().get(pk=policy.pk)
    policy.refresh_from_db()
    if policy.is_demonstration:
        if not settings.ALLOW_DEMONSTRATION_POLICIES:
            raise ValidationError("Demonstration policies cannot activate in production.")
    else:
        if not settings.ALLOW_AUTHORITATIVE_POLICY_ACTIVATION:
            raise ValidationError("Authoritative policy activation is blocked until the deployment owner enables the approved configuration.")
        if RoleCode.COMPETENT_AUTHORITY not in scope.roles:
            raise PermissionDenied("Authoritative activation requires the approving competent authority.")
        provenance = policy.provenance or {}
        if provenance.get("pending_validation") or not provenance.get("owner_approval_reference"):
            raise ValidationError("Production policy remains blocked pending owner validation and approval reference.")
        register = provenance.get("rule_register") or {}
        for group in ("route_rules", "stage_timelines", "evc_rules", "undertaking_rules", "document_validity_rules", "escalation_hierarchies", "calendar_holidays", "document_requirements", "committee_permissions", "exception_rules", "deadline_triggers"):
            rules = getattr(policy, group)
            keys = range(len(rules)) if isinstance(rules, list) else rules.keys()
            for key in keys:
                entry = register.get(f"{group}.{key}", {})
                if not all(entry.get(field) for field in ("source", "effective_from", "version", "approving_authority")):
                    raise ValidationError(f"Missing production rule provenance: {group}.{key}.")
        if not policy.effective_until:
            raise ValidationError("An authoritative policy needs an explicit effective end date.")
    if policy.state != PolicyVersion.PolicyState.APPROVED or policy.approved_by_id is None:
        raise ValidationError("Explicit competent-authority approval is required before activation.")

    PolicyVersion.objects.filter(
        policy_code=policy.policy_code,
        state=PolicyVersion.PolicyState.ACTIVE,
    ).exclude(id=policy.id).update(
        state=PolicyVersion.PolicyState.RETIRED,
        effective_until=timezone.now(),
    )

    policy.state = PolicyVersion.PolicyState.ACTIVE
    if policy.approved_by_id is None:
        policy.approved_by = actor
    policy.activated_at = timezone.now()
    policy.save(update_fields=["state", "approved_by", "activated_at", "updated_at"])

    record_audit_event(
        actor=actor,
        actor_role=",".join(sorted(scope.roles)),
        actor_scope=scope.to_audit_dict(),
        action="POLICY_ACTIVATED",
        target_type="PolicyVersion",
        target_id=str(policy.id),
        policy_version_ref=f"{policy.policy_code}@v{policy.version_number}",
        inputs_snapshot={
            "policy_code": policy.policy_code,
            "version_number": policy.version_number,
            "state": policy.state,
        },
    )
    return policy


@transaction.atomic
def migrate_cases_to_policy_version(
    *,
    actor: Any,
    source_policy: PolicyVersion,
    target_policy: PolicyVersion,
    case_ids: list[str],
    reason: str,
) -> PolicyMigrationRecord:
    """Explicitly migrate selected open cases to a new ACTIVE policy version with recorded scope, reason, authorisation, and audit (Sheet 04 J3, Sheet 07 P4)."""
    scope = _assert_policy_governor(actor)
    if not reason.strip():
        raise ValidationError("Explicit migration reason is mandatory.")
    if target_policy.state != PolicyVersion.PolicyState.ACTIVE:
        raise ValidationError("Target policy version must be ACTIVE.")

    cases = list(
        ApplicationCase.objects.select_for_update()
        .filter(
            id__in=case_ids,
            pinned_policy_version=source_policy,
        )
        .exclude(status=CaseStatus.CLOSED)
    )
    if len(cases) != len(set(str(cid) for cid in case_ids)):
        raise ValidationError("All specified cases must be open and currently pinned to source_policy.")

    if not case_ids:
        raise ValidationError("Select at least one case for migration.")
    for case in cases:
        if case.academic_cycle != target_policy.academic_cycle:
            raise ValidationError("Policy migration cannot cross academic cycles.")
        route = evaluate_policy_route(policy=target_policy, application_category=case.application_category, institution_category=case.institution.category, is_new_institution=case.institution.is_new_institution, extra_attributes=case.input_snapshot)
        selected = route.get("selected_route") or {}
        # History cannot be rewritten by simply changing the policy foreign key.
        if route.get("matched_count") != 1 or selected.get("stages") != case.prescribed_stages:
            raise ValidationError("Target route differs from the current stage plan; an explicit reviewed route migration is required.")

    migrated_ids: list[str] = []
    for case in cases:
        old_ver = case.version
        old_policy_ref = f"{source_policy.policy_code}@v{source_policy.version_number}"
        new_policy_ref = f"{target_policy.policy_code}@v{target_policy.version_number}"
        case.pinned_policy_version = target_policy
        case.version += 1
        case.save(update_fields=["pinned_policy_version", "version", "updated_at"])
        migrated_ids.append(str(case.id))
        record_audit_event(
            actor=actor,
            actor_role=",".join(sorted(scope.roles)),
            actor_scope=scope.to_audit_dict(),
            action="CASE_POLICY_MIGRATED",
            target_type="ApplicationCase",
            target_id=str(case.id),
            case=case,
            institution=case.institution,
            region=case.region,
            policy_version_ref=new_policy_ref,
            old_version=old_ver,
            new_version=case.version,
            reason=reason,
            inputs_snapshot={
                "from_policy": old_policy_ref,
                "to_policy": new_policy_ref,
            },
        )

    return PolicyMigrationRecord.objects.create(
        source_policy=source_policy,
        target_policy=target_policy,
        authorised_by=actor,
        scope_filter={"case_ids": migrated_ids},
        reason=reason,
        affected_case_ids=migrated_ids,
    )


@transaction.atomic
def edit_draft_policy(*, actor, policy_id, changes, reason):
    scope = _assert_policy_governor(actor)
    if not reason.strip():
        raise ValidationError("Draft edits require a reason.")
    policy = PolicyVersion.objects.select_for_update().get(pk=policy_id)
    if policy.state not in {PolicyVersion.PolicyState.DRAFT, PolicyVersion.PolicyState.VALIDATED, PolicyVersion.PolicyState.DRY_RUN_PASSED}:
        raise ValidationError("Active, approved or retired policies cannot be edited. Create a new version.")
    allowed = {"route_rules":list,"stage_timelines":dict,"evc_rules":dict,"undertaking_rules":list,"document_validity_rules":dict,"escalation_hierarchies":dict,"calendar_holidays":list,"regression_cases":list,"provenance":dict,"document_requirements":dict,"committee_permissions":dict,"exception_rules":dict,"deadline_triggers":dict}
    if not isinstance(changes, dict) or set(changes) - set(allowed):
        raise ValidationError("Unknown or invalid draft configuration fields.")
    before = {key:getattr(policy,key) for key in changes}
    for key,value in changes.items():
        if not isinstance(value,allowed[key]):
            raise ValidationError(f"Invalid configuration type for {key}.")
        setattr(policy,key,value)
    policy.state = PolicyVersion.PolicyState.DRAFT
    policy.validation_report = {}
    policy.dry_run_report = {}
    policy.save()
    record_audit_event(actor=actor,actor_role=','.join(sorted(scope.roles)),actor_scope=scope.to_audit_dict(),action="POLICY_DRAFT_EDITED",target_type="PolicyVersion",target_id=str(policy.id),reason=reason,inputs_snapshot={"before":before,"after":changes})
    return policy


@transaction.atomic
def approve_policy_version(*, actor, policy, reason):
    scope = _assert_policy_governor(actor)
    if RoleCode.COMPETENT_AUTHORITY not in scope.roles:
        raise PermissionDenied("Policy approval requires competent authority.")
    PolicyVersion.objects.select_for_update().get(pk=policy.pk)
    policy.refresh_from_db()
    if policy.state != PolicyVersion.PolicyState.DRY_RUN_PASSED:
        raise ValidationError("Policy must pass validation and regression dry-run before approval.")
    if not reason.strip():
        raise ValidationError("An approval reason is required.")
    if not policy.is_demonstration and (policy.provenance.get("pending_validation") or not policy.provenance.get("owner_approval_reference")):
        raise ValidationError("Research policy remains pending owner validation and approval reference.")
    policy.state = PolicyVersion.PolicyState.APPROVED
    policy.approved_by = actor
    policy.approved_at = timezone.now()
    policy.approval_reason = reason
    policy.save(update_fields=["state", "approved_by", "approved_at", "approval_reason", "updated_at"])
    record_audit_event(actor=actor,actor_role=','.join(sorted(scope.roles)),actor_scope=scope.to_audit_dict(),action="POLICY_APPROVED",target_type="PolicyVersion",target_id=str(policy.id),reason=reason,inputs_snapshot={"version":policy.version_number,"dry_run":policy.dry_run_report})
    return policy
