"""Append-only audit services and sealed export mechanism (Sheet 01 Block 09, Sheet 06 L2, Sheet 07 N5)."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from django.conf import settings
from django.db import connection, transaction
from django.utils import timezone

from apps.audit.models import AuditEvent
from apps.common.middleware import get_correlation_id


@transaction.atomic
def record_audit_event(
    *,
    actor: Any,
    actor_role: str,
    actor_scope: dict[str, Any],
    action: str,
    target_type: str,
    target_id: str,
    reason: str = "",
    case: Any = None,
    institution: Any = None,
    region: Any = None,
    policy_version_ref: str = "",
    old_version: int | None = None,
    new_version: int | None = None,
    inputs_snapshot: dict[str, Any] | None = None,
    correlation_id: str | None = None,
) -> AuditEvent:
    """Append an immutable audit event with hash-chain link and correlation ID (Sheet 01 Block 09, Sheet 06 L2)."""
    # Serialize the chain head, including the initially empty ledger, across processes.
    if connection.vendor == "postgresql":
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_xact_lock(%s)", [26262009])
    last_event = AuditEvent.objects.order_by("-occurred_at", "-id").first()
    prev_hash = last_event.sequence_hash if last_event else "GENESIS"
    corr_id = correlation_id or get_correlation_id()

    user_obj = actor if (actor and getattr(actor, "is_authenticated", False)) else None
    return AuditEvent.objects.create(
        previous_hash=prev_hash,
        actor=user_obj,
        actor_role=actor_role,
        actor_scope=actor_scope,
        action=action,
        target_type=target_type,
        target_id=str(target_id),
        case=case,
        institution=institution or getattr(case, "institution", None),
        region=region or getattr(case, "region", None),
        policy_version_ref=policy_version_ref,
        old_version=old_version,
        new_version=new_version,
        reason=reason,
        inputs_snapshot=inputs_snapshot or {},
        correlation_id=corr_id,
    )


def export_sealed_audit_bundle(export_dir: Path | None = None) -> Path:
    """Export sealed, read-only SHA-256-manifested audit bundle (Sheet 01 Block 09, Sheet 07 N5, SECURITY_NOTES.md)."""
    base_dir = Path(export_dir or settings.SEALED_AUDIT_EXPORT_ROOT)
    base_dir.mkdir(parents=True, exist_ok=True)
    stamp = timezone.now().strftime("%Y%m%dT%H%M%S%fZ")
    bundle_path = base_dir / f"sealed_audit_{stamp}.json"

    events = list(
        AuditEvent.objects.order_by("occurred_at", "id").values(
            "id",
            "sequence_hash",
            "previous_hash",
            "occurred_at",
            "actor_id",
            "actor_role",
            "action",
            "target_type",
            "target_id",
            "old_version",
            "new_version",
            "reason",
            "policy_version_ref",
            "correlation_id",
        )
    )
    serializable = [
        {
            **row,
            "id": str(row["id"]),
            "occurred_at": row["occurred_at"].isoformat(),
        }
        for row in events
    ]
    raw_bytes = json.dumps(serializable, sort_keys=True, indent=2).encode("utf-8")
    digest = hashlib.sha256(raw_bytes).hexdigest()

    envelope = {
        "exported_at": timezone.now().isoformat(),
        "event_count": len(serializable),
        "bundle_sha256": digest,
        "events": serializable,
    }
    bundle_path.write_text(json.dumps(envelope, sort_keys=True, indent=2), encoding="utf-8")
    # Seal file permissions to read-only (0444) so application runtime cannot overwrite it
    bundle_path.chmod(0o444)
    return bundle_path
