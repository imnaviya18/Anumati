"""Owned, audited mock-source reconciliation. Never mutates regulatory records."""
import hashlib
import json
from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import APIException
from apps.audit.services import record_audit_event
from apps.policy.models import SourceRecord, SyncException
from apps.policy.services import _assert_policy_governor


class SyncConflict(APIException):
    status_code = 409
    default_detail = "The record changed. Reload before resolving this exception."


def audit(actor, scope, item, action, reason, snapshot):
    record_audit_event(actor=actor, actor_role=','.join(sorted(scope.roles)),
        actor_scope=scope.to_audit_dict(), action=action, target_type="SyncException",
        target_id=str(item.id), reason=reason, inputs_snapshot=snapshot)


@transaction.atomic
def ingest_mock_event(*, actor, event_id, source_id, payload, reason):
    scope = _assert_policy_governor(actor)
    if not settings.DEBUG or not settings.ALLOW_DEMONSTRATION_POLICIES:
        raise PermissionDenied("Mock ingestion is available only in the local demonstration.")
    if not event_id.strip() or not source_id.strip() or not reason.strip():
        raise ValidationError("Event ID, source record ID and reason are required.")
    if not isinstance(payload, dict) or not payload or set(payload) - {"display_name", "reference", "notes"}:
        raise ValidationError("Mock reference payload accepts display_name, reference and notes only.")
    if any(not isinstance(v, str) or len(v) > 2000 for v in payload.values()):
        raise ValidationError("Reference fields must be strings of at most 2000 characters.")
    fingerprint = hashlib.sha256(json.dumps({"source_id":source_id,"payload":payload},sort_keys=True).encode()).hexdigest()
    # Lock the source row to serialize ingest and reconcile for a given source identity.
    record, _ = SourceRecord.objects.get_or_create(source_system="LOCAL_MOCK", source_id=source_id)
    record = SourceRecord.objects.select_for_update().get(pk=record.pk)
    previous = SyncException.objects.filter(source_system="LOCAL_MOCK", event_id=event_id).first()
    if previous:
        if previous.fingerprint != fingerprint:
            raise SyncConflict("Event ID was already used for different source data.")
        return previous
    item = SyncException.objects.create(source_record=record, source_system="LOCAL_MOCK",
        event_id=event_id, fingerprint=fingerprint, baseline_version=record.version,
        local_snapshot=record.payload, incoming_snapshot=payload, owner=actor, reason=reason)
    audit(actor, scope, item, "SYNC_EXCEPTION_OPENED", reason,
        {"source_system":"LOCAL_MOCK","event_id":event_id,"before":record.payload,"incoming":payload})
    return item


@transaction.atomic
def reconcile(*, actor, exception_id, expected_version, action, reason, owner=None):
    scope = _assert_policy_governor(actor)
    item = SyncException.objects.get(pk=exception_id)
    record = SourceRecord.objects.select_for_update().get(pk=item.source_record_id)
    item = SyncException.objects.select_for_update().get(pk=item.pk)
    if item.version != expected_version:
        raise SyncConflict()
    if item.state != "OPEN":
        raise ValidationError("This exception has already been resolved.")
    if not reason.strip():
        raise ValidationError("A reconciliation reason is mandatory.")
    before = {"state":item.state,"owner_id":item.owner_id,"record_version":record.version,"payload":record.payload}
    if action == "REASSIGN":
        if owner is None or not owner.is_active:
            raise ValidationError("Select an active policy governor as owner.")
        _assert_policy_governor(owner)
        item.owner = owner
    elif action in {"KEEP_LOCAL", "ACCEPT_SOURCE"}:
        if action == "ACCEPT_SOURCE":
            if record.version != item.baseline_version:
                raise SyncConflict("A newer reconciliation changed this source record. Keep local and submit a fresh source event for review.")
            record.payload = item.incoming_snapshot
            record.version += 1
            record.save(update_fields=["payload","version","updated_at"])
        item.state = "RESOLVED"
        item.resolution = action
        item.resolution_reason = reason
        item.resolved_by = actor
        item.resolved_at = timezone.now()
    else:
        raise ValidationError("Unknown reconciliation action.")
    item.version += 1
    item.save()
    audit(actor, scope, item, "SYNC_EXCEPTION_" + action, reason,
        {"before":before,"after":{"state":item.state,"owner_id":item.owner_id,"payload":record.payload,"record_version":record.version}})
    return item
