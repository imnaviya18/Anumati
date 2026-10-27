"""Services and selectors for scoped in-app notifications (PS Section F.1, Sheet 04 H3-H4)."""
from __future__ import annotations

from django.contrib.auth.models import AbstractBaseUser
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.utils import timezone

from apps.notifications.models import DeliveryOutcomeState, LogicalAlert


@transaction.atomic
def mark_alert_read(*, actor: AbstractBaseUser, alert: LogicalAlert) -> LogicalAlert:
    """Mark an in-app notification as READ by its recipient (note: reading an alert never closes an escalation — Sheet 04 H5)."""
    if alert.recipient_id != actor.id:
        raise PermissionDenied("Only the alert recipient may mark it as read.")
    alert.outcome_state = DeliveryOutcomeState.READ
    alert.read_at = timezone.now()
    alert.save(update_fields=["outcome_state", "read_at", "updated_at"])
    return alert
