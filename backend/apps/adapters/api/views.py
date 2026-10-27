"""Views for inspecting disabled adapter ports (Sheet 01 Block 12)."""
from __future__ import annotations

from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response

from apps.adapters.selectors import select_all_adapter_statuses


@api_view(["GET"])
@permission_classes([AllowAny])
def adapter_status_view(request: Request) -> Response:
    """Return status of all disabled external adapter ports."""
    return Response(select_all_adapter_statuses())
