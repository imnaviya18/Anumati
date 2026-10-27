"""Standard pagination classes for all list endpoints (QUALITY BAR: pagination on all lists)."""
from __future__ import annotations

from rest_framework.pagination import PageNumberPagination


class StandardResultsSetPagination(PageNumberPagination):
    """Consistent page-number pagination for list endpoints."""

    page_size = 50
    page_size_query_param = "page_size"
    max_page_size = 200
