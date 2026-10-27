"""Outbox dispatcher, worker leases, retries with backoff + jitter, reconciliation, and stranded-work recovery (Sheet 01 Block 08, Sheet 04 H3-H4, J4-J5, Sheet 05, Sheet 06 L4, M1-M6)."""
from __future__ import annotations

from datetime import timedelta
import random
from typing import Any, Callable
import uuid

from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.mail import send_mail
from django.db import transaction
from django.utils import timezone

from apps.access.models import RoleCode
from apps.access.services import resolve_actor_scope
from apps.audit.services import record_audit_event
from apps.common.middleware import get_correlation_id
from apps.deadlines.models import DeadlineState
from apps.notifications.models import DeliveryChannel, DeliveryOutcomeState, LogicalAlert
from apps.outbox.models import CallbackReceipt, DeliveryAttempt, OutboxEvent, OutboxState


def calculate_backoff_with_jitter(attempt_count: int, base_seconds: int = 15, max_seconds: int = 3600) -> int:
    """Calculate exponential backoff with bounded jitter in seconds (Sheet 04 H3, Sheet 06 M3)."""
    exp = min(max_seconds, base_seconds * (2 ** max(0, attempt_count - 1)))
    jitter = random.randint(1, max(2, exp // 4))
    return min(max_seconds, exp + jitter)


def claim_outbox_batch(
    *,
    dispatcher_id: str,
    batch_size: int = 50,
    lease_seconds: int = 120,
    now: timezone.datetime | None = None,
) -> list[uuid.UUID]:
    """Sheet 06 L4: Lease eligible outbox rows inside a short transaction; return IDs to publish to Redis outside transaction."""
    current_time = now or timezone.now()
    lease_until = current_time + timedelta(seconds=lease_seconds)

    with transaction.atomic():
        eligible_ids = list(
            OutboxEvent.objects.select_for_update(skip_locked=True)
            .filter(
                state=OutboxState.PENDING,
                next_attempt_at__lte=current_time,
            )
            .order_by("next_attempt_at", "created_at")
            .values_list("id", flat=True)[:batch_size]
        )
        if eligible_ids:
            OutboxEvent.objects.filter(id__in=eligible_ids).update(
                state=OutboxState.LEASED,
                lease_owner=dispatcher_id,
                lease_expires_at=lease_until,
                updated_at=current_time,
            )
    return eligible_ids


def publish_outbox_batch(
    *,
    dispatcher_id: str | None = None,
    batch_size: int = 50,
    lease_seconds: int = 120,
    broker_publisher: Callable[[uuid.UUID], None] | None = None,
    now: timezone.datetime | None = None,
) -> dict[str, Any]:
    """Sheet 06 L4: Claim batch, publish IDs to Redis outside DB transaction.

    Broker failure retains durable pending/leased intent; publishing does not mark business event complete.
    """
    disp_id = dispatcher_id or f"dispatcher-{uuid.uuid4().hex[:8]}"
    current_time = now or timezone.now()
    claimed_ids = claim_outbox_batch(
        dispatcher_id=disp_id,
        batch_size=batch_size,
        lease_seconds=lease_seconds,
        now=current_time,
    )
    published_ids: list[str] = []
    failed_publish_ids: list[str] = []

    for event_id in claimed_ids:
        try:
            if broker_publisher is not None:
                broker_publisher(event_id)
            else:
                from apps.outbox.tasks import process_outbox_event_task

                process_outbox_event_task.apply_async(args=[str(event_id)], queue="default")
            OutboxEvent.objects.filter(id=event_id, state=OutboxState.LEASED).update(
                state=OutboxState.PUBLISHED,
                updated_at=timezone.now(),
            )
            published_ids.append(str(event_id))
        except Exception as exc:  # Broker failure retains durable intent (Sheet 06 L4)
            OutboxEvent.objects.filter(id=event_id).update(
                state=OutboxState.PENDING,
                lease_owner="",
                lease_expires_at=None,
                last_error=f"Broker publish failed: {exc}",
            )
            failed_publish_ids.append(str(event_id))

    return {
        "dispatcher_id": disp_id,
        "claimed_count": len(claimed_ids),
        "published_ids": published_ids,
        "failed_publish_ids": failed_publish_ids,
    }


def execute_outbox_event(
    *,
    event_id: Any,
    worker_id: str = "worker-default",
    provider_Simulator: Callable[[OutboxEvent], dict[str, Any]] | None = None,
    default_exception_owner: Any = None,
) -> dict[str, Any]:
    """Sheet 06 M1-M3, M6: Claim and recheck durable task, execute bounded external attempt outside DB lock, classify outcome."""
    now = timezone.now()
    lease_until = now + timedelta(seconds=120)

    # M1: Claim and recheck durable task under short lock (do not hold DB locks across network I/O)
    with transaction.atomic():
        event = OutboxEvent.objects.select_for_update().get(pk=event_id)
        if event.state == OutboxState.COMPLETED:
            return {"status": "NO_OP_ALREADY_COMPLETED", "event_id": str(event.id)}
        if event.state == OutboxState.SUPERSEDED_CANCELLED:
            return {"status": "NO_OP_SUPERSEDED", "event_id": str(event.id)}

        # Recheck deadline revision before dispatch (Sheet 04 H1/H3, Sheet 06 M1)
        if event.deadline_id and event.deadline_revision is not None:
            deadline = event.deadline
            if (
                deadline.state in (DeadlineState.COMPLETED, DeadlineState.SUPERSEDED)
                or deadline.current_revision != event.deadline_revision
            ):
                event.state = OutboxState.SUPERSEDED_CANCELLED
                event.lease_owner = ""
                event.lease_expires_at = None
                event.save(update_fields=["state", "lease_owner", "lease_expires_at", "updated_at"])
                LogicalAlert.objects.filter(
                    deadline_id=event.deadline_id,
                    deadline_revision=event.deadline_revision,
                    outcome_state=DeliveryOutcomeState.PENDING,
                ).update(outcome_state=DeliveryOutcomeState.SUPERSEDED_CANCELLED)
                return {"status": "SUPERSEDED_CANCELLED", "event_id": str(event.id)}

        event.state = OutboxState.LEASED
        event.lease_owner = worker_id
        event.lease_expires_at = lease_until
        event.attempt_count += 1
        attempt_num = event.attempt_count
        event.save(update_fields=["state", "lease_owner", "lease_expires_at", "attempt_count", "updated_at"])

    # M2: Execute bounded external attempt OUTSIDE the database transaction
    outcome_type = "SUCCESS"
    provider_receipt = f"rcpt-{event.logical_id}-a{attempt_num}"
    error_detail = ""

    try:
        if provider_Simulator is not None:
            sim_res = provider_Simulator(event)
            outcome_type = sim_res.get("outcome", "SUCCESS")
            provider_receipt = sim_res.get("provider_receipt", provider_receipt)
            error_detail = sim_res.get("error_detail", "")
        else:
            if event.event_type == "DOCUMENT_QUARANTINE_SCAN":
                from apps.documents.services import run_quarantine_scan
                doc = run_quarantine_scan(document_version_id=event.payload["document_version_id"])
                if doc.quarantine_status in {"QUARANTINED", "SCANNING"}:
                    raise RuntimeError("Document scan remains pending.")
            if event.event_type == "COMMUNICATION_DISPATCH":
                outcome_type = "PERMANENT_FAILURE"
                error_detail = "Communication provider and recipient mapping are not configured."
            # In-app alerts already have a durable recipient-visible record.
            alert_id = event.payload.get("logical_alert_id")
            if alert_id:
                alert = LogicalAlert.objects.filter(pk=alert_id).select_related("recipient").first()
                if alert and alert.channel == DeliveryChannel.EMAIL_SMTP and not getattr(settings, "EMAIL_DELIVERY_ENABLED", False):
                    outcome_type = "PERMANENT_FAILURE"
                    error_detail = "SMTP delivery is disabled; no message was sent."
                elif alert and alert.channel == DeliveryChannel.EMAIL_SMTP:
                    send_mail(
                        subject=alert.subject,
                        message=alert.body,
                        from_email=settings.DEFAULT_FROM_EMAIL,
                        recipient_list=[alert.recipient.email or "user@anumati.local"],
                        fail_silently=False,
                    )
    except TimeoutError as exc:
        outcome_type = "TIMEOUT_UNKNOWN"
        error_detail = str(exc)
    except Exception as exc:
        outcome_type = "TRANSIENT_FAILURE"
        error_detail = str(exc)

    # M3 & M6: Classify outcome and persist attempt in a new short transaction
    with transaction.atomic():
        locked = OutboxEvent.objects.select_for_update().get(pk=event_id)
        DeliveryAttempt.objects.create(
            outbox_event=locked,
            attempt_number=attempt_num,
            worker_id=worker_id,
            outcome=outcome_type,
            provider_receipt=provider_receipt if outcome_type == "SUCCESS" else "",
            error_detail=error_detail,
            correlation_id=locked.correlation_id or get_correlation_id(),
        )
        alert_id = locked.payload.get("logical_alert_id")

        if outcome_type == "SUCCESS":
            locked.state = OutboxState.COMPLETED
            locked.completed_at = timezone.now()
            locked.lease_owner = ""
            locked.lease_expires_at = None
            locked.last_error = ""
            locked.save()
            if alert_id:
                # Sheet 04 H4 & Sheet 06 M6: Provider acceptance (SENT/DELIVERED) != recipient reading (READ)
                LogicalAlert.objects.filter(pk=alert_id).update(
                    outcome_state=DeliveryOutcomeState.SENT,
                    provider_receipt_id=provider_receipt,
                )
            return {"status": "COMPLETED", "event_id": str(locked.id), "attempt": attempt_num}

        if outcome_type == "TIMEOUT_UNKNOWN":
            locked.state = OutboxState.UNKNOWN_RECONCILING
            locked.lease_owner = ""
            locked.lease_expires_at = None
            locked.last_error = error_detail or "Timeout after send; outcome unknown"
            locked.save()
            if alert_id:
                LogicalAlert.objects.filter(pk=alert_id).update(
                    outcome_state=DeliveryOutcomeState.UNKNOWN,
                )
            return {"status": "UNKNOWN_RECONCILING", "event_id": str(locked.id), "attempt": attempt_num}

        # Transient or permanent failure
        if outcome_type == "PERMANENT_FAILURE" or locked.attempt_count >= locked.max_attempts:
            locked.state = OutboxState.FAILED_OWNED
            locked.lease_owner = ""
            locked.lease_expires_at = None
            locked.last_error = error_detail or "Retry budget exhausted"
            if default_exception_owner is not None:
                locked.exception_owner = default_exception_owner
            locked.exception_reason = locked.last_error
            locked.save()
            if alert_id:
                LogicalAlert.objects.filter(pk=alert_id).update(
                    outcome_state=DeliveryOutcomeState.FAILED,
                )
            return {"status": "FAILED_OWNED", "event_id": str(locked.id), "attempt": attempt_num}

        backoff_sec = calculate_backoff_with_jitter(locked.attempt_count)
        locked.state = OutboxState.PENDING
        locked.lease_owner = ""
        locked.lease_expires_at = None
        locked.next_attempt_at = timezone.now() + timedelta(seconds=backoff_sec)
        locked.last_error = error_detail
        locked.save()
        return {
            "status": "RETRY_SCHEDULED",
            "event_id": str(locked.id),
            "attempt": attempt_num,
            "next_attempt_at": locked.next_attempt_at.isoformat(),
        }


@transaction.atomic
def reconcile_callback_outcome(
    *,
    external_event_id: str,
    outbox_event_id: Any,
    reported_status: str,
    raw_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Sheet 04 H4 & Sheet 06 M4: Process authenticated callback, deduplicate by external_event_id, and reconcile ambiguous outcomes."""
    existing = CallbackReceipt.objects.filter(external_event_id=external_event_id).first()
    if existing is not None:
        return {
            "deduplicated": True,
            "receipt_id": str(existing.id),
            "outbox_event_id": str(existing.outbox_event_id),
        }

    event = OutboxEvent.objects.select_for_update().get(pk=outbox_event_id)
    receipt = CallbackReceipt.objects.create(
        external_event_id=external_event_id,
        outbox_event=event,
        reported_status=reported_status,
        raw_payload=raw_payload or {},
    )

    alert_id = event.payload.get("logical_alert_id")
    if reported_status in ("DELIVERED", "SENT"):
        event.state = OutboxState.COMPLETED
        event.completed_at = timezone.now()
        event.save(update_fields=["state", "completed_at", "updated_at"])
        if alert_id:
            LogicalAlert.objects.filter(pk=alert_id).update(
                outcome_state=(
                    DeliveryOutcomeState.DELIVERED
                    if reported_status == "DELIVERED"
                    else DeliveryOutcomeState.SENT
                )
            )
    elif reported_status == "FAILED":
        event.state = OutboxState.FAILED_OWNED
        event.exception_reason = "Provider callback reported permanent failure"
        event.save(update_fields=["state", "exception_reason", "updated_at"])
        if alert_id:
            LogicalAlert.objects.filter(pk=alert_id).update(outcome_state=DeliveryOutcomeState.FAILED)

    return {
        "deduplicated": False,
        "receipt_id": str(receipt.id),
        "outbox_state": event.state,
    }


@transaction.atomic
def recover_stranded_outbox_work(now: timezone.datetime | None = None) -> dict[str, Any]:
    """Sheet 05 & Sheet 06 M5: Sweep expired leases and uncompleted published events; requeue safely by stable ID."""
    current_time = now or timezone.now()
    expired_leased_qs = OutboxEvent.objects.select_for_update().filter(
        state__in=[OutboxState.LEASED, OutboxState.PUBLISHED],
        lease_expires_at__lte=current_time,
    )
    requeued_ids = [str(x) for x in expired_leased_qs.values_list("id", flat=True)]
    if requeued_ids:
        OutboxEvent.objects.filter(id__in=requeued_ids).update(
            state=OutboxState.PENDING,
            lease_owner="",
            lease_expires_at=None,
            next_attempt_at=current_time,
            updated_at=current_time,
        )
    return {
        "requeued_count": len(requeued_ids),
        "requeued_ids": requeued_ids,
    }


@transaction.atomic
def operator_replay_failed_event(
    *,
    actor: Any,
    outbox_event_id: Any,
    reason: str,
) -> OutboxEvent:
    """Sheet 04 J5 & Sheet 06 M5: Authorised operator replay of a failed/unknown outbox event preserving logical ID and recording audit."""
    scope = resolve_actor_scope(actor)
    allowed = {RoleCode.TECHNICAL_ADMIN, RoleCode.BUREAU_OFFICER, RoleCode.REGIONAL_OFFICER, RoleCode.COMPETENT_AUTHORITY}
    if not (scope.roles & allowed):
        raise PermissionDenied("Actor is not authorised to replay failed outbox events (Sheet 04 J5).")
    if not reason or not reason.strip():
        raise ValidationError("Operator replay requires an explicit recorded reason (Sheet 04 J5, Sheet 06 M5).")

    event = OutboxEvent.objects.select_for_update().get(pk=outbox_event_id)
    if event.state not in {OutboxState.FAILED_OWNED, OutboxState.UNKNOWN_RECONCILING}:
        raise ValidationError("Only failed or unknown events may be replayed.")
    old_state = event.state
    event.state = OutboxState.PENDING
    event.max_attempts = max(event.max_attempts, event.attempt_count + 1)
    event.next_attempt_at = timezone.now()
    event.lease_owner = ""
    event.lease_expires_at = None
    event.save()

    record_audit_event(
        actor=actor,
        actor_role=",".join(sorted(scope.roles)),
        actor_scope=scope.to_audit_dict(),
        action="OUTBOX_OPERATOR_REPLAY",
        target_type="OutboxEvent",
        target_id=str(event.id),
        case=event.case,
        reason=reason.strip(),
        inputs_snapshot={
            "logical_id": event.logical_id,
            "previous_state": old_state,
            "attempt_count": event.attempt_count,
        },
    )
    return event
