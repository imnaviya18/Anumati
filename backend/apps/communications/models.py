"""Models for standardised communication templates and deterministic electronic case summaries (Sheet 02 C1/C3, PS Section A)."""
from __future__ import annotations

import uuid
from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.common.models import TimeStampedModel


class CommunicationTemplate(TimeStampedModel):
    """Versioned, effective-dated communication & case-summary template managed through policy governance (PS Section A)."""

    class TemplateCategory(models.TextChoices):
        LOA = "LOA", "Letter of Approval (LoA)"
        EOA = "EOA", "Extension of Approval (EoA)"
        LOD = "LOD", "Letter of Deficiency (LoD)"
        LOR_SPEAKING_ORDER = "LOR_SPEAKING_ORDER", "Letter of Rejection (LoR) / Speaking Order"
        DEFICIENCY_NOTICE = "DEFICIENCY_NOTICE", "Scrutiny / Compliance Deficiency Notice"
        EVC_NOTICE = "EVC_NOTICE", "EVC Schedule / Visit Notice"
        RENEWAL_NOTICE = "RENEWAL_NOTICE", "Document Validity Renewal Notice"
        CASE_SUMMARY = "CASE_SUMMARY", "Electronic Case Summary Template"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    template_code = models.CharField(max_length=64, db_index=True)
    version_number = models.PositiveIntegerField(default=1)
    category = models.CharField(
        max_length=32,
        choices=TemplateCategory.choices,
        db_index=True,
    )
    policy_version = models.ForeignKey(
        "policy.PolicyVersion",
        on_delete=models.PROTECT,
        related_name="communication_templates",
        null=True,
        blank=True,
    )
    subject_template = models.CharField(max_length=255)
    body_template = models.TextField()
    required_fields = models.JSONField(default=list, blank=True)
    effective_from = models.DateTimeField(default=timezone.now)
    effective_until = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True, db_index=True)

    class Meta:
        ordering = ["template_code", "-version_number"]
        constraints = [
            models.UniqueConstraint(
                fields=["template_code", "version_number"],
                name="uniq_comm_template_code_version",
            )
        ]


class RenderedCommunication(TimeStampedModel):
    """Audited record of an issued standardised communication or generated electronic case summary (Sheet 02 C3, PS Section A)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    case = models.ForeignKey(
        "cases.ApplicationCase",
        on_delete=models.CASCADE,
        related_name="rendered_communications",
    )
    template = models.ForeignKey(
        CommunicationTemplate,
        on_delete=models.PROTECT,
        related_name="rendered_instances",
    )
    decision = models.ForeignKey(
        "decisions.CaseDecision",
        on_delete=models.PROTECT,
        related_name="communications",
        null=True,
        blank=True,
    )
    issued_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="issued_communications",
    )
    rendered_subject = models.CharField(max_length=255)
    rendered_body = models.TextField()
    context_snapshot = models.JSONField(default=dict)
    case_version_at_render = models.PositiveIntegerField()
