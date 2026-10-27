"""URL routes for audit trail inspection."""
from django.urls import path
from apps.audit.api.views import AuditEventListView

urlpatterns = [
    path("events/", AuditEventListView.as_view(), name="audit-events-list"),
]
