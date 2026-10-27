"""Scoped query selectors for access filtering across cases, obligations, documents, and reports (Sheet 01 Block 01, Sheet 07 P1, Q2)."""
from __future__ import annotations

from typing import Any
from django.db.models import Q, QuerySet
from django.utils import timezone

from apps.access.models import CaseAssignment, RoleCode
from apps.access.services import resolve_actor_scope
from apps.cases.models import ApplicationCase
from apps.compliance.models import Obligation
from apps.documents.models import DocumentValidityRecord, DocumentVersion


def scope_cases_queryset(user: Any, queryset: QuerySet[ApplicationCase] | None = None) -> QuerySet[ApplicationCase]:
    """Filter ApplicationCase queryset strictly by actor scope (deny by default — Sheet 07 P1, Q2)."""
    now = timezone.now()
    scope = resolve_actor_scope(user, now)
    qs = queryset if queryset is not None else ApplicationCase.objects.all()

    if RoleCode.OVERSIGHT_AUDITOR in scope.roles or RoleCode.COMPETENT_AUTHORITY in scope.roles:
        return qs

    filters = Q(pk__in=[])
    if RoleCode.INSTITUTION_USER in scope.roles and scope.institution_ids:
        filters |= Q(institution_id__in=scope.institution_ids)

    if RoleCode.REGIONAL_OFFICER in scope.roles and scope.region_ids:
        filters |= Q(region_id__in=scope.region_ids)

    if RoleCode.BUREAU_OFFICER in scope.roles:
        if scope.bureau_ids:
            filters |= Q(responsible_bureau_id__in=scope.bureau_ids)
        if scope.region_ids:
            filters |= Q(region_id__in=scope.region_ids)

    if scope.roles & {RoleCode.SCRUTINY_MEMBER, RoleCode.EVC_MEMBER, RoleCode.COMMITTEE_MEMBER}:
        valid_case_ids = [
            ca.case_id
            for ca in CaseAssignment.objects.filter(
                Q(user=user) | Q(committee_id__in=scope.committee_ids),
                is_active=True,
            )
            if ca.is_currently_valid(now)
        ]
        if valid_case_ids:
            filters |= Q(id__in=valid_case_ids)

    return qs.filter(filters).distinct()


def scope_obligations_queryset(user: Any, queryset: QuerySet[Obligation] | None = None) -> QuerySet[Obligation]:
    """Filter Obligation queryset strictly by actor scope (Sheet 07 P1, Q2)."""
    scope = resolve_actor_scope(user)
    qs = queryset if queryset is not None else Obligation.objects.all()

    if RoleCode.OVERSIGHT_AUDITOR in scope.roles or RoleCode.COMPETENT_AUTHORITY in scope.roles:
        return qs

    filters = Q(pk__in=[])
    if RoleCode.INSTITUTION_USER in scope.roles and scope.institution_ids:
        filters |= Q(institution_id__in=scope.institution_ids)
    if (RoleCode.REGIONAL_OFFICER in scope.roles or RoleCode.BUREAU_OFFICER in scope.roles) and scope.region_ids:
        filters |= Q(institution__region_id__in=scope.region_ids)
    if RoleCode.BUREAU_OFFICER in scope.roles and scope.bureau_ids:
        filters |= Q(case__responsible_bureau_id__in=scope.bureau_ids)

    if RoleCode.SCRUTINY_MEMBER in scope.roles:
        filters |= Q(case_id__in=scope_cases_queryset(user).values("id"))
    return qs.filter(filters).distinct()


def scope_documents_queryset(
    user: Any, queryset: QuerySet[DocumentVersion] | None = None
) -> QuerySet[DocumentVersion]:
    """Filter DocumentVersion queryset strictly by actor scope (Sheet 07 P1, Q2)."""
    now = timezone.now()
    scope = resolve_actor_scope(user, now)
    qs = queryset if queryset is not None else DocumentVersion.objects.all()

    if RoleCode.OVERSIGHT_AUDITOR in scope.roles or RoleCode.COMPETENT_AUTHORITY in scope.roles:
        return qs

    filters = Q(pk__in=[])
    if RoleCode.INSTITUTION_USER in scope.roles and scope.institution_ids:
        filters |= Q(institution_id__in=scope.institution_ids)
    if (RoleCode.REGIONAL_OFFICER in scope.roles or RoleCode.BUREAU_OFFICER in scope.roles) and scope.region_ids:
        filters |= Q(institution__region_id__in=scope.region_ids)
    if RoleCode.BUREAU_OFFICER in scope.roles and scope.bureau_ids:
        filters |= Q(case__responsible_bureau_id__in=scope.bureau_ids)
    if scope.roles & {RoleCode.SCRUTINY_MEMBER, RoleCode.EVC_MEMBER, RoleCode.COMMITTEE_MEMBER}:
        valid_case_ids = [
            ca.case_id
            for ca in CaseAssignment.objects.filter(
                Q(user=user) | Q(committee_id__in=scope.committee_ids),
                is_active=True,
            )
            if ca.is_currently_valid(now)
        ]
        if valid_case_ids:
            filters |= Q(case_id__in=valid_case_ids)

    return qs.filter(filters).distinct()


def scope_validity_records_queryset(
    user: Any, queryset: QuerySet[DocumentValidityRecord] | None = None
) -> QuerySet[DocumentValidityRecord]:
    """Filter DocumentValidityRecord queryset strictly by actor scope (Sheet 07 P1, Q2)."""
    scope = resolve_actor_scope(user)
    qs = queryset if queryset is not None else DocumentValidityRecord.objects.all()

    if RoleCode.OVERSIGHT_AUDITOR in scope.roles or RoleCode.COMPETENT_AUTHORITY in scope.roles:
        return qs

    filters = Q(pk__in=[])
    if RoleCode.INSTITUTION_USER in scope.roles and scope.institution_ids:
        filters |= Q(institution_id__in=scope.institution_ids)
    if (RoleCode.REGIONAL_OFFICER in scope.roles or RoleCode.BUREAU_OFFICER in scope.roles) and scope.region_ids:
        filters |= Q(institution__region_id__in=scope.region_ids)

    return qs.filter(filters).distinct()
