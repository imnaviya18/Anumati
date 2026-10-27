"""Policy-driven route evaluation and explicit transition contracts (Sheet 01 Block 02, Sheet 02 A2-C4, Sheet 06 K5, PS Section A)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from django.core.exceptions import ValidationError

from apps.access.models import RoleCode
from apps.cases.models import ApplicationCase, CaseStatus, StageStatus, StageType
from apps.policy.models import PolicyVersion


class TransitionViolationError(ValidationError):
    """Raised when an attempted case or stage transition violates the explicit transition contract (Sheet 02, Sheet 06 K5)."""


@dataclass(frozen=True)
class TransitionRule:
    """Explicit transition contract mapping (source_case_status, action) -> destination_case_status + required actor roles."""

    source_status: str
    action: str
    destination_status: str
    allowed_roles: frozenset[str]
    requires_active_stage: bool = False


# Explicit state machine transition table (Sheet 01 Block 02, Sheet 02 A1-C4, Sheet 06 K5).
# No blanket stage order, no automatic approval, no arbitrary target state.
PERMITTED_CASE_TRANSITIONS: dict[tuple[str, str], TransitionRule] = {
    (CaseStatus.DRAFT, "SUBMIT_APPLICATION"): TransitionRule(
        source_status=CaseStatus.DRAFT,
        action="SUBMIT_APPLICATION",
        destination_status=CaseStatus.SUBMITTED,
        allowed_roles=frozenset({RoleCode.INSTITUTION_USER, RoleCode.BUREAU_OFFICER, RoleCode.REGIONAL_OFFICER}),
    ),
    (CaseStatus.SUBMITTED, "RESOLVE_ROUTE_SUCCESS"): TransitionRule(
        source_status=CaseStatus.SUBMITTED,
        action="RESOLVE_ROUTE_SUCCESS",
        destination_status=CaseStatus.IN_STAGE_PROCESSING,
        allowed_roles=frozenset({RoleCode.INSTITUTION_USER, RoleCode.BUREAU_OFFICER, RoleCode.REGIONAL_OFFICER}),
    ),
    (CaseStatus.SUBMITTED, "RESOLVE_ROUTE_AMBIGUOUS"): TransitionRule(
        source_status=CaseStatus.SUBMITTED,
        action="RESOLVE_ROUTE_AMBIGUOUS",
        destination_status=CaseStatus.POLICY_REVIEW_REQUIRED,
        allowed_roles=frozenset({RoleCode.INSTITUTION_USER, RoleCode.BUREAU_OFFICER, RoleCode.REGIONAL_OFFICER, RoleCode.POLICY_ADMIN}),
    ),
    (CaseStatus.POLICY_REVIEW_REQUIRED, "RESOLVE_ROUTE_SUCCESS"): TransitionRule(
        source_status=CaseStatus.POLICY_REVIEW_REQUIRED,
        action="RESOLVE_ROUTE_SUCCESS",
        destination_status=CaseStatus.IN_STAGE_PROCESSING,
        allowed_roles=frozenset({RoleCode.BUREAU_OFFICER, RoleCode.REGIONAL_OFFICER, RoleCode.POLICY_ADMIN}),
    ),
    (CaseStatus.IN_STAGE_PROCESSING, "RETURN_FOR_DEFICIENCY"): TransitionRule(
        source_status=CaseStatus.IN_STAGE_PROCESSING,
        action="RETURN_FOR_DEFICIENCY",
        destination_status=CaseStatus.DEFICIENCY_PENDING,
        allowed_roles=frozenset(
            {
                RoleCode.SCRUTINY_MEMBER,
                RoleCode.REGIONAL_OFFICER,
                RoleCode.BUREAU_OFFICER,
                RoleCode.COMMITTEE_MEMBER,
            }
        ),
        requires_active_stage=True,
    ),
    (CaseStatus.DEFICIENCY_PENDING, "SUBMIT_DEFICIENCY_RESPONSE"): TransitionRule(
        source_status=CaseStatus.DEFICIENCY_PENDING,
        action="SUBMIT_DEFICIENCY_RESPONSE",
        destination_status=CaseStatus.IN_STAGE_PROCESSING,
        allowed_roles=frozenset({RoleCode.INSTITUTION_USER}),
        requires_active_stage=True,
    ),
    (CaseStatus.IN_STAGE_PROCESSING, "COMPLETE_STAGE_NEXT"): TransitionRule(
        source_status=CaseStatus.IN_STAGE_PROCESSING,
        action="COMPLETE_STAGE_NEXT",
        destination_status=CaseStatus.IN_STAGE_PROCESSING,
        allowed_roles=frozenset(
            {
                RoleCode.SCRUTINY_MEMBER,
                RoleCode.EVC_MEMBER,
                RoleCode.REGIONAL_OFFICER,
                RoleCode.BUREAU_OFFICER,
                RoleCode.COMMITTEE_MEMBER,
            }
        ),
        requires_active_stage=True,
    ),
    (CaseStatus.IN_STAGE_PROCESSING, "COMPLETE_FINAL_STAGE"): TransitionRule(
        source_status=CaseStatus.IN_STAGE_PROCESSING,
        action="COMPLETE_FINAL_STAGE",
        destination_status=CaseStatus.READY_FOR_DISPOSITION,
        allowed_roles=frozenset(
            {
                RoleCode.SCRUTINY_MEMBER,
                RoleCode.EVC_MEMBER,
                RoleCode.REGIONAL_OFFICER,
                RoleCode.BUREAU_OFFICER,
                RoleCode.COMMITTEE_MEMBER,
            }
        ),
        requires_active_stage=True,
    ),
    (CaseStatus.READY_FOR_DISPOSITION, "REFER_BACK_TO_STAGE"): TransitionRule(
        source_status=CaseStatus.READY_FOR_DISPOSITION,
        action="REFER_BACK_TO_STAGE",
        destination_status=CaseStatus.IN_STAGE_PROCESSING,
        allowed_roles=frozenset({RoleCode.COMPETENT_AUTHORITY}),
    ),
    (CaseStatus.READY_FOR_DISPOSITION, "DECIDE_GRANT_LOA"): TransitionRule(
        source_status=CaseStatus.READY_FOR_DISPOSITION,
        action="DECIDE_GRANT_LOA",
        destination_status=CaseStatus.APPROVED_LOA,
        allowed_roles=frozenset({RoleCode.COMPETENT_AUTHORITY}),
    ),
    (CaseStatus.READY_FOR_DISPOSITION, "DECIDE_GRANT_EOA"): TransitionRule(
        source_status=CaseStatus.READY_FOR_DISPOSITION,
        action="DECIDE_GRANT_EOA",
        destination_status=CaseStatus.APPROVED_EOA,
        allowed_roles=frozenset({RoleCode.COMPETENT_AUTHORITY}),
    ),
    (CaseStatus.READY_FOR_DISPOSITION, "DECIDE_ISSUE_LOD"): TransitionRule(
        source_status=CaseStatus.READY_FOR_DISPOSITION,
        action="DECIDE_ISSUE_LOD",
        destination_status=CaseStatus.DEFICIENCY_LETTER_LOD,
        allowed_roles=frozenset({RoleCode.COMPETENT_AUTHORITY}),
    ),
    (CaseStatus.READY_FOR_DISPOSITION, "DECIDE_REJECT_LOR"): TransitionRule(
        source_status=CaseStatus.READY_FOR_DISPOSITION,
        action="DECIDE_REJECT_LOR",
        destination_status=CaseStatus.REJECTED_LOR,
        allowed_roles=frozenset({RoleCode.COMPETENT_AUTHORITY}),
    ),
    (CaseStatus.APPROVED_LOA, "CLOSE_PROCESSING_INSTANCE"): TransitionRule(
        source_status=CaseStatus.APPROVED_LOA,
        action="CLOSE_PROCESSING_INSTANCE",
        destination_status=CaseStatus.CLOSED,
        allowed_roles=frozenset({RoleCode.COMPETENT_AUTHORITY, RoleCode.BUREAU_OFFICER, RoleCode.REGIONAL_OFFICER}),
    ),
    (CaseStatus.APPROVED_EOA, "CLOSE_PROCESSING_INSTANCE"): TransitionRule(
        source_status=CaseStatus.APPROVED_EOA,
        action="CLOSE_PROCESSING_INSTANCE",
        destination_status=CaseStatus.CLOSED,
        allowed_roles=frozenset({RoleCode.COMPETENT_AUTHORITY, RoleCode.BUREAU_OFFICER, RoleCode.REGIONAL_OFFICER}),
    ),
    (CaseStatus.DEFICIENCY_LETTER_LOD, "CLOSE_PROCESSING_INSTANCE"): TransitionRule(
        source_status=CaseStatus.DEFICIENCY_LETTER_LOD,
        action="CLOSE_PROCESSING_INSTANCE",
        destination_status=CaseStatus.CLOSED,
        allowed_roles=frozenset({RoleCode.COMPETENT_AUTHORITY, RoleCode.BUREAU_OFFICER, RoleCode.REGIONAL_OFFICER}),
    ),
    (CaseStatus.REJECTED_LOR, "CLOSE_PROCESSING_INSTANCE"): TransitionRule(
        source_status=CaseStatus.REJECTED_LOR,
        action="CLOSE_PROCESSING_INSTANCE",
        destination_status=CaseStatus.CLOSED,
        allowed_roles=frozenset({RoleCode.COMPETENT_AUTHORITY, RoleCode.BUREAU_OFFICER, RoleCode.REGIONAL_OFFICER}),
    ),
}

# Stage role compatibility map (Sheet 02 B1-B2, APH Annexure-16)
STAGE_EXECUTION_ROLES: dict[str, frozenset[str]] = {
    StageType.SELF_DISCLOSURE_CHECK: frozenset({RoleCode.REGIONAL_OFFICER, RoleCode.BUREAU_OFFICER}),
    StageType.SCRUTINY: frozenset({RoleCode.SCRUTINY_MEMBER, RoleCode.REGIONAL_OFFICER, RoleCode.BUREAU_OFFICER}),
    StageType.RE_SCRUTINY: frozenset({RoleCode.SCRUTINY_MEMBER, RoleCode.REGIONAL_OFFICER, RoleCode.BUREAU_OFFICER}),
    StageType.EVC: frozenset({RoleCode.EVC_MEMBER, RoleCode.REGIONAL_OFFICER}),
    StageType.SHC: frozenset({RoleCode.COMMITTEE_MEMBER, RoleCode.BUREAU_OFFICER}),
    StageType.SAC: frozenset({RoleCode.COMMITTEE_MEMBER, RoleCode.BUREAU_OFFICER}),
    StageType.SCSC: frozenset({RoleCode.COMMITTEE_MEMBER, RoleCode.BUREAU_OFFICER}),
}


def validate_case_transition(
    *,
    case: ApplicationCase,
    action: str,
    actor_roles: frozenset[str],
    active_stage_type: str | None = None,
) -> TransitionRule:
    """Validate that (case.status, action) is permitted for the actor's roles and required stages (Sheet 06 K5)."""
    key = (case.status, action)
    if key not in PERMITTED_CASE_TRANSITIONS:
        raise TransitionViolationError(
            f"Forbidden transition from state '{case.status}' via action '{action}' (Sheet 06 K5)."
        )
    rule = PERMITTED_CASE_TRANSITIONS[key]
    if not (actor_roles & rule.allowed_roles):
        raise TransitionViolationError(
            f"Actor roles {sorted(actor_roles)} are not permitted to execute '{action}' from '{case.status}'."
        )
    if rule.requires_active_stage and active_stage_type and action != "SUBMIT_DEFICIENCY_RESPONSE":
        allowed_for_stage = STAGE_EXECUTION_ROLES.get(active_stage_type, frozenset())
        if not (actor_roles & allowed_for_stage):
            raise TransitionViolationError(
                f"Actor roles {sorted(actor_roles)} cannot execute stage type '{active_stage_type}'."
            )
    if action in {
        "DECIDE_GRANT_LOA",
        "DECIDE_GRANT_EOA",
        "DECIDE_ISSUE_LOD",
        "DECIDE_REJECT_LOR",
    }:
        # Verify all prescribed stages for the case route have been completed (Sheet 02 B3/B4, Sheet 06 K5)
        completed_types = set(
            case.stage_instances.filter(status=StageStatus.COMPLETED).values_list("stage_type", flat=True)
        )
        for req_stage in case.prescribed_stages or []:
            if req_stage not in completed_types:
                raise TransitionViolationError(
                    f"Required prescribed stage '{req_stage}' is not completed; final disposition is forbidden (Sheet 06 K5)."
                )
    return rule


def evaluate_policy_route(
    *,
    policy: PolicyVersion,
    application_category: str,
    institution_category: str,
    is_new_institution: bool,
    extra_attributes: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Deterministic policy route resolution (Sheet 02 A2, Sheet 07 P3).

    Evaluates declarative route_rules in PolicyVersion.
    If zero or more than one route matches, returns matched_count != 1 so the caller transitions
    to POLICY_REVIEW_REQUIRED (Sheet 02 A2: 'One valid route selected? NO -> Authorised policy review;
    Missing rules never default to approval').
    """
    attrs = {
        "application_category": application_category,
        "institution_category": institution_category,
        "is_new_institution": is_new_institution,
        **(extra_attributes or {}),
    }
    matched_routes: list[dict[str, Any]] = []
    for rule in policy.route_rules or []:
        conditions: dict[str, Any] = rule.get("conditions", {})
        is_match = True
        for cond_key, expected_val in conditions.items():
            actual_val = attrs.get(cond_key)
            if isinstance(expected_val, list):
                if actual_val not in expected_val:
                    is_match = False
                    break
            elif actual_val != expected_val:
                is_match = False
                break
        if is_match:
            matched_routes.append(rule)

    return {
        "policy_code": policy.policy_code,
        "policy_version_number": policy.version_number,
        "calendar_version": policy.calendar_version,
        "evaluated_inputs": attrs,
        "matched_count": len(matched_routes),
        "selected_route": matched_routes[0] if len(matched_routes) == 1 else None,
        "matched_route_codes": [r.get("route_code", "") for r in matched_routes],
    }
