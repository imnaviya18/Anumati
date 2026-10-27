"""Stage 2 Tests: Atomic Decisions, Append-Only Audit, Outbox, Idempotency, Version Locking & 100-Concurrent Commands (Sheet 06 K1-K6, L1-L3, Sheet 07 N5, Q1)."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import tempfile

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.management import call_command
from django.db import transaction, DatabaseError, connection
from django.test import TestCase, TransactionTestCase

from apps.access.models import CaseAssignment, RoleCode
from apps.access.services import assign_role_to_user, create_case_assignment
from apps.audit.models import AuditEvent
from apps.audit.services import export_sealed_audit_bundle
from apps.audit.triggers import install_append_only_audit_triggers
from apps.cases.models import ApplicationCase, CaseStatus, StageInstance, StageStatus, StageType
from apps.compliance.models import Obligation
from apps.decisions.models import CaseDecision, DecisionOutcome
from apps.decisions.services import (
    IdempotencyConflictError,
    StaleCaseVersionError,
    execute_guarded_decision_command,
    execute_guarded_stage_transition_command,
)
from apps.organisation.models import Institution
from apps.organisation.services import create_institution, create_region
from apps.outbox.models import OutboxEvent
from apps.policy.models import PolicyVersion

User = get_user_model()


class Stage2AtomicDecisionAndAuditTests(TestCase):
    def setUp(self) -> None:
        call_command("bootstrap_anumati")
        install_append_only_audit_triggers()
        self.tech_admin = User.objects.get(username="tech_admin")
        self.region = create_region(
            actor=self.tech_admin,
            code="WEST",
            name="Western Regional Office",
            headquarters_city="Mumbai",
        )
        self.inst = create_institution(
            actor=self.tech_admin,
            permanent_id="1-WEST-3001",
            name="Western Technical Institute",
            region=self.region,
            category=Institution.InstitutionCategory.PRIVATE_SELF_FINANCING,
            state="Maharashtra",
            is_new_institution=True,
        )
        self.ro_user = User.objects.create_user(username="ro_west", password="pw")
        self.scrutiny_user = User.objects.create_user(username="scrutiny_west", password="pw")
        self.evc_user = User.objects.create_user(username="evc_west", password="pw")
        self.ca_user = User.objects.create_user(username="ca_ec_user", password="pw")

        assign_role_to_user(
            actor=self.tech_admin,
            target_user=self.ro_user,
            role=RoleCode.REGIONAL_OFFICER,
            region=self.region,
            reason="Assign West RO",
        )
        assign_role_to_user(
            actor=self.tech_admin,
            target_user=self.scrutiny_user,
            role=RoleCode.SCRUTINY_MEMBER,
            region=self.region,
            reason="Assign Scrutiny Member",
        )
        assign_role_to_user(
            actor=self.tech_admin,
            target_user=self.evc_user,
            role=RoleCode.EVC_MEMBER,
            region=self.region,
            reason="Assign EVC Member",
        )
        assign_role_to_user(
            actor=self.tech_admin,
            target_user=self.ca_user,
            role=RoleCode.COMPETENT_AUTHORITY,
            delegated_powers=["GRANT_LOA", "GRANT_EOA", "ISSUE_LOD", "REJECT_LOR", "REFER_BACK"],
            reason="Assign Competent Authority",
        )

        self.policy = PolicyVersion.objects.create(
            policy_code="APH-2024-27",
            version_number=1,
            academic_cycle="2026-27",
            state=PolicyVersion.PolicyState.ACTIVE,
        )
        self.case = ApplicationCase.objects.create(
            case_number="CASE-WEST-001",
            source_id="SRC-WEST-001",
            institution=self.inst,
            region=self.region,
            academic_cycle="2026-27",
            application_category="NEW_INSTITUTION",
            pinned_policy_version=self.policy,
            selected_route_code="SCRUTINY_PLUS_EVC",
            prescribed_stages=[StageType.SCRUTINY, StageType.EVC],
            status=CaseStatus.IN_STAGE_PROCESSING,
            current_stage_type=StageType.SCRUTINY,
            version=1,
        )
        self.scrutiny_stage = StageInstance.objects.create(
            case=self.case,
            stage_type=StageType.SCRUTINY,
            sequence_number=1,
            iteration_number=1,
            status=StageStatus.IN_PROGRESS,
        )
        create_case_assignment(
            actor=self.ro_user,
            case=self.case,
            stage_instance=self.scrutiny_stage,
            target_user=self.scrutiny_user,
            assignment_scope=CaseAssignment.AssignmentScope.STAGE_REVIEWER,
            reason="Assign scrutiny reviewer",
        )

    def test_guarded_stage_transition_and_atomic_decision_with_idempotency(self) -> None:
        """Verify stage transitions, version locking, idempotency replay/conflict, and atomic decision commit (Sheet 06 K1-L3)."""
        # 1. Complete Scrutiny stage -> automatically creates EVC stage and increments case version to 2
        res1 = execute_guarded_stage_transition_command(
            actor=self.scrutiny_user,
            case_id=self.case.id,
            stage_instance_id=self.scrutiny_stage.id,
            action="COMPLETE_STAGE",
            expected_version=1,
            idempotency_key="key-scrutiny-complete-1",
            reason="All Annexure-1 documents verified clean.",
            findings=[{"item": "Land Deed", "status": "VERIFIED"}],
            recommendation="PROCEED_TO_EVC",
        )
        self.assertEqual(res1.status_code, 200)
        self.assertFalse(res1.replayed)
        self.assertEqual(res1.body["version"], 2)
        self.assertEqual(res1.body["current_stage_type"], StageType.EVC)

        # Replay with identical key and payload returns exact committed result without re-mutating
        replay1 = execute_guarded_stage_transition_command(
            actor=self.scrutiny_user,
            case_id=self.case.id,
            stage_instance_id=self.scrutiny_stage.id,
            action="COMPLETE_STAGE",
            expected_version=1,
            idempotency_key="key-scrutiny-complete-1",
            reason="All Annexure-1 documents verified clean.",
            findings=[{"item": "Land Deed", "status": "VERIFIED"}],
            recommendation="PROCEED_TO_EVC",
        )
        self.assertTrue(replay1.replayed)
        self.assertEqual(replay1.body["audit_event_id"], res1.body["audit_event_id"])

        # Same key with different payload raises IdempotencyConflictError (Sheet 06 K3)
        with self.assertRaises(IdempotencyConflictError):
            execute_guarded_stage_transition_command(
                actor=self.scrutiny_user,
                case_id=self.case.id,
                stage_instance_id=self.scrutiny_stage.id,
                action="COMPLETE_STAGE",
                expected_version=1,
                idempotency_key="key-scrutiny-complete-1",
                reason="Different mutated reason",
                findings=[],
                recommendation="PROCEED_TO_EVC",
            )

        # 2. Assign and complete EVC stage -> case moves to READY_FOR_DISPOSITION (version 3)
        evc_stage = StageInstance.objects.get(id=res1.body["next_stage_id"])
        create_case_assignment(
            actor=self.ro_user,
            case=self.case,
            stage_instance=evc_stage,
            target_user=self.evc_user,
            assignment_scope=CaseAssignment.AssignmentScope.EVC_EVALUATOR,
            reason="Assign EVC evaluator",
        )
        from apps.evc.models import EvcCoordination, EvcStatus
        with self.assertRaises(ValidationError):
            execute_guarded_stage_transition_command(
                actor=self.evc_user, case_id=self.case.id, stage_instance_id=evc_stage.id,
                action="COMPLETE_STAGE", expected_version=2, idempotency_key="bypass-evc-report",
                reason="Attempted report bypass",
            )
        EvcCoordination.objects.create(
            case=self.case, stage_instance=evc_stage, status=EvcStatus.REPORT_SUBMITTED,
            observations={"facilities": "verified"}, video_recording_ref="recording/test",
            report_summary="Completed evaluation report",
        )
        res2 = execute_guarded_stage_transition_command(
            actor=self.evc_user,
            case_id=self.case.id,
            stage_instance_id=evc_stage.id,
            action="COMPLETE_STAGE",
            expected_version=2,
            idempotency_key="key-evc-complete-1",
            reason="Infrastructure and lab equipment verified via EVC.",
            recommendation="RECOMMEND_LOA",
        )
        self.assertEqual(res2.body["case_status"], CaseStatus.READY_FOR_DISPOSITION)
        self.assertEqual(res2.body["version"], 3)

        # 3. Stale expected_version (e.g., 2 instead of 3) raises StaleCaseVersionError (HTTP 409 — Sheet 06 K4)
        with self.assertRaises(StaleCaseVersionError):
            execute_guarded_decision_command(
                actor=self.ca_user,
                case_id=self.case.id,
                action="DECIDE_GRANT_LOA",
                expected_version=2,
                idempotency_key="key-stale-decision",
                outcome=DecisionOutcome.GRANT_LOA,
                reasons="Grant LoA",
                delegated_power_ref="GRANT_LOA",
            )

        # 4. Atomic decision write: creates CaseDecision, Obligation, DeadlineRecord, AuditEvent, OutboxEvent, IdempotencyRecord in ONE transaction
        dec_res = execute_guarded_decision_command(
            actor=self.ca_user,
            case_id=self.case.id,
            action="DECIDE_GRANT_LOA",
            expected_version=3,
            idempotency_key="key-final-loa-1",
            outcome=DecisionOutcome.GRANT_LOA,
            reasons="Recommended by Scrutiny and EVC; all APH norms satisfied.",
            delegated_power_ref="GRANT_LOA",
            obligations_spec=[
                {
                    "obligation_code": "SECURITY_DEPOSIT_AFFIDAVIT_3",
                    "condition_text": "Submit Security Deposit and Affidavit-3 within 15 days (APH 1.11f/2.25f).",
                    "evidence_requirement": "Signed Affidavit-3 + FDR receipt",
                    "due_days": 15,
                }
            ],
        )
        self.assertEqual(dec_res.status_code, 200)
        self.assertEqual(dec_res.body["status"], CaseStatus.APPROVED_LOA)
        self.assertEqual(dec_res.body["version"], 4)
        self.assertEqual(len(dec_res.body["obligation_ids"]), 1)
        self.assertEqual(CaseDecision.objects.filter(case=self.case, is_current_final=True).count(), 1)
        self.assertEqual(Obligation.objects.filter(case=self.case).count(), 1)
        self.assertTrue(OutboxEvent.objects.filter(id=dec_res.body["outbox_event_id"]).exists())

    def test_append_only_audit_and_sealed_export(self) -> None:
        """Prove AuditEvent rejects UPDATE and DELETE at both ORM and raw SQL database trigger levels (Sheet 07 N5)."""
        event = AuditEvent.objects.first()
        self.assertIsNotNone(event)
        assert event is not None

        # ORM-level update and delete are denied
        event.reason = "Tampered reason"
        with self.assertRaises(PermissionDenied):
            event.save()
        with self.assertRaises(PermissionDenied):
            event.delete()

        # Database trigger-level raw SQL UPDATE and DELETE are denied
        with self.assertRaises(DatabaseError):
            with transaction.atomic(), connection.cursor() as cursor:
                cursor.execute("UPDATE audit_auditevent SET reason = 'SQL Tamper'")

        with self.assertRaises(DatabaseError):
            with transaction.atomic(), connection.cursor() as cursor:
                cursor.execute("DELETE FROM audit_auditevent")

        # Sealed export writes read-only bundle with verified SHA-256 digest
        with tempfile.TemporaryDirectory() as tmpdir:
            bundle_path = export_sealed_audit_bundle(Path(tmpdir))
            self.assertTrue(bundle_path.is_file())
            mode = bundle_path.stat().st_mode & 0o777
            self.assertEqual(mode, 0o444)


class Stage2Concurrency100DecisionsTest(TransactionTestCase):
    """Sheet 07 Q1 & MINIMUM TESTS: 100 concurrent final-decision commands -> at most one authoritative outcome, others conflict or replay."""

    def test_100_concurrent_final_decision_commands(self) -> None:
        call_command("bootstrap_anumati")
        tech_admin = User.objects.get(username="tech_admin")
        region = create_region(
            actor=tech_admin,
            code="CENTRAL",
            name="Central Regional Office",
            headquarters_city="Bhopal",
        )
        inst = create_institution(
            actor=tech_admin,
            permanent_id="1-CENT-9001",
            name="Central Engineering College",
            region=region,
            category=Institution.InstitutionCategory.PRIVATE_SELF_FINANCING,
            state="Madhya Pradesh",
        )
        ca_user = User.objects.create_user(username="ca_concurrent", password="pw")
        assign_role_to_user(
            actor=tech_admin,
            target_user=ca_user,
            role=RoleCode.COMPETENT_AUTHORITY,
            delegated_powers=["GRANT_EOA", "REJECT_LOR"],
            reason="Assign CA for concurrency test",
        )
        policy = PolicyVersion.objects.create(
            policy_code="APH-2024-27",
            version_number=1,
            academic_cycle="2026-27",
            state=PolicyVersion.PolicyState.ACTIVE,
        )
        case = ApplicationCase.objects.create(
            case_number="CASE-CONC-100",
            source_id="SRC-CONC-100",
            institution=inst,
            region=region,
            academic_cycle="2026-27",
            application_category="EOA_SELF_DISCLOSURE",
            pinned_policy_version=policy,
            selected_route_code="EOA_SELF_DISCLOSURE",
            prescribed_stages=[StageType.SELF_DISCLOSURE_CHECK],
            status=CaseStatus.READY_FOR_DISPOSITION,
            version=1,
        )
        StageInstance.objects.create(
            case=case,
            stage_type=StageType.SELF_DISCLOSURE_CHECK,
            sequence_number=1,
            iteration_number=1,
            status=StageStatus.COMPLETED,
        )

        outcomes_summary = {"committed": 0, "replayed": 0, "conflict": 0}

        def run_one_command(idx: int) -> str:
            # First 10 threads share idempotency key "key-shared-0" to exercise concurrent replay/deduplication;
            # remaining 90 threads use distinct keys competing on the case version lock.
            idem_key = "key-shared-0" if idx < 10 else f"key-distinct-{idx}"
            action = "DECIDE_GRANT_EOA" if idx % 2 == 0 else "DECIDE_REJECT_LOR"
            outcome = DecisionOutcome.GRANT_EOA if idx % 2 == 0 else DecisionOutcome.REJECT_LOR
            power = "GRANT_EOA" if idx % 2 == 0 else "REJECT_LOR"
            if idem_key == "key-shared-0":
                action = "DECIDE_GRANT_EOA"
                outcome = DecisionOutcome.GRANT_EOA
                power = "GRANT_EOA"
            try:
                res = execute_guarded_decision_command(
                    actor=ca_user,
                    case_id=case.id,
                    action=action,
                    expected_version=1,
                    idempotency_key=idem_key,
                    outcome=outcome,
                    reasons="Concurrent disposition test",
                    delegated_power_ref=power,
                )
                return "replayed" if res.replayed else "committed"
            except (StaleCaseVersionError, IdempotencyConflictError, DatabaseError):
                return "conflict"
            finally:
                connection.close()

        with ThreadPoolExecutor(max_workers=16) as pool:
            results = list(pool.map(run_one_command, range(100)))

        for r in results:
            outcomes_summary[r] += 1

        # Exactly 1 authoritative committed outcome; all other 99 either replayed or conflicted
        self.assertEqual(outcomes_summary["committed"], 1, f"Expected 1 committed, got {outcomes_summary}")
        self.assertEqual(outcomes_summary["committed"] + outcomes_summary["replayed"] + outcomes_summary["conflict"], 100)
        self.assertEqual(CaseDecision.objects.filter(case=case, is_current_final=True).count(), 1)
        case.refresh_from_db()
        self.assertEqual(case.version, 2)
