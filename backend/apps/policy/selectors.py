"""Selectors for policy versions and migrations (Sheet 01 Block 05, Sheet 07 P3-P4)."""
from __future__ import annotations

from django.db.models import QuerySet
from apps.policy.models import PolicyMigrationRecord, PolicyVersion


def select_policy_versions(*, academic_cycle: str | None = None) -> QuerySet[PolicyVersion]:
    """Return policy versions ordered by version_number descending."""
    qs = PolicyVersion.objects.select_related("created_by", "approved_by").all()
    if academic_cycle:
        qs = qs.filter(academic_cycle=academic_cycle)
    return qs


def select_policy_migrations() -> QuerySet[PolicyMigrationRecord]:
    """Return policy migration history."""
    return PolicyMigrationRecord.objects.select_related(
        "source_policy", "target_policy", "authorised_by"
    ).all()
