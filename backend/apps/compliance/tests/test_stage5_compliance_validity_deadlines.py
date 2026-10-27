"""Stage 5 Tests: Continuing Obligations, Separate Submission/Verification/Lateness Facts, Document Validity & Renewals, Separate Clocks, Deadline Extensions & Multi-Level Escalations (Sheets 03, 04 H1-H5, 06 M6, 07 N2-N3)."""
from datetime import date, timedelta
import tempfile

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.utils import timezone

from apps.access.models import RoleCode
from apps.access.services import assign_role_to_user
from apps.compliance.models import ObligationState
from apps.compliance.services import (
    import_pre_existing_obligation,
    register_accepted_validity_document,
    review_and_decide_document_renewal,
    submit_document_renewal,
    submit_obligation_evidence,
    verify_obligation_evidence,
)
from apps.deadlines.services import (
    close_escalation_task,
    extend_or_hold_deadline,
    scan_durable_due_work_register,
)
from apps.documents.models import ReviewAcceptanceStatus, ValidityMonitorState
from apps.documents.services import receive_quarantined_upload, run_quarantine_scan
from apps.escalation.models import EscalationState, EscalationTask
from apps.organisation.models import Institution
from apps.organisation.services import create_institution, create_region
from apps.outbox.services import execute_outbox_event

User = get_user_model()


class Stage5ComplianceValidityDeadlinesEscalationTests(TestCase):
    def setUp(self) -> None:
        call_command("bootstrap_anumati")
        self.tech_admin = User.objects.get(username="tech_admin")
        self.region = create_region(
            actor=self.tech_admin,
            code="SWRO",
            name="South Western Regional Office",
            headquarters_city="Bengaluru",
        )
        self.inst = create_institution(
            actor=self.tech_admin,
            permanent_id="1-SWRO-6001",
            name="Bengaluru Technical College",
            region=self.region,
            category=Institution.InstitutionCategory.PRIVATE_SELF_FINANCING,
            state="Karnataka",
        )
        self.user_inst = User.objects.create_user(username="inst_swro", password="pw")
        self.user_ro = User.objects.create_user(username="ro_swro", password="pw")
        self.user_bureau = User.objects.create_user(username="bureau_swro", password="pw")
        self.user_ca = User.objects.create_user(username="ca_swro", password="pw")

        assign_role_to_user(
            actor=self.tech_admin,
            target_user=self.user_inst,
            role=RoleCode.INSTITUTION_USER,
            institution=self.inst,
            reason="Assign SWRO Institution User",
        )
        assign_role_to_user(
            actor=self.tech_admin,
            target_user=self.user_ro,
            role=RoleCode.REGIONAL_OFFICER,
            region=self.region,
            reason="Assign SWRO Regional Officer",
        )
        assign_role_to_user(
            actor=self.tech_admin,
            target_user=self.user_bureau,
            role=RoleCode.BUREAU_OFFICER,
            region=self.region,
            reason="Assign Bureau Officer",
        )
        assign_role_to_user(
            actor=self.tech_admin,
            target_user=self.user_ca,
            role=RoleCode.COMPETENT_AUTHORITY,
            delegated_powers=["EXTEND_DEADLINE"],
            reason="Assign Competent Authority",
        )

    def test_obligations_separate_submission_and_verification_lateness_facts(self) -> None:
        """Prove submission, verification, and lateness are stored as separate facts, and timely submission != timely verification (Sheet 03 E2-E4, Sheet 07 N2)."""
        with tempfile.TemporaryDirectory() as tmp_storage:
            with override_settings(PRIVATE_STORAGE_ROOT=tmp_storage):
                now = timezone.now()
                due_at = now + timedelta(days=5)

                # 1. Authorised import of pre-existing obligation (Sheet 03 D1)
                oblig = import_pre_existing_obligation(
                    actor=self.user_ro,
                    institution=self.inst,
                    source_command_ref="IMPORT-CMD-2026-01",
                    obligation_code="UHV_FACULTY_UNDERTAKING",
                    condition_text="Possess UHV trained faculty for every 20 students (APH 6.54).",
                    evidence_requirement="Signed undertaking on letterhead + faculty certificates",
                    due_at=due_at,
                )
                self.assertEqual(oblig.state, ObligationState.OPEN)

                # 2. Institution uploads evidence ON TIME (2 days before due_at), scanned asynchronously
                on_time_receipt = due_at - timedelta(days=2)
                doc_v1 = receive_quarantined_upload(
                    actor=self.user_inst,
                    institution=self.inst,
                    document_type="UNDERTAKING_EVIDENCE",
                    original_filename="uhv_partial.pdf",
                    content_type="application/pdf",
                    file_bytes=b"%PDF-1.7 partial evidence",
                    received_at=on_time_receipt,
                )
                run_quarantine_scan(document_version_id=doc_v1.id)

                sub1 = submit_obligation_evidence(
                    actor=self.user_inst,
                    obligation_id=oblig.id,
                    document_version_id=doc_v1.id,
                    review_sla_days=3,
                )
                oblig.refresh_from_db()
                # Submission ≠ verified fulfilment (Sheet 01 Block 04, Sheet 03 E1-E4)
                self.assertEqual(oblig.state, ObligationState.EVIDENCE_SUBMITTED)
                self.assertFalse(oblig.is_submission_late)
                self.assertIsNone(oblig.verified_at)

                # 3. Officer reviews LATE (10 days after review_deadline_at) and records deficiency -> CLARIFICATION_REQUIRED
                late_review_time = (sub1.review_deadline_at or now) + timedelta(days=10)
                verify_obligation_evidence(
                    actor=self.user_ro,
                    submission_id=sub1.id,
                    fulfilled=False,
                    finding_notes="Only 2 faculty certificates attached instead of required 6.",
                    reviewed_at=late_review_time,
                )
                oblig.refresh_from_db()
                self.assertEqual(oblig.state, ObligationState.CLARIFICATION_REQUIRED)
                self.assertFalse(oblig.is_submission_late)
                self.assertTrue(oblig.is_verification_late)

                # 4. Institution resubmits complete evidence AFTER original due_at, officer accepts on time
                late_receipt = due_at + timedelta(days=4)
                doc_v2 = receive_quarantined_upload(
                    actor=self.user_inst,
                    institution=self.inst,
                    document_type="UNDERTAKING_EVIDENCE",
                    original_filename="uhv_complete.pdf",
                    content_type="application/pdf",
                    file_bytes=b"%PDF-1.7 complete 6 faculty certificates",
                    received_at=late_receipt,
                )
                run_quarantine_scan(document_version_id=doc_v2.id)
                sub2 = submit_obligation_evidence(
                    actor=self.user_inst,
                    obligation_id=oblig.id,
                    document_version_id=doc_v2.id,
                    review_sla_days=5,
                )
                verify_obligation_evidence(
                    actor=self.user_ro,
                    submission_id=sub2.id,
                    fulfilled=True,
                    finding_notes="All 6 UHV faculty certificates verified.",
                    reviewed_at=timezone.now(),
                )
                oblig.refresh_from_db()
                self.assertEqual(oblig.state, ObligationState.FULFILLED)
                self.assertTrue(oblig.is_submission_late)
                self.assertFalse(oblig.is_verification_late)
                self.assertEqual(oblig.accepted_evidence_version_id, doc_v2.id)

    def test_document_validity_new_upload_never_replaces_accepted_until_human_acceptance(self) -> None:
        """Prove Sheet 03 F1-F5 & PS Section E: a new renewal upload never replaces accepted validity until accepted by a human reviewer."""
        with tempfile.TemporaryDirectory() as tmp_storage:
            with override_settings(PRIVATE_STORAGE_ROOT=tmp_storage):
                doc_initial = receive_quarantined_upload(
                    actor=self.user_inst,
                    institution=self.inst,
                    document_type="FIRE_SAFETY_CERTIFICATE",
                    original_filename="fire_2025.pdf",
                    content_type="application/pdf",
                    file_bytes=b"%PDF-1.7 initial fire safety certificate",
                )
                run_quarantine_scan(document_version_id=doc_initial.id)

                val_rec = register_accepted_validity_document(
                    actor=self.user_ro,
                    institution=self.inst,
                    document_type="FIRE_SAFETY_CERTIFICATE",
                    accepted_version_id=doc_initial.id,
                    valid_from=date(2025, 1, 1),
                    valid_until=date(2026, 12, 31),
                )
                self.assertEqual(val_rec.accepted_version_id, doc_initial.id)

                # Upload renewal v2 (rejected in review) -> accepted_version MUST remain doc_initial
                doc_renewal_bad = receive_quarantined_upload(
                    actor=self.user_inst,
                    institution=self.inst,
                    document_type="FIRE_SAFETY_CERTIFICATE",
                    original_filename="fire_unsigned.pdf",
                    content_type="application/pdf",
                    file_bytes=b"%PDF-1.7 unsigned renewal",
                )
                run_quarantine_scan(document_version_id=doc_renewal_bad.id)
                submit_document_renewal(
                    actor=self.user_inst,
                    validity_record_id=val_rec.id,
                    new_document_version_id=doc_renewal_bad.id,
                )
                val_rec.refresh_from_db()
                self.assertEqual(val_rec.state, ValidityMonitorState.PENDING_RENEWAL_REVIEW)
                self.assertEqual(val_rec.accepted_version_id, doc_initial.id)
                self.assertEqual(val_rec.pending_renewal_version_id, doc_renewal_bad.id)

                # Reject renewal -> accepted_version still remains doc_initial
                review_and_decide_document_renewal(
                    actor=self.user_ro,
                    validity_record_id=val_rec.id,
                    accept=False,
                    new_valid_from=None,
                    new_valid_until=None,
                    finding_notes="Missing Competent Authority seal on renewal.",
                )
                val_rec.refresh_from_db()
                self.assertEqual(val_rec.accepted_version_id, doc_initial.id)
                self.assertIsNone(val_rec.pending_renewal_version_id)

                # Upload renewal v3 and accept -> old version retained in previous_accepted_versions, accepted_version updated
                doc_renewal_good = receive_quarantined_upload(
                    actor=self.user_inst,
                    institution=self.inst,
                    document_type="FIRE_SAFETY_CERTIFICATE",
                    original_filename="fire_2027_signed.pdf",
                    content_type="application/pdf",
                    file_bytes=b"%PDF-1.7 signed renewal 2027",
                )
                run_quarantine_scan(document_version_id=doc_renewal_good.id)
                submit_document_renewal(
                    actor=self.user_inst,
                    validity_record_id=val_rec.id,
                    new_document_version_id=doc_renewal_good.id,
                )
                review_and_decide_document_renewal(
                    actor=self.user_ro,
                    validity_record_id=val_rec.id,
                    accept=True,
                    new_valid_from=date(2027, 1, 1),
                    new_valid_until=date(2029, 12, 31),
                    finding_notes="Verified Fire Department seal and validity dates.",
                )
                val_rec.refresh_from_db()
                self.assertEqual(val_rec.accepted_version_id, doc_renewal_good.id)
                self.assertEqual(val_rec.valid_until, date(2029, 12, 31))
                self.assertEqual(len(val_rec.previous_accepted_versions), 1)
                self.assertEqual(val_rec.previous_accepted_versions[0]["version_id"], str(doc_initial.id))
                doc_renewal_good.refresh_from_db()
                self.assertEqual(doc_renewal_good.acceptance_status, ReviewAcceptanceStatus.ACCEPTED)

    def test_deadline_extension_preserves_history_and_escalation_levels_fire_in_order_and_stop_on_closure(self) -> None:
        """Prove Sheet 03 D2-D4, Sheet 04 H1-H5, Sheet 06 M6: deadline extension preserves history; 24h scheduler catch-up fires escalations in order; sent alert != closure; explicit closure stops further escalations."""
        base_time = timezone.now()
        initial_due = base_time + timedelta(days=2)

        oblig = import_pre_existing_obligation(
            actor=self.user_ro,
            institution=self.inst,
            source_command_ref="IMPORT-ESC-01",
            obligation_code="LAB_EQUIPMENT_INVOICE",
            condition_text="Upload lab equipment invoices",
            evidence_requirement="Invoices PDF",
            due_at=initial_due,
            reminder_offsets_hours=[48, 0],
        )
        dl = oblig.active_deadline
        assert dl is not None

        # 1. Extend deadline -> revision increments to 2 and preserves old due_at in DeadlineRevision
        extended_due = initial_due + timedelta(days=3)
        extend_or_hold_deadline(
            actor=self.user_ca,
            deadline_id=dl.id,
            new_due_at=extended_due,
            reason="Granted 3-day extension due to bank holiday.",
        )
        dl.refresh_from_db()
        self.assertEqual(dl.current_revision, 2)
        self.assertEqual(dl.revisions.count(), 1)
        rev_rec = dl.revisions.first()
        assert rev_rec is not None
        self.assertEqual(rev_rec.previous_due_at, initial_due)
        self.assertEqual(rev_rec.new_due_at, extended_due)

        # 2. Simulate overdue at +1 hour past extended_due -> Level 1 escalation fires
        scan1 = scan_durable_due_work_register(now=extended_due + timedelta(hours=1))
        self.assertGreaterEqual(scan1["escalations_created"], 1)
        esc_l1 = EscalationTask.objects.get(deadline=dl, deadline_revision=2, escalation_level=1)
        self.assertEqual(esc_l1.state, EscalationState.OPEN)

        # Execute outbox delivery for the escalation alert -> proves sent alert does NOT close escalation (Sheet 06 M6)
        for ev in dl.outbox_events.all():
            execute_outbox_event(event_id=ev.id)
        esc_l1.refresh_from_db()
        self.assertEqual(esc_l1.state, EscalationState.OPEN)

        # 3. Simulate scheduler stopped for 24 hours (now at +30 hours overdue) -> catch-up scan fires Level 2 and marks Level 1 ESCALATED_NEXT_LEVEL
        scan_durable_due_work_register(now=extended_due + timedelta(hours=30))
        esc_l1.refresh_from_db()
        self.assertEqual(esc_l1.state, EscalationState.ESCALATED_NEXT_LEVEL)
        esc_l2 = EscalationTask.objects.get(deadline=dl, deadline_revision=2, escalation_level=2)
        self.assertEqual(esc_l2.state, EscalationState.OPEN)

        # 4. Authorised officer closes escalation before Level 3 (72h) -> subsequent scan at +80h does NOT fire Level 3
        close_escalation_task(
            actor=self.user_bureau,
            escalation_id=esc_l2.id,
            closure_reason="Institution submitted verified undertaking; escalation resolved.",
        )
        esc_l2.refresh_from_db()
        self.assertEqual(esc_l2.state, EscalationState.CLOSED)

        scan_after_close = scan_durable_due_work_register(now=extended_due + timedelta(hours=80))
        self.assertEqual(scan_after_close["escalations_created"], 0)
        self.assertFalse(
            EscalationTask.objects.filter(deadline=dl, deadline_revision=2, escalation_level=3).exists()
        )
