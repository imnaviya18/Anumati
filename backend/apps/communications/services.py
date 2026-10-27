"""Services for deterministic electronic case summaries and standardised communications (Sheet 02 C1/C3, PS Section A.5, A.6)."""
from __future__ import annotations

from string import Formatter
from typing import Any
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from apps.access.models import RoleCode
from apps.access.services import (
    assert_not_technical_admin_only_for_regulatory_action,
    check_case_read_access,
    resolve_actor_scope,
)
from apps.audit.services import record_audit_event
from apps.cases.models import ApplicationCase
from apps.communications.models import CommunicationTemplate, RenderedCommunication
from apps.decisions.models import CaseDecision
from apps.outbox.models import OutboxEvent


class _StrictTemplateDict(dict):
    def __missing__(self, key: str) -> str:
        raise ValidationError(f"Missing required template field '{key}'.")


def _render_safe_format(template_str: str, context: dict[str, Any]) -> str:
    """Deterministically format a string template using only top-level field substitutions (no arbitrary eval)."""
    formatter = Formatter()
    for _, field_name, _, _ in formatter.parse(template_str):
        if field_name is not None and ("." in field_name or "[" in field_name):
            raise ValidationError("Attribute or index traversal is forbidden in templates.")
    return template_str.format_map(_StrictTemplateDict(context))


def build_case_template_context(case: ApplicationCase) -> dict[str, Any]:
    """Extract structured facts for a case to feed deterministic summary or communication templates."""
    stage_instances = [
        f"{si.stage_type}#{si.iteration_number}:{si.status}"
        for si in case.stage_instances.all().order_by("sequence_number", "iteration_number")
    ]
    evc_coords = list(case.evc_coordinations.all().order_by("-created_at"))
    latest_evc = evc_coords[0] if evc_coords else None
    obligations = list(case.obligations.all().order_by("created_at"))
    decisions = list(case.decisions.all().order_by("-created_at"))
    latest_decision = decisions[0] if decisions else None
    policy_ref = (
        f"{case.pinned_policy_version.policy_code}@v{case.pinned_policy_version.version_number}"
        if case.pinned_policy_version
        else "UNPINNED"
    )

    return {
        "case_number": case.case_number,
        "source_id": case.source_id,
        "institution_code": case.institution.permanent_id,
        "institution_name": case.institution.name,
        "region_code": case.region.code,
        "academic_cycle": case.academic_cycle,
        "application_category": case.application_category,
        "selected_route_code": case.selected_route_code or "UNASSIGNED",
        "prescribed_stages": ", ".join(case.prescribed_stages or []),
        "status": case.status,
        "current_stage_type": case.current_stage_type or "NONE",
        "case_version": str(case.version),
        "policy_code": policy_ref,
        "stage_history_summary": "; ".join(stage_instances) if stage_instances else "None",
        "evc_status": latest_evc.status if latest_evc else "NOT_APPLICABLE",
        "evc_report_summary": latest_evc.report_summary if latest_evc and latest_evc.report_summary else "N/A",
        "obligations_count": str(len(obligations)),
        "latest_decision_outcome": latest_decision.outcome if latest_decision else "PENDING",
        "latest_decision_reasons": latest_decision.reasons if latest_decision else "N/A",
    }


@transaction.atomic
def render_electronic_case_summary(
    *,
    actor: Any,
    case: ApplicationCase,
    template: CommunicationTemplate | None = None,
) -> RenderedCommunication:
    """Generate a deterministic electronic case summary from structured case data through a fixed, versioned template (PS-A.5, Sheet 01 Block 07, Sheet 02 C1).

    Never alters case state, stage, version, or regulatory decisions.
    """
    scope = check_case_read_access(actor, case)

    if template is None:
        now = timezone.now()
        template = (
            CommunicationTemplate.objects.filter(
                category=CommunicationTemplate.TemplateCategory.CASE_SUMMARY,
                is_active=True,
                effective_from__lte=now,
            )
            .order_by("-version_number")
            .first()
        )
        if template is None:
            template = CommunicationTemplate.objects.create(
                template_code="DEFAULT_CASE_SUMMARY",
                version_number=1,
                category=CommunicationTemplate.TemplateCategory.CASE_SUMMARY,
                policy_version=case.pinned_policy_version,
                subject_template="Electronic Case Summary: {case_number} ({institution_code})",
                body_template=(
                    "Case: {case_number} | Institution: {institution_name} ({institution_code}) | "
                    "Region: {region_code} | Cycle: {academic_cycle} | Route: {selected_route_code} | "
                    "Status: {status} | Current Stage: {current_stage_type} | Policy: {policy_code} | "
                    "Stages: {stage_history_summary} | EVC Status: {evc_status} | "
                    "EVC Summary: {evc_report_summary} | Obligations: {obligations_count} | "
                    "Decision Outcome: {latest_decision_outcome}"
                ),
                required_fields=[
                    "case_number",
                    "institution_code",
                    "institution_name",
                    "status",
                    "selected_route_code",
                ],
            )

    if template.category != CommunicationTemplate.TemplateCategory.CASE_SUMMARY:
        raise ValidationError("Template must have category CASE_SUMMARY.")

    context = build_case_template_context(case)
    for req_field in template.required_fields or []:
        if req_field not in context:
            raise ValidationError(f"Case context missing required field '{req_field}'.")

    rendered_subject = _render_safe_format(template.subject_template, context)
    rendered_body = _render_safe_format(template.body_template, context)

    record = RenderedCommunication.objects.create(
        case=case,
        template=template,
        issued_by=actor,
        rendered_subject=rendered_subject,
        rendered_body=rendered_body,
        context_snapshot=context,
        case_version_at_render=case.version,
    )

    record_audit_event(
        actor=actor,
        actor_role=",".join(sorted(scope.roles)),
        actor_scope=scope.to_audit_dict(),
        action="ELECTRONIC_CASE_SUMMARY_GENERATED",
        target_type="RenderedCommunication",
        target_id=str(record.id),
        case=case,
        institution=case.institution,
        region=case.region,
        inputs_snapshot={
            "template_code": template.template_code,
            "template_version": template.version_number,
            "case_version_at_render": case.version,
        },
    )
    return record


@transaction.atomic
def issue_standardised_communication(
    *,
    actor: Any,
    case: ApplicationCase,
    template: CommunicationTemplate,
    decision: CaseDecision | None = None,
    extra_fields: dict[str, str] | None = None,
) -> RenderedCommunication:
    """Issue a standardised regulatory communication (LoA, EoA, LoD, LoR/Speaking Order, Deficiency/EVC/Renewal notice) from a versioned template (PS-A.6, Sheet 02 C3)."""
    scope = resolve_actor_scope(actor)
    assert_not_technical_admin_only_for_regulatory_action(scope, "issue_standardised_communication")
    check_case_read_access(actor, case)

    if RoleCode.INSTITUTION_USER in scope.roles and len(scope.roles) == 1:
        raise PermissionDenied("Institution users cannot issue official regulatory communications.")

    if not template.is_active:
        raise ValidationError("Cannot issue communication from an inactive template.")

    context = build_case_template_context(case)
    if extra_fields:
        for k, v in extra_fields.items():
            context[str(k)] = str(v)

    for req_field in template.required_fields or []:
        if req_field not in context or context[req_field] in {"", None}:
            raise ValidationError(f"Missing required field '{req_field}' for template '{template.template_code}'.")

    rendered_subject = _render_safe_format(template.subject_template, context)
    rendered_body = _render_safe_format(template.body_template, context)

    record = RenderedCommunication.objects.create(
        case=case,
        template=template,
        decision=decision,
        issued_by=actor,
        rendered_subject=rendered_subject,
        rendered_body=rendered_body,
        context_snapshot=context,
        case_version_at_render=case.version,
    )

    now = timezone.now()
    OutboxEvent.objects.create(
        logical_id=f"comm-issued:{record.id}:{now.strftime('%Y%m%d%H%M%S%f')}",
        event_type="COMMUNICATION_DISPATCH",
        case=case,
        case_version=case.version,
        next_attempt_at=now,
        payload={
            "rendered_communication_id": str(record.id),
            "template_code": template.template_code,
            "category": template.category,
            "subject": rendered_subject,
        },
    )

    record_audit_event(
        actor=actor,
        actor_role=",".join(sorted(scope.roles)),
        actor_scope=scope.to_audit_dict(),
        action="STANDARDISED_COMMUNICATION_ISSUED",
        target_type="RenderedCommunication",
        target_id=str(record.id),
        case=case,
        institution=case.institution,
        region=case.region,
        inputs_snapshot={
            "template_code": template.template_code,
            "version_number": template.version_number,
            "category": template.category,
            "decision_id": str(decision.id) if decision else None,
        },
    )
    return record
