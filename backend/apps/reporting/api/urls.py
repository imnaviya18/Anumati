"""URL routes for dashboards and the 6 statutory reports."""
from django.urls import path
from apps.reporting.api.views import RoleDashboardSnapshotView, StatutoryReportView

urlpatterns = [
    path("dashboard/", RoleDashboardSnapshotView.as_view(), name="reporting-dashboard"),
    path("reports/<str:report_code>/", StatutoryReportView.as_view(), name="reporting-statutory-report"),
]
