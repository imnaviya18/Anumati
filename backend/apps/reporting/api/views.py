"""API views for role-based dashboards, polling, and the exact 6 statutory reports + CSV export (PS Sections B & F)."""
from __future__ import annotations

from django.core.exceptions import PermissionDenied, ValidationError
from django.http import HttpResponse
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.reporting.selectors import generate_statutory_report, select_role_dashboard_snapshot
from apps.reporting.services import export_statutory_report_csv


class RoleDashboardSnapshotView(APIView):
    """Return role-based dashboard snapshot with 'data_as_of' timestamp for authenticated polling (PS Section B)."""

    permission_classes = [IsAuthenticated]

    def get(self, request: Request) -> Response:
        try:
            snapshot = select_role_dashboard_snapshot(
                request.user,
                region_code=request.query_params.get("region_code"),
                academic_cycle=request.query_params.get("academic_cycle"),
                bureau_code=request.query_params.get("bureau_code"),
            )
            return Response(snapshot)
        except PermissionDenied as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_403_FORBIDDEN)


class StatutoryReportView(APIView):
    """Return one of the exact 6 statutory reports as JSON or CSV export with strict scope checks (PS Section F.3)."""

    permission_classes = [IsAuthenticated]

    def get(self, request: Request, report_code: str) -> Response | HttpResponse:
        filters = {
            "region_code": request.query_params.get("region_code"),
            "academic_cycle": request.query_params.get("academic_cycle"),
            "institution_code": request.query_params.get("institution_code"),
        }
        export_format = request.query_params.get("export", "").lower()
        try:
            if export_format == "csv":
                csv_text, _ = export_statutory_report_csv(
                    actor=request.user,
                    report_code=report_code,
                    filters=filters,
                )
                resp = HttpResponse(csv_text, content_type="text/csv; charset=utf-8")
                resp["Content-Disposition"] = f'attachment; filename="{report_code}.csv"'
                return resp

            payload = generate_statutory_report(
                request.user,
                report_code=report_code,
                filters=filters,
            )
            return Response(payload)
        except PermissionDenied as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_403_FORBIDDEN)
        except ValidationError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
