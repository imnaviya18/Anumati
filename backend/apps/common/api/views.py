"""Health boundary and redirect to the single React workspace implementation."""
from django.conf import settings
from django.http import HttpResponseRedirect
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from apps.common.selectors import select_health_snapshot


@api_view(["GET"])
@permission_classes([AllowAny])
def health_check_view(request):
    snapshot = select_health_snapshot()
    snapshot["correlation_id"] = getattr(request, "correlation_id", "")
    return Response(snapshot, status=200 if snapshot["status"] == "ok" else 503)


def web_workspace_shell_view(request):
    path = "/admin" if request.path == "/admin-workspace" else request.path
    return HttpResponseRedirect(settings.FRONTEND_ORIGIN.rstrip("/") + path)
