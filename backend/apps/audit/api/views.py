"""API views for scoped audit trail inspection (Sheet 01 Block 09, PS Section B.3 & F.4)."""
from __future__ import annotations

from django.core.exceptions import PermissionDenied
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.access.models import RoleCode
from apps.access.selectors import scope_cases_queryset
from apps.access.services import resolve_actor_scope
from apps.audit.models import AuditEvent


class AuditEventListView(APIView):
    """Return scoped immutable audit events for cases/institutions visible to the actor."""

    permission_classes = [IsAuthenticated]

    def get(self, request: Request) -> Response:
        try:
            scope = resolve_actor_scope(request.user)
        except PermissionDenied as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_403_FORBIDDEN)

        qs = AuditEvent.objects.all()
        if not (scope.roles & {RoleCode.OVERSIGHT_AUDITOR, RoleCode.COMPETENT_AUTHORITY}):
            visible_cases = scope_cases_queryset(request.user)
            qs = qs.filter(case__in=visible_cases)

        case_id = request.query_params.get("case_id")
        if case_id:
            qs = qs.filter(case_id=case_id)

        return Response(
            [
                {
                    "id": str(ev.id),
                    "sequence_hash": ev.sequence_hash,
                    "previous_hash": ev.previous_hash,
                    "occurred_at": ev.occurred_at.isoformat(),
                    "actor_role": ev.actor_role,
                    "action": ev.action,
                    "target_type": ev.target_type,
                    "target_id": ev.target_id,
                    "old_version": ev.old_version,
                    "new_version": ev.new_version,
                    "reason": ev.reason,
                    "correlation_id": ev.correlation_id,
                }
                for ev in qs.order_by("-occurred_at")[:100]
            ]
        )
