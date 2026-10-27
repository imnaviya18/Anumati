"""API views for policy governance (Sheet 01 Block 05, Sheet 04 J1-J3, Sheet 07 P3-P4)."""
from __future__ import annotations

from django.core.exceptions import PermissionDenied, ValidationError
from django.shortcuts import get_object_or_404
from rest_framework import status, serializers
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.access.services import resolve_actor_scope
from apps.policy.models import PolicyVersion
from apps.policy.selectors import select_policy_versions
from apps.policy.services import (
    approve_and_activate_policy_version,
    approve_policy_version,
    draft_policy_version,
    edit_draft_policy,
    migrate_cases_to_policy_version,
    run_policy_dry_run,
    validate_policy_version,
)


def _serialize_policy(p: PolicyVersion) -> dict:
    return {
        "id": str(p.id),
        "policy_code": p.policy_code,
        "version_number": p.version_number,
        "academic_cycle": p.academic_cycle,
        "state": p.state,
        "calendar_version": p.calendar_version,
        "route_rules": p.route_rules,
        "is_demonstration": p.is_demonstration,
        "provenance": p.provenance,
        "configuration": {field:getattr(p,field) for field in ("route_rules","stage_timelines","evc_rules","undertaking_rules","document_validity_rules","escalation_hierarchies","calendar_holidays","regression_cases","document_requirements","committee_permissions","exception_rules","deadline_triggers","provenance")},
        "validation_report": p.validation_report,
        "dry_run_report": p.dry_run_report,
        "effective_from": p.effective_from.isoformat() if p.effective_from else None,
        "approved_by": p.approved_by_id,
        "approved_at": p.approved_at,
        "approval_reason": p.approval_reason,
        "effective_until": p.effective_until,
        "activated_at": p.activated_at.isoformat() if p.activated_at else None,
    }


class PolicyListDraftView(APIView):
    """List policy versions or create a new DRAFT policy version (Sheet 04 J1)."""

    permission_classes = [IsAuthenticated]

    def get(self, request: Request) -> Response:
        try:
            resolve_actor_scope(request.user)
        except PermissionDenied as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_403_FORBIDDEN)
        qs = select_policy_versions(academic_cycle=request.query_params.get("academic_cycle"))
        return Response([_serialize_policy(p) for p in qs])

    def post(self, request: Request) -> Response:
        try:
            class Dates(serializers.Serializer):
                effective_from = serializers.DateTimeField(required=False)
                effective_until = serializers.DateTimeField(required=False, allow_null=True)
            dates = Dates(data=request.data)
            dates.is_valid(raise_exception=True)
            policy = draft_policy_version(
                actor=request.user,
                policy_code=str(request.data.get("policy_code", "")),
                version_number=int(request.data.get("version_number", 1)),
                academic_cycle=str(request.data.get("academic_cycle", "")),
                **dates.validated_data,
                calendar_holidays=request.data.get("calendar_holidays") or [],
                calendar_version=str(request.data.get("calendar_version", "CAL-v1")),
                route_rules=request.data.get("route_rules") or [],
                stage_timelines=request.data.get("stage_timelines") or {},
                evc_rules=request.data.get("evc_rules") or {},
                undertaking_rules=request.data.get("undertaking_rules") or [],
                document_validity_rules=request.data.get("document_validity_rules") or {},
                escalation_hierarchies=request.data.get("escalation_hierarchies") or {},
                regression_cases=request.data.get("regression_cases") or [],
                is_demonstration=request.data.get("is_demonstration") is True,
                provenance=request.data.get("provenance") or {"pending_validation":["AICTE owner review"]},
                document_requirements=request.data.get("document_requirements") or {},
                committee_permissions=request.data.get("committee_permissions") or {},
                exception_rules=request.data.get("exception_rules") or {},
                deadline_triggers=request.data.get("deadline_triggers") or {},
            )
            return Response(_serialize_policy(policy), status=status.HTTP_201_CREATED)
        except PermissionDenied as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_403_FORBIDDEN)
        except ValidationError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)


class PolicyActionView(APIView):
    """Execute validate, dry-run, or activate on a policy version (Sheet 04 J2-J3, Sheet 07 P3-P4)."""

    permission_classes = [IsAuthenticated]

    def post(self, request: Request, policy_id: str, action_name: str) -> Response:
        policy = get_object_or_404(PolicyVersion, id=policy_id)
        try:
            if action_name == "edit":
                updated = edit_draft_policy(actor=request.user,policy_id=policy.id,changes=request.data.get("changes"),reason=str(request.data.get("reason","")))
            elif action_name == "validate":
                updated = validate_policy_version(actor=request.user, policy=policy)
            elif action_name == "dry-run":
                updated = run_policy_dry_run(actor=request.user, policy=policy)
            elif action_name == "approve":
                updated = approve_policy_version(actor=request.user, policy=policy, reason=str(request.data.get("reason", "")))
            elif action_name == "activate":
                if policy.state != PolicyVersion.PolicyState.APPROVED:
                    raise ValidationError("An explicit competent-authority approval is required before activation.")
                updated = approve_and_activate_policy_version(actor=request.user, policy=policy)
            else:
                return Response({"detail": "Unknown policy action."}, status=status.HTTP_400_BAD_REQUEST)
            return Response(_serialize_policy(updated))
        except PermissionDenied as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_403_FORBIDDEN)
        except ValidationError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)


class PolicyMigrateCasesView(APIView):
    """Explicitly migrate open cases to a target ACTIVE policy version (Sheet 07 P4)."""

    permission_classes = [IsAuthenticated]

    def post(self, request: Request) -> Response:
        source = get_object_or_404(PolicyVersion, id=request.data.get("source_policy_id"))
        target = get_object_or_404(PolicyVersion, id=request.data.get("target_policy_id"))
        try:
            rec = migrate_cases_to_policy_version(
                actor=request.user,
                source_policy=source,
                target_policy=target,
                case_ids=request.data.get("case_ids") or [],
                reason=str(request.data.get("reason", "")),
            )
            return Response(
                {
                    "migration_id": str(rec.id),
                    "affected_case_ids": rec.affected_case_ids,
                }
            )
        except PermissionDenied as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_403_FORBIDDEN)
        except ValidationError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
