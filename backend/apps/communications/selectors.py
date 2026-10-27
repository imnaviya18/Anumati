"""Selectors for communication templates and rendered communications."""
from __future__ import annotations

from typing import Any
from django.db.models import QuerySet

from apps.access.selectors import scope_cases_queryset
from apps.communications.models import CommunicationTemplate, RenderedCommunication


def select_active_templates(*, category: str | None = None) -> QuerySet[CommunicationTemplate]:
    """Return active communication templates."""
    qs = CommunicationTemplate.objects.filter(is_active=True)
    if category:
        qs = qs.filter(category=category)
    return qs


def select_rendered_communications_for_user(
    user: Any,
    *,
    case_id: str | None = None,
) -> QuerySet[RenderedCommunication]:
    """Return rendered communications visible to the user."""
    visible_cases = scope_cases_queryset(user)
    qs = RenderedCommunication.objects.select_related("case", "template", "issued_by", "decision").filter(
        case__in=visible_cases
    )
    if case_id:
        qs = qs.filter(case_id=case_id)
    return qs
