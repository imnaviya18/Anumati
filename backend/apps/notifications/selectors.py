"""Selectors for in-app notifications scoped to the authenticated user."""
from __future__ import annotations

from django.contrib.auth.models import AbstractBaseUser
from django.db.models import QuerySet
from apps.notifications.models import LogicalAlert


def select_alerts_for_user(user: AbstractBaseUser) -> QuerySet[LogicalAlert]:
    """Return logical alerts addressed to the authenticated user."""
    if not user or not user.is_authenticated:
        return LogicalAlert.objects.none()
    return LogicalAlert.objects.select_related("case", "institution", "deadline").filter(
        recipient=user
    )
