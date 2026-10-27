"""API views for electronic case summaries and standardised communications (PS Section A.5, A.6)."""
from __future__ import annotations

from django.core.exceptions import PermissionDenied, ValidationError
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.cases.models import ApplicationCase
from apps.communications.models import CommunicationTemplate
from apps.communications.services import (
    issue_standardised_communication,
    render_electronic_case_summary,
)


class ElectronicCaseSummaryView(APIView):
    """Generate and return a deterministic electronic case summary without mutating case state or decisions (PS-A.5)."""

    permission_classes = [IsAuthenticated]

    def post(self, request: Request, case_id: str) -> Response:
        case = get_object_or_404(ApplicationCase, id=case_id)
        try:
            rec = render_electronic_case_summary(actor=request.user, case=case)
            return Response(
                {
                    "id": str(rec.id),
                    "case_id": str(case.id),
                    "rendered_subject": rec.rendered_subject,
                    "rendered_body": rec.rendered_body,
                    "case_version_at_render": rec.case_version_at_render,
                }
            )
        except PermissionDenied as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_403_FORBIDDEN)
        except ValidationError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)


class IssueCommunicationView(APIView):
    """Issue a standardised communication from a versioned template (PS-A.6)."""

    permission_classes = [IsAuthenticated]

    def post(self, request: Request, case_id: str) -> Response:
        case = get_object_or_404(ApplicationCase, id=case_id)
        template = get_object_or_404(CommunicationTemplate, id=request.data.get("template_id"))
        try:
            rec = issue_standardised_communication(
                actor=request.user,
                case=case,
                template=template,
                extra_fields=request.data.get("extra_fields") or {},
            )
            return Response(
                {
                    "id": str(rec.id),
                    "case_id": str(case.id),
                    "template_code": template.template_code,
                    "rendered_subject": rec.rendered_subject,
                    "rendered_body": rec.rendered_body,
                },
                status=status.HTTP_201_CREATED,
            )
        except PermissionDenied as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_403_FORBIDDEN)
        except ValidationError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
