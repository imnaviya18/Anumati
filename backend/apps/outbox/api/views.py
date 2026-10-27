"""API views for operational outbox metrics, failed queue, and audited operator replay (Sheets 05, 06 M3, 07 Q4)."""
from __future__ import annotations

from django.core.exceptions import PermissionDenied, ValidationError
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.access.models import RoleCode
from apps.access.services import resolve_actor_scope
from apps.outbox.models import OutboxEvent
from apps.outbox.selectors import select_failed_outbox_queue, select_operations_metrics
from apps.outbox.services import operator_replay_failed_event


class OutboxOperationsMetricsView(APIView):
    """Return operational queue age, failed jobs, stale leases, due lag, and outbox backlog (Sheet 07 Q4)."""

    permission_classes = [IsAuthenticated]

    def get(self, request: Request) -> Response:
        try:
            scope = resolve_actor_scope(request.user)
            if not (scope.roles & {RoleCode.TECHNICAL_ADMIN, RoleCode.OVERSIGHT_AUDITOR, RoleCode.BUREAU_OFFICER}):
                return Response({"detail": "Operations metrics restricted to operators."}, status=status.HTTP_403_FORBIDDEN)
            return Response(select_operations_metrics())
        except PermissionDenied as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_403_FORBIDDEN)


class OutboxFailedQueueReplayView(APIView):
    """List failed outbox items or execute audited operator replay (Sheet 06 M3)."""

    permission_classes = [IsAuthenticated]

    def get(self, request: Request) -> Response:
        try:
            scope = resolve_actor_scope(request.user)
            if not (scope.roles & {RoleCode.TECHNICAL_ADMIN, RoleCode.OVERSIGHT_AUDITOR, RoleCode.BUREAU_OFFICER}):
                return Response({"detail": "Denied."}, status=status.HTTP_403_FORBIDDEN)
            qs = select_failed_outbox_queue()
            return Response(
                [
                    {
                        "id": str(ev.id),
                        "logical_id": ev.logical_id,
                        "event_type": ev.event_type,
                        "attempt_count": ev.attempt_count,
                        "last_error": ev.last_error,
                        "exception_reason": ev.exception_reason,
                    }
                    for ev in qs[:100]
                ]
            )
        except PermissionDenied as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_403_FORBIDDEN)

    def post(self, request: Request, event_id: str) -> Response:
        event = get_object_or_404(OutboxEvent, id=event_id)
        try:
            updated = operator_replay_failed_event(
                actor=request.user,
                outbox_event_id=event.id,
                reason=str(request.data.get("reason", "")),
            )
            return Response({"id": str(updated.id), "state": updated.state})
        except PermissionDenied as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_403_FORBIDDEN)
        except ValidationError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
