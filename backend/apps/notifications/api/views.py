"""API views for in-app notifications (PS Section F.1, Sheet 04 H3-H4)."""
from __future__ import annotations

from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.notifications.models import LogicalAlert
from apps.notifications.selectors import select_alerts_for_user
from apps.notifications.services import mark_alert_read


class NotificationListView(APIView):
    """List in-app notifications addressed to the authenticated actor."""

    permission_classes = [IsAuthenticated]

    def get(self, request: Request) -> Response:
        qs = select_alerts_for_user(request.user)
        return Response(
            [
                {
                    "id": str(al.id),
                    "milestone_code": al.milestone_code,
                    "subject": al.subject,
                    "body": al.body,
                    "outcome_state": al.outcome_state,
                    "created_at": al.created_at.isoformat(),
                    "read_at": al.read_at.isoformat() if al.read_at else None,
                }
                for al in qs[:100]
            ]
        )


class NotificationMarkReadView(APIView):
    """Mark an in-app notification as READ by its recipient."""

    permission_classes = [IsAuthenticated]

    def post(self, request: Request, alert_id: str) -> Response:
        alert = get_object_or_404(LogicalAlert, id=alert_id)
        try:
            updated = mark_alert_read(actor=request.user, alert=alert)
            return Response({"id": str(updated.id), "outcome_state": updated.outcome_state})
        except PermissionDenied as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_403_FORBIDDEN)
