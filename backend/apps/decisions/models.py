"""Models for decisions and idempotency command records (Sheet 02 C1-C4, Sheet 06 K1-K6, L1-L3, Sheet 07 N1, N4)."""
from __future__ import annotations

import uuid
from django.conf import settings
from django.db import models

from apps.common.models import TimeStampedModel


class DecisionOutcome(models.TextChoices):
    """Authorised Competent Authority disposition outcomes (Sheet 02 C1-C2, APH 1.10, 2.25)."""

    GRANT_LOA = "GRANT_LOA", "Grant Letter of Approval (LoA)"
    GRANT_EOA = "GRANT_EOA", "Grant Extension of Approval (EoA)"
    ISSUE_LOD = "ISSUE_LOD", "Issue Letter of Deficiency (LoD)"
    REJECT_LOR = "REJECT_LOR", "Issue Letter of Rejection (LoR) & Speaking Order"
    REFER_BACK = "REFER_BACK", "Refer Back to Designated Stage (C1 -> B1)"


class CaseDecision(TimeStampedModel):
    """Authoritative Competent Authority decision tied to processing instance and reviewed evidence (Sheet 02 C2, Sheet 06 K6/L1, Sheet 07 N1)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    case = models.ForeignKey(
        "cases.ApplicationCase",
        on_delete=models.PROTECT,
        related_name="decisions",
    )
    outcome = models.CharField(
        max_length=32,
        choices=DecisionOutcome.choices,
        db_index=True,
    )
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="recorded_decisions",
    )
    decided_by_role = models.CharField(max_length=32)
    delegated_power_ref = models.CharField(max_length=128)
    pinned_policy_version = models.ForeignKey(
        "policy.PolicyVersion",
        on_delete=models.PROTECT,
        related_name="decisions",
    )
    case_version_at_decision = models.PositiveIntegerField()
    reasons = models.TextField()
    reviewed_evidence_version_ids = models.JSONField(default=list, blank=True)
    refer_back_stage_type = models.CharField(max_length=32, blank=True, default="")
    is_current_final = models.BooleanField(default=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            # One current final decision per processing instance (Sheet 06 K6)
            models.UniqueConstraint(
                fields=["case"],
                condition=models.Q(is_current_final=True),
                name="uniq_one_current_final_decision_per_case",
            )
        ]


class IdempotencyRecord(TimeStampedModel):
    """Command identity and saved response for guarded decision/transition commands (Sheet 06 K1, K3, L2, Sheet 07 N4)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="idempotency_records",
    )
    action = models.CharField(max_length=64, db_index=True)
    idempotency_key = models.CharField(max_length=128, db_index=True)
    case = models.ForeignKey(
        "cases.ApplicationCase",
        on_delete=models.PROTECT,
        related_name="idempotency_records",
        null=True,
        blank=True,
    )
    payload_fingerprint = models.CharField(max_length=64)
    response_status = models.PositiveSmallIntegerField()
    response_body = models.JSONField(default=dict)
    correlation_id = models.CharField(max_length=64, blank=True, default="")

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["actor", "action", "idempotency_key"],
                name="uniq_actor_action_idempotency_key",
            )
        ]
        indexes = [
            models.Index(
                fields=["actor", "action", "idempotency_key"],
                name="idx_idemp_actor_action_key",
            ),
        ]
