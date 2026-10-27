"""Architectural edge case test suite for ANUMATI v2.
Verifies boundary conditions, error handling, conflict resolution,
and concurrency/idempotency guarantees across Sheets 01 through 07.
"""
from datetime import date, timedelta
import tempfile
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.utils import timezone

from apps.access.models import CaseAssignment, RoleCode
from apps.access.services import assign_role_to_user, create_case_assignment
from apps.cases.models import (
    CaseStatus,
    DeficiencyCycle,
    StageInstance,
    StageStatus,
    StageType,
)
from apps.cases.services import (
    submit_deficiency_response,
    submit_or_import_application,
)
from django.db import IntegrityError, DatabaseError
from apps.compliance.services import (
    register_accepted_validity_document,
    review_and_decide_document_renewal,
    submit_document_renewal,
)
from apps.deadlines.models import ClockType, DeadlineRecord
from apps.deadlines.services import extend_or_hold_deadline
from apps.decisions.models import DecisionOutcome
from apps.decisions.services import (
    IdempotencyConflictError,
    StaleCaseVersionError,
    execute_guarded_decision_command,
    execute_guarded_stage_transition_command,
)
from apps.documents.models import (
    ValidityMonitorState,
)
from apps.documents.services import receive_quarantined_upload, run_quarantine_scan
from apps.evc.models import EvcMode, EvcStatus
from apps.evc.services import (
    check_evc_readiness_and_queue,
    reserve_evc_slot_atomically,
    reschedule_evc_visit,
)
from apps.organisation.models import Committee, Institution
from apps.organisation.services import create_committee, create_institution, create_region
from apps.outbox.models import OutboxEvent, OutboxState
from apps.outbox.services import operator_replay_failed_event
from apps.policy.models import PolicyVersion

User = get_user_model()


class ArchitecturalEdgeCaseTests(TestCase):
    def setUp(self):
        call_command("bootstrap_anumati")
        self.tech_admin = User.objects.get(username="tech_admin")
        self.region = create_region(
            actor=self.tech_admin,
            code="EDGE-R",
            name="Edge Test Region",
            headquarters_city="New Delhi",
        )
        self.inst = create_institution(
            actor=self.tech_admin,
            permanent_id="1-EDGE-001",
            name="Edge Institute of Technology",
            region=self.region,
            category=Institution.InstitutionCategory.PRIVATE_SELF_FINANCING,
            state="Delhi",
        )
        self.other_inst = create_institution(
            actor=self.tech_admin,
            permanent_id="1-EDGE-002",
            name="Other Institute",
            region=self.region,
            category=Institution.InstitutionCategory.GOVERNMENT,
            state="Delhi",
        )

        # Users with distinct roles
        self.inst_user = User.objects.create_user(username="inst_edge_user", password="pw")
        assign_role_to_user(
            actor=self.tech_admin,
            target_user=self.inst_user,
            role=RoleCode.INSTITUTION_USER,
            institution=self.inst,
            reason="Setup institution test user",
        )

        self.ro_user = User.objects.create_user(username="ro_edge_user", password="pw")
        assign_role_to_user(
            actor=self.tech_admin,
            target_user=self.ro_user,
            role=RoleCode.REGIONAL_OFFICER,
            region=self.region,
            reason="Setup RO test user",
        )

        self.scrutiny_user = User.objects.create_user(username="scrutiny_edge_user", password="pw")
        assign_role_to_user(
            actor=self.tech_admin,
            target_user=self.scrutiny_user,
            role=RoleCode.SCRUTINY_MEMBER,
            region=self.region,
            reason="Setup scrutiny test user",
        )

        self.ca_user = User.objects.create_user(username="ca_edge_user", password="pw")
        assign_role_to_user(
            actor=self.tech_admin,
            target_user=self.ca_user,
            role=RoleCode.COMPETENT_AUTHORITY,
            delegated_powers=["EXECUTIVE_COMMITTEE_DISPOSITION", "CHAIRMAN_DISPOSITION"],
            reason="Setup CA test user",
        )

        self.policy = PolicyVersion.objects.create(
            policy_code="EDGE-POL",
            version_number=1,
            academic_cycle="2026-27",
            state=PolicyVersion.PolicyState.ACTIVE,
            effective_from=timezone.now() - timedelta(days=1),
            route_rules=[
                {
                    "route_code": "EOA_ROUTE",
                    "conditions": {
                        "application_category": "EOA",
                    },
                    "stages": [StageType.SCRUTINY, StageType.EVC],
                }
            ],
            stage_timelines={"SCRUTINY": 7, "EVC": 14},
        )

    # -------------------------------------------------------------------------
    # 1. Intake & Isolation Edge Cases (Sheet 02 A1, Sheet 07 Q2)
    # -------------------------------------------------------------------------
    def test_institution_user_cannot_submit_intake_for_different_institution(self):
        """Cross-tenant intake must be rejected with PermissionDenied (Sheet 07 Q2)."""
        with self.assertRaises(PermissionDenied):
            submit_or_import_application(
                actor=self.inst_user,
                institution=self.other_inst,
                academic_cycle="2026-27",
                application_category="EOA",
                source_id="ATTACK-001",
            )

    def test_duplicate_application_source_id_raises_conflict(self):
        """Duplicate intake source ID must raise ValidationError / conflict (Sheet 02 A1)."""
        case = submit_or_import_application(
            actor=self.inst_user,
            institution=self.inst,
            academic_cycle="2026-27",
            application_category="EOA",
            source_id="UNIQUE-SRC-1",
        )
        self.assertIsNotNone(case.id)

        with self.assertRaises((ValidationError, DatabaseError, IntegrityError)):
            submit_or_import_application(
                actor=self.inst_user,
                institution=self.inst,
                academic_cycle="2026-27",
                application_category="EOA",
                source_id="UNIQUE-SRC-1",
            )

    def test_regional_officer_intake_transition_permitted(self):
        """Regional Officers may import applications for their region without a TransitionViolationError (Sheet 02 A1, Sheet 07 Q1)."""
        case = submit_or_import_application(
            actor=self.ro_user,
            institution=self.inst,
            academic_cycle="2026-27",
            application_category="EOA",
            source_id="RO-IMPORT-1",
        )
        self.assertIsNotNone(case.id)
        self.assertIsNotNone(case.submitted_at)
        self.assertNotEqual(case.status, CaseStatus.DRAFT)

    # -------------------------------------------------------------------------
    # 1b. Private storage path containment (Sheet 01 Block 11, Sheet 07 P2)
    # -------------------------------------------------------------------------
    def test_storage_path_rejects_traversal_and_sibling_prefix_directories(self):
        """Keys must stay inside the storage root, including sibling dirs that merely share the root's name as a prefix."""
        from pathlib import Path

        with tempfile.TemporaryDirectory() as parent:
            root = Path(parent) / "private"
            root.mkdir()
            with override_settings(PRIVATE_STORAGE_ROOT=str(root)):
                from apps.documents.services import _storage_path_for_object_key

                inside = _storage_path_for_object_key("documents/a.pdf")
                self.assertTrue(inside.is_relative_to(root.resolve()))
                with self.assertRaises(PermissionDenied):
                    _storage_path_for_object_key("../outside.pdf")
                with self.assertRaises(PermissionDenied):
                    _storage_path_for_object_key("../private-evil/stolen.pdf")

    # -------------------------------------------------------------------------
    # 2. Guarded Decision Command & Idempotency Edge Cases (Sheet 06 K1-K6, L1-L3)
    # -------------------------------------------------------------------------
    def test_idempotency_conflict_with_altered_payload_raises_error(self):
        """Reusing same idempotency key with different payload must fail with IdempotencyConflictError (Sheet 06 K3)."""
        case = submit_or_import_application(
            actor=self.inst_user,
            institution=self.inst,
            academic_cycle="2026-27",
            application_category="EOA",
            source_id="IDEM-TEST-1",
        )
        case.prescribed_stages = []
        case.status = CaseStatus.READY_FOR_DISPOSITION
        case.save(update_fields=["prescribed_stages", "status"])

        idemp_key = "idemp-key-edge-1"
        res1 = execute_guarded_decision_command(
            actor=self.ca_user,
            case_id=case.id,
            action="DECIDE_GRANT_EOA",
            expected_version=case.version,
            idempotency_key=idemp_key,
            outcome=DecisionOutcome.GRANT_EOA,
            reasons="All initial conditions satisfied",
            delegated_power_ref="EXECUTIVE_COMMITTEE_DISPOSITION",
        )
        self.assertEqual(res1.status_code, 200)
        self.assertFalse(res1.replayed)

        # Replay with IDENTICAL payload -> returns replayed=True
        res2 = execute_guarded_decision_command(
            actor=self.ca_user,
            case_id=case.id,
            action="DECIDE_GRANT_EOA",
            expected_version=case.version,
            idempotency_key=idemp_key,
            outcome=DecisionOutcome.GRANT_EOA,
            reasons="All initial conditions satisfied",
            delegated_power_ref="EXECUTIVE_COMMITTEE_DISPOSITION",
        )
        self.assertTrue(res2.replayed)

        # Replay with ALTERED payload (different reasons) -> must raise IdempotencyConflictError
        with self.assertRaises(IdempotencyConflictError):
            execute_guarded_decision_command(
                actor=self.ca_user,
                case_id=case.id,
                action="DECIDE_GRANT_EOA",
                expected_version=case.version,
                idempotency_key=idemp_key,
                outcome=DecisionOutcome.GRANT_EOA,
                reasons="Altered justification statement",
                delegated_power_ref="EXECUTIVE_COMMITTEE_DISPOSITION",
            )

    def test_stale_case_version_decision_rejection(self):
        """Stale expected_version must fail with StaleCaseVersionError (HTTP 409) (Sheet 06 K4)."""
        case = submit_or_import_application(
            actor=self.inst_user,
            institution=self.inst,
            academic_cycle="2026-27",
            application_category="EOA",
            source_id="STALE-TEST-1",
        )
        case.status = CaseStatus.READY_FOR_DISPOSITION
        case.save(update_fields=["status"])

        with self.assertRaises(StaleCaseVersionError):
            execute_guarded_decision_command(
                actor=self.ca_user,
                case_id=case.id,
                action="DECIDE_GRANT_EOA",
                expected_version=case.version + 99,  # Stale/incorrect version
                idempotency_key="idemp-stale-test",
                outcome=DecisionOutcome.GRANT_EOA,
                reasons="Premature or stale update attempt",
                delegated_power_ref="EXECUTIVE_COMMITTEE_DISPOSITION",
            )

    def test_unauthorized_user_cannot_issue_decision(self):
        """Scrutiny member or Regional Officer cannot issue final decision (Sheet 02 C1, Sheet 06 K2)."""
        case = submit_or_import_application(
            actor=self.inst_user,
            institution=self.inst,
            academic_cycle="2026-27",
            application_category="EOA",
            source_id="AUTH-TEST-1",
        )
        case.status = CaseStatus.READY_FOR_DISPOSITION
        case.save(update_fields=["status"])

        with self.assertRaises(PermissionDenied):
            execute_guarded_decision_command(
                actor=self.ro_user,  # RO is not Competent Authority
                case_id=case.id,
                action="DECIDE_GRANT_EOA",
                expected_version=case.version,
                idempotency_key="idemp-ro-unauth",
                outcome=DecisionOutcome.GRANT_EOA,
                reasons="Unauthorized attempt",
                delegated_power_ref="EXECUTIVE_COMMITTEE_DISPOSITION",
            )

    def test_competent_authority_missing_delegated_power_ref_is_denied(self):
        """Competent Authority missing the specific delegated power is denied (Sheet 02 C1)."""
        case = submit_or_import_application(
            actor=self.inst_user,
            institution=self.inst,
            academic_cycle="2026-27",
            application_category="EOA",
            source_id="POWER-TEST-1",
        )
        case.status = CaseStatus.READY_FOR_DISPOSITION
        case.save(update_fields=["status"])

        with self.assertRaises(PermissionDenied):
            execute_guarded_decision_command(
                actor=self.ca_user,
                case_id=case.id,
                action="DECIDE_GRANT_EOA",
                expected_version=case.version,
                idempotency_key="idemp-missing-power",
                outcome=DecisionOutcome.GRANT_EOA,
                reasons="Missing delegated power test",
                delegated_power_ref="COUNCIL_OF_MINISTERS_SPECIAL_POWER",  # Not granted
            )

    # -------------------------------------------------------------------------
    # 3. Stage Execution & EVC Prerequisites Edge Cases (Sheet 02 B2, Sheet 04 G1-G5)
    # -------------------------------------------------------------------------
    def test_evc_stage_completion_requires_evc_report(self):
        """EVC stage completion cannot be bypassed without a submitted EVC report (Sheet 04 G4-G5)."""
        case = submit_or_import_application(
            actor=self.inst_user,
            institution=self.inst,
            academic_cycle="2026-27",
            application_category="EOA",
            source_id="EVC-BYPASS-TEST",
        )
        evc_stage = StageInstance.objects.create(
            case=case,
            stage_type=StageType.EVC,
            sequence_number=2,
            status=StageStatus.IN_PROGRESS,
            assigned_officer=self.ro_user,
        )
        create_case_assignment(
            actor=self.tech_admin,
            case=case,
            stage_instance=evc_stage,
            target_user=self.ro_user,
            assignment_scope=CaseAssignment.AssignmentScope.STAGE_REVIEWER,
            reason="Assign EVC reviewer",
        )

        # Attempt to complete stage without scheduling or conducting report
        with self.assertRaises(ValidationError):
            execute_guarded_stage_transition_command(
                actor=self.ro_user,
                case_id=case.id,
                stage_instance_id=evc_stage.id,
                action="COMPLETE_STAGE",
                expected_version=case.version,
                idempotency_key="evc-bypass-key",
                reason="Attempting to complete EVC without conducting visit",
            )

    def test_evc_reschedule_requires_recorded_reason(self):
        """Rescheduling an EVC visit requires an explicit non-empty recorded reason (Sheet 04 G3)."""
        committee = create_committee(
            actor=self.tech_admin,
            code="EVC-COMM-EDGE",
            name="Edge EVC Committee",
            committee_type=Committee.CommitteeType.EVC,
            region=self.region,
        )
        case = submit_or_import_application(
            actor=self.inst_user,
            institution=self.inst,
            academic_cycle="2026-27",
            application_category="EOA",
            source_id="EVC-RESCHED-TEST",
        )
        case.prescribed_stages = [StageType.EVC]
        case.current_stage_type = StageType.EVC
        case.save(update_fields=["prescribed_stages", "current_stage_type"])

        evc_stage = StageInstance.objects.create(
            case=case,
            stage_type=StageType.EVC,
            sequence_number=1,
            status=StageStatus.IN_PROGRESS,
            assigned_officer=self.ro_user,
        )
        coord = check_evc_readiness_and_queue(
            actor=self.ro_user,
            case_id=case.id,
            stage_instance_id=evc_stage.id,
            mode=EvcMode.PHYSICAL,
        )
        slot_start = timezone.now() + timedelta(days=5)
        slot_end = slot_start + timedelta(hours=4)
        reserve_evc_slot_atomically(
            actor=self.ro_user,
            coordination_id=coord.id,
            committee_id=committee.id,
            slot_start=slot_start,
            slot_end=slot_end,
            reason="Initial reservation",
        )

        # Reschedule without reason -> ValidationError
        with self.assertRaises(ValidationError):
            reschedule_evc_visit(
                actor=self.ro_user,
                coordination_id=coord.id,
                reason="   ",  # Blank reason
            )

        # Reschedule with valid reason -> succeeds and preserves schedule_history
        rescheduled = reschedule_evc_visit(
            actor=self.ro_user,
            coordination_id=coord.id,
            reason="Severe regional weather alert necessitates postponement",
        )
        self.assertEqual(rescheduled.status, EvcStatus.RESCHEDULE_REQUIRED)
        self.assertEqual(len(rescheduled.schedule_history), 1)

    # -------------------------------------------------------------------------
    # 4. Deficiency Cycle & Response Edge Cases (Sheet 02 B2, Sheet 07 N1)
    # -------------------------------------------------------------------------
    def test_deficiency_response_requires_valid_explanation_and_expected_version(self):
        """Deficiency response requires non-empty explanation and matching expected_version."""
        case = submit_or_import_application(
            actor=self.inst_user,
            institution=self.inst,
            academic_cycle="2026-27",
            application_category="EOA",
            source_id="DEFICIENCY-TEST-1",
        )
        scrutiny_stage = case.stage_instances.get(stage_type=StageType.SCRUTINY)
        DeficiencyCycle.objects.create(
            case=case,
            stage_instance=scrutiny_stage,
            deficiencies_recorded=[{"issue": "Missing deed"}],
            returned_by=self.ro_user,
            return_reason="Missing land deed",
        )
        case.status = CaseStatus.DEFICIENCY_PENDING
        case.save(update_fields=["status"])

        # Empty response explanation -> ValidationError
        with self.assertRaises(ValidationError):
            submit_deficiency_response(
                actor=self.inst_user,
                case_id=case.id,
                response_text="",
                expected_version=case.version,
            )

        # Stale expected_version -> StaleCaseVersionError
        with self.assertRaises(StaleCaseVersionError):
            submit_deficiency_response(
                actor=self.inst_user,
                case_id=case.id,
                response_text="Land deed attached.",
                expected_version=case.version + 5,
            )

    # -------------------------------------------------------------------------
    # 5. Deadlines & Escalation Edge Cases (Sheet 03 D4, Sheet 04 H1-H5)
    # -------------------------------------------------------------------------
    def test_deadline_extension_requires_authorized_officer_and_future_timestamp(self):
        """Unauthorized users cannot extend deadlines; past timestamps or missing reasons are rejected (Sheet 03 D4)."""
        dl = DeadlineRecord.objects.create(
            source_type="STAGE",
            source_id=self.inst.id,
            institution=self.inst,
            region=self.region,
            clock_type=ClockType.OFFICER_REVIEW,
            due_at=timezone.now() + timedelta(days=2),
            calendar_version="CAL-v1",
        )

        # Institution user cannot extend deadline -> PermissionDenied
        with self.assertRaises(PermissionDenied):
            extend_or_hold_deadline(
                actor=self.inst_user,
                deadline_id=dl.id,
                reason="Institution asking for extension directly",
                new_due_at=timezone.now() + timedelta(days=10),
            )

        # Officer extending without reason -> ValidationError
        with self.assertRaises(ValidationError):
            extend_or_hold_deadline(
                actor=self.ro_user,
                deadline_id=dl.id,
                reason="   ",
                new_due_at=timezone.now() + timedelta(days=5),
            )

        # Officer extending to past timestamp -> ValidationError
        with self.assertRaises(ValidationError):
            extend_or_hold_deadline(
                actor=self.ro_user,
                deadline_id=dl.id,
                reason="Past extension",
                new_due_at=timezone.now() - timedelta(hours=1),
            )

    # -------------------------------------------------------------------------
    # 6. Outbox Replay & State Edge Cases (Sheet 04 H3-H4, Sheet 06 M5)
    # -------------------------------------------------------------------------
    def test_outbox_operator_replay_rejects_pending_or_completed_events(self):
        """Operator replay is only permitted on FAILED or UNKNOWN events (Sheet 04 H3, Sheet 06 M5)."""
        event_pending = OutboxEvent.objects.create(
            logical_id="edge-outbox-pending",
            event_type="COMMUNICATION",
            state=OutboxState.PENDING,
            next_attempt_at=timezone.now(),
        )
        with self.assertRaises(ValidationError):
            operator_replay_failed_event(
                actor=self.tech_admin,
                outbox_event_id=event_pending.id,
                reason="Premature replay attempt",
            )

        event_completed = OutboxEvent.objects.create(
            logical_id="edge-outbox-completed",
            event_type="COMMUNICATION",
            state=OutboxState.COMPLETED,
            next_attempt_at=timezone.now(),
        )
        with self.assertRaises(ValidationError):
            operator_replay_failed_event(
                actor=self.tech_admin,
                outbox_event_id=event_completed.id,
                reason="Cannot replay completed event",
            )

        # Replaying FAILED_OWNED succeeds
        event_failed = OutboxEvent.objects.create(
            logical_id="edge-outbox-failed",
            event_type="COMMUNICATION",
            state=OutboxState.FAILED_OWNED,
            next_attempt_at=timezone.now(),
        )
        replayed = operator_replay_failed_event(
            actor=self.tech_admin,
            outbox_event_id=event_failed.id,
            reason="Service recovered by administrator",
        )
        self.assertEqual(replayed.state, OutboxState.PENDING)
        self.assertEqual(replayed.state, OutboxState.PENDING)

    # -------------------------------------------------------------------------
    # 7. Document Validity & Renewal Independent State (Sheet 03 F1-F5)
    # -------------------------------------------------------------------------
    def test_document_validity_pending_renewal_does_not_replace_accepted_validity(self):
        """A new renewal submission enters explicit pending state and does NOT overwrite accepted validity (Sheet 03 F3-F4)."""
        with tempfile.TemporaryDirectory() as storage_root, override_settings(PRIVATE_STORAGE_ROOT=storage_root):
            doc_initial = receive_quarantined_upload(
                actor=self.inst_user,
                institution=self.inst,
                document_type="FIRE_SAFETY_CERTIFICATE",
                original_filename="initial_fire.pdf",
                content_type="application/pdf",
                file_bytes=b"%PDF-1.7 initial fire certificate",
            )
            run_quarantine_scan(document_version_id=doc_initial.id)

            val_rec = register_accepted_validity_document(
                actor=self.ro_user,
                institution=self.inst,
                document_type="FIRE_SAFETY_CERTIFICATE",
                accepted_version_id=doc_initial.id,
                valid_from=date(2025, 1, 1),
                valid_until=date(2026, 12, 31),
            )
            self.assertEqual(val_rec.accepted_version_id, doc_initial.id)
            self.assertEqual(val_rec.state, ValidityMonitorState.VALID)

            # Upload new candidate version
            doc_renewal_candidate = receive_quarantined_upload(
                actor=self.inst_user,
                institution=self.inst,
                document_type="FIRE_SAFETY_CERTIFICATE",
                original_filename="renewal_candidate.pdf",
                content_type="application/pdf",
                file_bytes=b"%PDF-1.7 candidate fire certificate renewal",
            )
            run_quarantine_scan(document_version_id=doc_renewal_candidate.id)

            # Submit renewal -> enter PENDING_RENEWAL_REVIEW
            submit_document_renewal(
                actor=self.inst_user,
                validity_record_id=val_rec.id,
                new_document_version_id=doc_renewal_candidate.id,
            )
            val_rec.refresh_from_db()
            # CRITICAL CHECK: accepted_version is STILL doc_initial!
            self.assertEqual(val_rec.accepted_version_id, doc_initial.id)
            self.assertEqual(val_rec.pending_renewal_version_id, doc_renewal_candidate.id)
            self.assertEqual(val_rec.state, ValidityMonitorState.PENDING_RENEWAL_REVIEW)

            # Review and accept renewal -> updates accepted_version
            updated = review_and_decide_document_renewal(
                actor=self.ro_user,
                validity_record_id=val_rec.id,
                accept=True,
                new_valid_from=date(2027, 1, 1),
                new_valid_until=date(2028, 12, 31),
                finding_notes="Verified renewed fire certificate",
            )
            self.assertEqual(updated.accepted_version_id, doc_renewal_candidate.id)
            self.assertEqual(updated.state, ValidityMonitorState.VALID)

    def test_regional_officer_intake_transition_permitted(self):
        """Edge case 13: Verify Regional Officer is permitted to submit/import applications for regional institutions (Sheet 02 A1)."""
        case = submit_or_import_application(
            actor=self.ro_user,
            institution=self.inst,
            academic_cycle="2026-27",
            application_category="EOA",
            source_id="RO-INTAKE-TEST-001",
        )
        self.assertIn(case.status, [CaseStatus.IN_STAGE_PROCESSING, CaseStatus.SUBMITTED])
        self.assertEqual(case.institution, self.inst)

