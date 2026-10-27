"""Stage 3 Tests: Celery/Redis Dispatcher, Leases, Retries, Stranded Recovery, Reconciliation & Quarantine Pipeline (Sheet 03 E1-E3, Sheet 05, Sheet 06 L4, M1-M6, Sheet 07 P2, Q2, Q3)."""
from datetime import timedelta
import tempfile

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.utils import timezone

from apps.access.models import RoleCode
from apps.access.services import assign_role_to_user
from apps.deadlines.models import ClockType, DeadlineRecord, DeadlineState
from apps.documents.models import QuarantineStatus, ReviewAcceptanceStatus
from apps.documents.services import (
    issue_short_lived_download_grant,
    receive_quarantined_upload,
    redeem_download_grant,
    review_and_accept_document_version,
    run_quarantine_scan,
)
from apps.notifications.models import DeliveryChannel, DeliveryOutcomeState, LogicalAlert
from apps.organisation.models import Institution
from apps.organisation.services import create_institution, create_region
from apps.outbox.models import OutboxEvent, OutboxState
from apps.outbox.selectors import select_operations_metrics
from apps.outbox.services import (
    execute_outbox_event,
    operator_replay_failed_event,
    publish_outbox_batch,
    reconcile_callback_outcome,
    recover_stranded_outbox_work,
)

User = get_user_model()


class Stage3OutboxRecoveryAndQuarantineTests(TestCase):
    def setUp(self) -> None:
        call_command("bootstrap_anumati")
        self.tech_admin = User.objects.get(username="tech_admin")
        self.region = create_region(
            actor=self.tech_admin,
            code="EAST",
            name="Eastern Regional Office",
            headquarters_city="Kolkata",
        )
        self.inst_east = create_institution(
            actor=self.tech_admin,
            permanent_id="1-EAST-4001",
            name="Eastern Institute of Engineering",
            region=self.region,
            category=Institution.InstitutionCategory.PRIVATE_SELF_FINANCING,
            state="West Bengal",
        )
        self.inst_other = create_institution(
            actor=self.tech_admin,
            permanent_id="1-EAST-4002",
            name="Other Institute",
            region=self.region,
            category=Institution.InstitutionCategory.PRIVATE_SELF_FINANCING,
            state="West Bengal",
        )
        self.user_inst = User.objects.create_user(username="inst_east", password="pw")
        self.user_other_inst = User.objects.create_user(username="inst_other", password="pw")
        self.user_ro = User.objects.create_user(username="ro_east", password="pw")

        assign_role_to_user(
            actor=self.tech_admin,
            target_user=self.user_inst,
            role=RoleCode.INSTITUTION_USER,
            institution=self.inst_east,
            reason="Assign East Institution User",
        )
        assign_role_to_user(
            actor=self.tech_admin,
            target_user=self.user_other_inst,
            role=RoleCode.INSTITUTION_USER,
            institution=self.inst_other,
            reason="Assign Other Institution User",
        )
        assign_role_to_user(
            actor=self.tech_admin,
            target_user=self.user_ro,
            role=RoleCode.REGIONAL_OFFICER,
            region=self.region,
            reason="Assign East RO",
        )

    def test_outbox_leases_retries_failed_owner_replay_and_reconciliation(self) -> None:
        """Verify Sheet 06 L4, M1-M6: broker failure retains intent, transient failure retries with backoff+jitter, exhausted enters failed queue, operator replay is audited, ambiguous outcome reconciled."""
        now = timezone.now()
        dl = DeadlineRecord.objects.create(
            source_type="STAGE",
            source_id=self.inst_east.id,
            institution=self.inst_east,
            region=self.region,
            clock_type=ClockType.INSTITUTION_SUBMISSION,
            due_at=now + timedelta(days=7),
            current_revision=1,
            state=DeadlineState.ACTIVE,
        )
        alert = LogicalAlert.objects.create(
            deadline=dl,
            deadline_revision=1,
            milestone_code="REMINDER_7D",
            institution=self.inst_east,
            recipient=self.user_inst,
            channel=DeliveryChannel.IN_APP,
            subject="Upcoming Deadline",
            body="Please submit documents.",
            outcome_state=DeliveryOutcomeState.PENDING,
        )
        ev = OutboxEvent.objects.create(
            logical_id="alert:test-1",
            event_type="DELIVER_ALERT",
            deadline=dl,
            deadline_revision=1,
            payload={"logical_alert_id": str(alert.id)},
            state=OutboxState.PENDING,
            max_attempts=2,
            next_attempt_at=now,
        )

        # 1. Broker failure during publish retains PENDING state (Sheet 06 L4)
        def failing_broker(_event_id):
            raise ConnectionError("Redis broker unreachable")

        pub_fail = publish_outbox_batch(broker_publisher=failing_broker, now=now)
        self.assertEqual(len(pub_fail["failed_publish_ids"]), 1)
        ev.refresh_from_db()
        self.assertEqual(ev.state, OutboxState.PENDING)

        # 2. Successful publish transitions to PUBLISHED (not COMPLETED — Sheet 05 & 06 L4)
        published_box = []
        pub_ok = publish_outbox_batch(broker_publisher=lambda eid: published_box.append(eid), now=now)
        self.assertEqual(len(pub_ok["published_ids"]), 1)
        ev.refresh_from_db()
        self.assertEqual(ev.state, OutboxState.PUBLISHED)

        # 3. Simulate worker crash / expired lease -> recover_stranded_outbox_work requeues to PENDING (Sheet 06 M5)
        ev.lease_expires_at = now - timedelta(seconds=10)
        ev.save()
        rec = recover_stranded_outbox_work(now=now)
        self.assertIn(str(ev.id), rec["requeued_ids"])
        ev.refresh_from_db()
        self.assertEqual(ev.state, OutboxState.PENDING)

        # 4. Attempt 1: Transient failure schedules retry with backoff + jitter (Sheet 06 M3)
        att1 = execute_outbox_event(
            event_id=ev.id,
            provider_Simulator=lambda _e: {"outcome": "TRANSIENT_FAILURE", "error_detail": "SMTP temporary 421"},
        )
        self.assertEqual(att1["status"], "RETRY_SCHEDULED")
        ev.refresh_from_db()
        self.assertEqual(ev.state, OutboxState.PENDING)
        self.assertEqual(ev.attempt_count, 1)

        # 5. Attempt 2 (reaches max_attempts=2): Moves to FAILED_OWNED with exception_owner (Sheet 04 J4, Sheet 06 M3)
        att2 = execute_outbox_event(
            event_id=ev.id,
            provider_Simulator=lambda _e: {"outcome": "TRANSIENT_FAILURE", "error_detail": "SMTP timeout"},
            default_exception_owner=self.tech_admin,
        )
        self.assertEqual(att2["status"], "FAILED_OWNED")
        ev.refresh_from_db()
        self.assertEqual(ev.state, OutboxState.FAILED_OWNED)
        self.assertEqual(ev.exception_owner, self.tech_admin)

        # 6. Operator replay resets to PENDING, preserves logical_id, and records audit (Sheet 04 J5, Sheet 06 M5)
        operator_replay_failed_event(
            actor=self.tech_admin,
            outbox_event_id=ev.id,
            reason="Mail server restored; replaying failed notification.",
        )
        ev.refresh_from_db()
        self.assertEqual(ev.state, OutboxState.PENDING)
        self.assertEqual(ev.logical_id, "alert:test-1")

        # 7. Attempt 3: Timeout after send -> UNKNOWN_RECONCILING, then reconciled by deduplicated callback (Sheet 06 M3-M4)
        att3 = execute_outbox_event(
            event_id=ev.id,
            provider_Simulator=lambda _e: {"outcome": "TIMEOUT_UNKNOWN", "error_detail": "Socket timeout after DATA"},
        )
        self.assertEqual(att3["status"], "UNKNOWN_RECONCILING")
        alert.refresh_from_db()
        self.assertEqual(alert.outcome_state, DeliveryOutcomeState.UNKNOWN)

        cb1 = reconcile_callback_outcome(
            external_event_id="provider-cb-999",
            outbox_event_id=ev.id,
            reported_status="DELIVERED",
        )
        self.assertFalse(cb1["deduplicated"])
        ev.refresh_from_db()
        alert.refresh_from_db()
        self.assertEqual(ev.state, OutboxState.COMPLETED)
        self.assertEqual(alert.outcome_state, DeliveryOutcomeState.DELIVERED)
        self.assertIsNone(alert.read_at)  # Provider acceptance != recipient reading (Sheet 04 H4)

        # Duplicate callback is safely deduplicated (Sheet 06 M4, Sheet 07 Q3)
        cb2 = reconcile_callback_outcome(
            external_event_id="provider-cb-999",
            outbox_event_id=ev.id,
            reported_status="DELIVERED",
        )
        self.assertTrue(cb2["deduplicated"])

        # 8. Deadline revision change supersedes queued outbox task before send (Sheet 04 H1/H3, Sheet 06 M1, Sheet 07 Q3)
        ev_sup = OutboxEvent.objects.create(
            logical_id="alert:test-superseded",
            event_type="DELIVER_ALERT",
            deadline=dl,
            deadline_revision=1,
            payload={},
            state=OutboxState.PENDING,
            next_attempt_at=now,
        )
        dl.current_revision = 2
        dl.save()
        sup_res = execute_outbox_event(event_id=ev_sup.id)
        self.assertEqual(sup_res["status"], "SUPERSEDED_CANCELLED")

        metrics = select_operations_metrics()
        self.assertIn("outbox_backlog", metrics)
        self.assertIn("stale_leases", metrics)

    def test_quarantine_pipeline_scan_outage_and_download_isolation(self) -> None:
        """Verify Sheet 03 E1-E3, Sheet 07 P2, Q2: quarantine upload, scanner outage retention, dirty file rejection, short-lived download grant, and separate human acceptance."""
        with tempfile.TemporaryDirectory() as tmp_storage:
            with override_settings(PRIVATE_STORAGE_ROOT=tmp_storage):
                valid_pdf = b"%PDF-1.7\n1 0 obj\n<<>>\nendobj\n%%EOF"
                received_ts = timezone.now() - timedelta(hours=2)

                # 1. Receive upload -> starts QUARANTINED and preserves received_at
                doc = receive_quarantined_upload(
                    actor=self.user_inst,
                    institution=self.inst_east,
                    document_type="AFFIDAVIT_2",
                    original_filename="affidavit2.pdf",
                    content_type="application/pdf",
                    file_bytes=valid_pdf,
                    received_at=received_ts,
                )
                self.assertEqual(doc.quarantine_status, QuarantineStatus.QUARANTINED)
                self.assertEqual(doc.acceptance_status, ReviewAcceptanceStatus.PENDING_REVIEW)
                self.assertEqual(doc.received_at, received_ts)

                # Quarantined file cannot be downloaded or accepted by reviewer yet (Sheet 07 P2, Q2)
                with self.assertRaises(PermissionDenied):
                    issue_short_lived_download_grant(actor=self.user_ro, document_version_id=doc.id)
                with self.assertRaises(ValidationError):
                    review_and_accept_document_version(
                        actor=self.user_ro,
                        document_version_id=doc.id,
                        accept=True,
                        finding="Premature accept",
                    )

                # 2. Scanner outage preserves QUARANTINED state (pending scan != rejection — Sheet 03 E1, Sheet 07 P2, Q2)
                run_quarantine_scan(document_version_id=doc.id, simulate_scanner_outage=True)
                doc.refresh_from_db()
                self.assertEqual(doc.quarantine_status, QuarantineStatus.QUARANTINED)

                # 3. Clean scan transitions to CLEAN while preserving original received_at AND keeping acceptance_status PENDING_REVIEW
                run_quarantine_scan(document_version_id=doc.id, simulate_scanner_outage=False)
                doc.refresh_from_db()
                self.assertEqual(doc.quarantine_status, QuarantineStatus.CLEAN)
                self.assertEqual(doc.received_at, received_ts)
                self.assertEqual(doc.acceptance_status, ReviewAcceptanceStatus.PENDING_REVIEW)

                # 4. Cross-institution user is denied download grant (Sheet 07 Q2)
                with self.assertRaises(PermissionDenied):
                    issue_short_lived_download_grant(actor=self.user_other_inst, document_version_id=doc.id)

                # Authorised Regional Officer can obtain and redeem a short-lived download grant
                grant = issue_short_lived_download_grant(
                    actor=self.user_ro,
                    document_version_id=doc.id,
                    ttl_seconds=60,
                )
                redeemed_doc, downloaded_bytes = redeem_download_grant(actor=self.user_ro, token=grant.token)
                self.assertEqual(redeemed_doc.id, doc.id)
                self.assertEqual(downloaded_bytes, valid_pdf)

                # Expired grant is rejected
                with self.assertRaises(PermissionDenied):
                    redeem_download_grant(
                        actor=self.user_ro,
                        token=grant.token,
                        now=timezone.now() + timedelta(seconds=120),
                    )

                # 5. Human compliance acceptance is recorded separately (Sheet 03 E3-E4, Sheet 07 P2)
                review_and_accept_document_version(
                    actor=self.user_ro,
                    document_version_id=doc.id,
                    accept=True,
                    finding="Affidavit-2 verified against e-stamp and notary seal.",
                )
                doc.refresh_from_db()
                self.assertEqual(doc.acceptance_status, ReviewAcceptanceStatus.ACCEPTED)

                # 6. Spoofed / invalid file signature is marked REJECTED and unavailable for download (Sheet 07 Q2)
                bad_doc = receive_quarantined_upload(
                    actor=self.user_inst,
                    institution=self.inst_east,
                    document_type="BUILDING_PLAN",
                    original_filename="spoofed.pdf",
                    content_type="application/pdf",
                    file_bytes=b"MZ-executable-spoofed-as-pdf",
                )
                run_quarantine_scan(document_version_id=bad_doc.id)
                bad_doc.refresh_from_db()
                self.assertEqual(bad_doc.quarantine_status, QuarantineStatus.REJECTED)
                with self.assertRaises(PermissionDenied):
                    issue_short_lived_download_grant(actor=self.user_ro, document_version_id=bad_doc.id)
