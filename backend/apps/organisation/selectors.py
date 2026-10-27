"""Scoped selectors for organisation entities (Sheet 01, Sheet 07 P1)."""
from __future__ import annotations

from typing import Any
from django.db.models import QuerySet

from apps.access.models import RoleCode
from apps.access.services import resolve_actor_scope
from apps.organisation.models import Institution, Region


def select_visible_institutions(user: Any) -> QuerySet[Institution]:
    """Return institutions visible to the authenticated user based on their role scope."""
    scope = resolve_actor_scope(user)
    qs = Institution.objects.filter(is_active=True).select_related("region")
    if RoleCode.OVERSIGHT_AUDITOR in scope.roles or RoleCode.COMPETENT_AUTHORITY in scope.roles or RoleCode.TECHNICAL_ADMIN in scope.roles:
        return qs
    if RoleCode.INSTITUTION_USER in scope.roles:
        return qs.filter(id__in=scope.institution_ids)
    if RoleCode.REGIONAL_OFFICER in scope.roles or RoleCode.BUREAU_OFFICER in scope.roles:
        return qs.filter(region_id__in=scope.region_ids)
    return qs.none()


def select_active_regions() -> QuerySet[Region]:
    """Return active AICTE regions."""
    return Region.objects.filter(is_active=True).order_by("code")
