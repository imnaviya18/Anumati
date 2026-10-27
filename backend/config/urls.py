"""Root URL configuration for ANUMATI v2 (Sheet 01 Block 01, Sheet 05)."""
from django.urls import include, path
from apps.common.api.views import web_workspace_shell_view

urlpatterns = [
    path("", web_workspace_shell_view, name="workspace-root"),
    path("institution", web_workspace_shell_view, name="workspace-institution"),
    path("officer", web_workspace_shell_view, name="workspace-officer"),
    path("oversight", web_workspace_shell_view, name="workspace-oversight"),
    path("policy", web_workspace_shell_view, name="workspace-policy"),
    path("admin-workspace", web_workspace_shell_view, name="workspace-admin"),
    path("api/v1/", include("apps.common.api.urls")),
    path("api/v1/auth/", include("apps.accounts.api.urls")),
    path("api/v1/organisation/", include("apps.organisation.api.urls")),
    path("api/v1/access/", include("apps.access.api.urls")),
    path("api/v1/adapters/", include("apps.adapters.api.urls")),
    path("api/v1/deadlines/", include("apps.deadlines.api.urls")),
    path("api/v1/evc/", include("apps.evc.api.urls")),
    path("api/v1/cases/", include("apps.cases.api.urls")),
    path("api/v1/decisions/", include("apps.decisions.api.urls")),
    path("api/v1/policy/", include("apps.policy.api.urls")),
    path("api/v1/communications/", include("apps.communications.api.urls")),
    path("api/v1/documents/", include("apps.documents.api.urls")),
    path("api/v1/compliance/", include("apps.compliance.api.urls")),
    path("api/v1/reporting/", include("apps.reporting.api.urls")),
    path("api/v1/outbox/", include("apps.outbox.api.urls")),
    path("api/v1/audit/", include("apps.audit.api.urls")),
    path("api/v1/notifications/", include("apps.notifications.api.urls")),
]
