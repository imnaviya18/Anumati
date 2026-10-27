"""Operational metrics selectors for outbox, leases, and due-work lag (Sheet 05 Operations, Sheet 07 Q4)."""
from __future__ import annotations

from typing import Any
from django.db.models import QuerySet
from django.utils import timezone

from apps.deadlines.models import DeadlineRecord, DeadlineState
from apps.outbox.models import OutboxEvent, OutboxState


def select_failed_outbox_queue() -> QuerySet[OutboxEvent]:
    """Return outbox events in FAILED_OWNED or UNKNOWN_RECONCILING state (Sheet 06 M3-M4)."""
    return OutboxEvent.objects.filter(
        state__in=[OutboxState.FAILED_OWNED, OutboxState.UNKNOWN_RECONCILING]
    ).order_by("-updated_at")


def select_operations_metrics(now: timezone.datetime | None = None) -> dict[str, Any]:
    """Compute queue age, failed jobs, stale leases, due lag, and outbox backlog (Sheet 05, Sheet 07 Q4)."""
    current_time = now or timezone.now()

    pending_qs = OutboxEvent.objects.filter(
        state__in=[OutboxState.PENDING, OutboxState.LEASED, OutboxState.PUBLISHED]
    )
    outbox_backlog = pending_qs.count()
    oldest_pending = pending_qs.order_by("created_at").first()
    queue_age_seconds = (
        max(0.0, (current_time - oldest_pending.created_at).total_seconds())
        if oldest_pending
        else 0.0
    )

    stale_leases = OutboxEvent.objects.filter(
        state__in=[OutboxState.LEASED, OutboxState.PUBLISHED],
        lease_expires_at__lte=current_time,
    ).count()

    failed_jobs = OutboxEvent.objects.filter(state=OutboxState.FAILED_OWNED).count()
    unknown_jobs = OutboxEvent.objects.filter(state=OutboxState.UNKNOWN_RECONCILING).count()

    overdue_deadlines = DeadlineRecord.objects.filter(
        state=DeadlineState.ACTIVE,
        due_at__lte=current_time,
    ).order_by("due_at")
    oldest_due = overdue_deadlines.first()
    due_lag_seconds = (
        max(0.0, (current_time - oldest_due.due_at).total_seconds())
        if oldest_due
        else 0.0
    )

    return {
        "data_as_of": current_time.isoformat(),
        "outbox_backlog": outbox_backlog,
        "queue_age_seconds": round(queue_age_seconds, 3),
        "stale_leases": stale_leases,
        "failed_jobs": failed_jobs,
        "unknown_reconciling_jobs": unknown_jobs,
        "due_lag_seconds": round(due_lag_seconds, 3),
    }
