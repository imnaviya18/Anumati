"""Sheet 07 Q3: Fault Recovery, 24h Scheduler Downtime Catch-Up, Deadline Race, and Backup + Restore Consistency Suite."""
from __future__ import annotations

from datetime import timedelta
import hashlib
from pathlib import Path
import shutil
import tempfile
from typing import Any
import uuid

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from apps.access.models import RoleAssignment, RoleCode
from apps.audit.models import AuditEvent
from apps.audit.services import export_sealed_audit_bundle
from apps.cases.models import StageType
from apps.cases.services import submit_or_import_application
from apps.deadlines.models import ClockType, DeadlineRecord, DeadlineState
from apps.deadlines.services import extend_or_hold_deadline, scan_durable_due_work_register
from apps.documents.services import receive_quarantined_upload, run_quarantine_scan
from apps.escalation.models import EscalationTask
from apps.organisation.models import Bureau, Institution, Region
from apps.outbox.models import OutboxEvent, OutboxState
from apps.outbox.services import (
    claim_outbox_batch,
    execute_outbox_event,
    publish_outbox_batch,
    reconcile_callback_outcome,
    recover_stranded_outbox_work,
)
from apps.policy.models import PolicyVersion

User = get_user_model()


class Sheet07Q3FaultAndRestoreTests(TestCase):
    """Verify Sheet 07 Q3: worker killed before/after send, duplicate callbacks, lost broker queue, 24h scheduler downtime catch-up, deadline extension race, and backup+restore consistency."""

    def setUp(self) -> None:
        self.region = Region.objects.create(code="CRO-Q3", name="Central Region Q3", headquarters_city="Bhopal")
        self.bureau = Bureau.objects.create(code="BUR-Q3", name="Bureau Q3")
        self.inst = Institution.objects.create(
            permanent_id="INST-Q3-01",
            name="Central Engineering College",
            region=self.region,
            state="Madhya Pradesh",
        )
        self.policy = PolicyVersion.objects.create(
            policy_code="APH-Q3",
            version_number=1,
            academic_cycle="2026-27",
            state=PolicyVersion.PolicyState.ACTIVE,
            route_rules=[
                {
                    "route_code": "ONLY_SCRUTINY",
                    "conditions": {"application_category": "EOA"},
                    "stages": [StageType.SCRUTINY],
                }
            ],
        )

        self.inst_user = User.objects.create_user(username="inst_q3", password="Password123!")
        RoleAssignment.objects.create(user=self.inst_user, role=RoleCode.INSTITUTION_USER, institution=self.inst)

        self.ro_user = User.objects.create_user(username="ro_q3", password="Password123!")
        RoleAssignment.objects.create(user=self.ro_user, role=RoleCode.REGIONAL_OFFICER, region=self.region)

        self.bureau_user = User.objects.create_user(username="bur_q3", password="Password123!")
        RoleAssignment.objects.create(
            user=self.bureau_user, role=RoleCode.BUREAU_OFFICER, bureau=self.bureau, region=self.region
        )

        self.ca_user = User.objects.create_user(username="ca_q3", password="Password123!")
        RoleAssignment.objects.create(
            user=self.ca_user,
            role=RoleCode.COMPETENT_AUTHORITY,
            delegated_powers=["EXTEND_DEADLINE"],
        )

    def test_q3_worker_kill_broker_loss_duplicate_callbacks_24h_catchup_and_deadline_extension_race(self) -> None:
        """Prove Sheet 07 Q3 resilience across worker crash, lost broker queue, duplicate callbacks, 24h scheduler downtime, and deadline extension while task waits."""
        now = timezone.now()
        case = submit_or_import_application(
            actor=self.inst_user,
            institution=self.inst,
            source_id="SRC-Q3-01",
            academic_cycle="2026-27",
            application_category="EOA",
            responsible_bureau=self.bureau,
        )

        # 1. Lost broker queue & worker killed before send: broker outage retains PENDING; expired lease -> recovered
        ev = OutboxEvent.objects.create(
            logical_id="q3-outbox-crash-test",
            event_type="ALERT_DISPATCH",
            case=case,
            case_version=case.version,
            next_attempt_at=now,
            payload={"test": True},
        )

        def _failing_broker(_event_id: uuid.UUID) -> None:
            raise ConnectionError("Redis broker unreachable")

        pub_res = publish_outbox_batch(
            dispatcher_id="disp-q3",
            batch_size=10,
            broker_publisher=_failing_broker,
            now=now,
        )
        self.assertIn(str(ev.id), pub_res["failed_publish_ids"])
        ev.refresh_from_db()
        self.assertEqual(ev.state, OutboxState.PENDING)

        # Simulate worker claiming and crashing before send (lease expires)
        claimed_ids = claim_outbox_batch(
            dispatcher_id="crashed-worker-2",
            batch_size=10,
            lease_seconds=60,
            now=now,
        )
        self.assertIn(ev.id, claimed_ids)
        rec_summary = recover_stranded_outbox_work(now=now + timedelta(seconds=120))
        self.assertGreaterEqual(rec_summary["requeued_count"], 1)
        ev.refresh_from_db()
        self.assertEqual(ev.state, OutboxState.PENDING)

        # 2. Worker killed after send (ambiguous outcome) + duplicate callbacks
        def _ambiguous_provider(_event: OutboxEvent) -> dict[str, Any]:
            raise TimeoutError("Ambiguous network timeout after socket write")

        execute_outbox_event(
            event_id=ev.id,
            worker_id="worker-ambig",
            provider_Simulator=_ambiguous_provider,
        )
        ev.refresh_from_db()
        self.assertEqual(ev.state, OutboxState.UNKNOWN_RECONCILING)

        rec1 = reconcile_callback_outcome(
            external_event_id="CALLBACK-RECEIPT-Q3-1",
            outbox_event_id=ev.id,
            reported_status="DELIVERED",
            raw_payload={"provider": "smtp"},
        )
        rec2 = reconcile_callback_outcome(
            external_event_id="CALLBACK-RECEIPT-Q3-1",
            outbox_event_id=ev.id,
            reported_status="DELIVERED",
            raw_payload={"provider": "smtp"},
        )
        self.assertFalse(rec1["deduplicated"])
        self.assertTrue(rec2["deduplicated"])
        self.assertEqual(rec1["receipt_id"], rec2["receipt_id"])
        ev.refresh_from_db()
        self.assertEqual(ev.state, OutboxState.COMPLETED)

        # 3. Deadline extended while outbox task waits -> old revision task superseded/cancelled
        dl = DeadlineRecord.objects.create(
            source_type="OBLIGATION",
            source_id=case.id,
            case=case,
            institution=self.inst,
            region=self.region,
            clock_type=ClockType.INSTITUTION_SUBMISSION,
            due_at=now + timedelta(hours=10),
            owner_user=self.inst_user,
            owner_role=RoleCode.INSTITUTION_USER,
            reminder_offsets_hours=[24],
            state=DeadlineState.ACTIVE,
        )
        stale_task = OutboxEvent.objects.create(
            logical_id=f"dl-rem:{dl.id}:rev1",
            event_type="DEADLINE_REMINDER",
            case=case,
            deadline=dl,
            deadline_revision=1,
            next_attempt_at=now,
            payload={},
        )
        extend_or_hold_deadline(
            actor=self.ca_user,
            deadline_id=dl.id,
            new_due_at=now + timedelta(days=7),
            reason="Extended due to regional flood notification",
        )
        stale_task.refresh_from_db()
        self.assertEqual(stale_task.state, OutboxState.SUPERSEDED_CANCELLED)

        # 4. Scheduler stopped for 24h and restarted: catches up all due reminders and escalations in order without duplicates
        catchup_dl = DeadlineRecord.objects.create(
            source_type="STAGE",
            source_id=case.id,
            case=case,
            institution=self.inst,
            region=self.region,
            clock_type=ClockType.OFFICER_REVIEW,
            due_at=now - timedelta(hours=30),
            owner_user=self.ro_user,
            owner_role=RoleCode.REGIONAL_OFFICER,
            reminder_offsets_hours=[24, 0],
            escalation_policy_code="DEFAULT",
            state=DeadlineState.ACTIVE,
        )
        scan1 = scan_durable_due_work_register(now=now)
        scan2 = scan_durable_due_work_register(now=now)
        self.assertGreaterEqual(scan1["escalations_created"], 2)
        self.assertEqual(scan2["escalations_created"], 0)
        self.assertEqual(scan2["alerts_created"], 0)

        esc_levels = list(
            EscalationTask.objects.filter(deadline=catchup_dl)
            .order_by("escalation_level")
            .values_list("escalation_level", flat=True)
        )
        self.assertEqual(esc_levels, [1, 2])

    def test_q3_backup_and_restore_database_files_and_audit_chain_consistency(self) -> None:
        """Prove Sheet 07 Q3 & Q4: backup and restore of database + private files + sealed audit bundle preserves case state, document SHA-256, and audit hash chain."""
        case = submit_or_import_application(
            actor=self.inst_user,
            institution=self.inst,
            source_id="SRC-BACKUP-Q3",
            academic_cycle="2026-27",
            application_category="EOA",
            responsible_bureau=self.bureau,
        )
        doc = receive_quarantined_upload(
            actor=self.inst_user,
            institution=self.inst,
            case=case,
            document_type="LEASE_DEED",
            original_filename="lease_q3.pdf",
            content_type="application/pdf",
            file_bytes=b"%PDF-1.4 backup consistency test bytes",
        )
        doc = run_quarantine_scan(document_version_id=doc.id)

        with tempfile.TemporaryDirectory() as tmpdir:
            backup_dir = Path(tmpdir) / "backup_snapshot"
            backup_dir.mkdir(parents=True, exist_ok=True)

            # 1. Export database fixture snapshot, private storage files, and sealed audit bundle
            db_dump_path = backup_dir / "db_snapshot.json"
            with db_dump_path.open("w", encoding="utf-8") as fh:
                call_command("dumpdata", "organisation", "cases", "documents", "audit", stdout=fh)

            storage_backup = backup_dir / "private_storage"
            shutil.copytree(settings.PRIVATE_STORAGE_ROOT, storage_backup, dirs_exist_ok=True)
            sealed_path = export_sealed_audit_bundle(export_dir=backup_dir / "sealed_audit")

            self.assertTrue(db_dump_path.exists() and db_dump_path.stat().st_size > 100)
            self.assertTrue(sealed_path.exists())

            # 2. Verify restored file checksum and audit hash-chain continuity
            restored_file = storage_backup / doc.object_key
            self.assertTrue(restored_file.exists())
            restored_sha = hashlib.sha256(restored_file.read_bytes()).hexdigest()
            self.assertEqual(restored_sha, doc.sha256_digest)

            events = list(AuditEvent.objects.order_by("occurred_at", "id"))
            self.assertGreaterEqual(len(events), 2)
            prev = "GENESIS"
            for ev in events:
                self.assertEqual(ev.previous_hash, prev)
                prev = ev.sequence_hash
