"""Sheet 07 Q1: State, Version, Idempotency & Concurrency Verification Suite."""
from __future__ import annotations

from datetime import timedelta
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from apps.access.models import CaseAssignment, RoleAssignment, RoleCode
from apps.cases.models import StageType
from apps.cases.services import submit_or_import_application
from apps.decisions.models import DecisionOutcome
from apps.decisions.services import (
    IdempotencyConflictError,
    StaleCaseVersionError,
    execute_guarded_decision_command,
    execute_guarded_stage_transition_command,
)
from apps.evc.models import EvcMode, EvcStatus
from apps.evc.services import check_evc_readiness_and_queue, reserve_evc_slot_atomically
from apps.organisation.models import Bureau, Committee, Institution, Region
from apps.policy.models import PolicyVersion
from apps.routing.services import TransitionViolationError

User = get_user_model()


class Sheet07Q1StateAndConcurrencyTests(TestCase):
    """Verify Sheet 07 Q1: permitted/forbidden transitions, stale versions, repeated keys, and atomic EVC slot contention."""

    def setUp(self) -> None:
        self.region = Region.objects.create(code="WRO-Q1", name="Western Region Q1", headquarters_city="Mumbai")
        self.bureau = Bureau.objects.create(code="APP-Q1", name="Approval Bureau Q1")
        self.inst = Institution.objects.create(
            permanent_id="INST-Q1-01",
            name="Q1 Engineering College",
            region=self.region,
            state="Maharashtra",
            category=Institution.InstitutionCategory.PRIVATE_SELF_FINANCING,
            is_new_institution=True,
        )
        self.policy = PolicyVersion.objects.create(
            policy_code="APH-Q1",
            version_number=1,
            academic_cycle="2026-27",
            state=PolicyVersion.PolicyState.ACTIVE,
            route_rules=[
                {
                    "route_code": "SCRUTINY_AND_EVC",
                    "conditions": {"application_category": "NEW_INST"},
                    "stages": [StageType.SCRUTINY, StageType.EVC],
                }
            ],
        )

        self.inst_user = User.objects.create_user(username="inst_q1", password="Password123!")
        RoleAssignment.objects.create(user=self.inst_user, role=RoleCode.INSTITUTION_USER, institution=self.inst)

        self.ro_user = User.objects.create_user(username="ro_q1", password="Password123!")
        RoleAssignment.objects.create(user=self.ro_user, role=RoleCode.REGIONAL_OFFICER, region=self.region)

        self.ca_user = User.objects.create_user(username="ca_q1", password="Password123!")
        RoleAssignment.objects.create(
            user=self.ca_user,
            role=RoleCode.COMPETENT_AUTHORITY,
            delegated_powers=["EC_APPROVAL"],
        )

        self.evc_committee = Committee.objects.create(
            code="EVC-COM-Q1",
            name="EVC Committee Q1",
            committee_type=Committee.CommitteeType.EVC,
            region=self.region,
        )

    def test_q1_forbidden_transitions_stale_versions_idempotency_and_slot_contention(self) -> None:
        """Prove Q1 invariants across transitions, optimistic version locking, idempotency keys, and atomic EVC slot reservations."""
        case1 = submit_or_import_application(
            actor=self.inst_user,
            institution=self.inst,
            source_id="SRC-Q1-1",
            academic_cycle="2026-27",
            application_category="NEW_INST",
            responsible_bureau=self.bureau,
        )
        case2 = submit_or_import_application(
            actor=self.inst_user,
            institution=self.inst,
            source_id="SRC-Q1-2",
            academic_cycle="2026-27",
            application_category="NEW_INST",
            responsible_bureau=self.bureau,
        )

        scrutiny1 = case1.stage_instances.get(stage_type=StageType.SCRUTINY)
        scrutiny2 = case2.stage_instances.get(stage_type=StageType.SCRUTINY)
        CaseAssignment.objects.create(
            case=case1,
            stage_instance=scrutiny1,
            user=self.ro_user,
            assignment_scope=CaseAssignment.AssignmentScope.STAGE_REVIEWER,
        )
        CaseAssignment.objects.create(
            case=case2,
            stage_instance=scrutiny2,
            user=self.ro_user,
            assignment_scope=CaseAssignment.AssignmentScope.STAGE_REVIEWER,
        )

        # 1. Forbidden transition: Competent Authority cannot grant approval while stages are incomplete
        with self.assertRaises(TransitionViolationError):
            execute_guarded_decision_command(
                actor=self.ca_user,
                case_id=case1.id,
                action="DECIDE_GRANT_LOA",
                outcome=DecisionOutcome.GRANT_LOA,
                expected_version=case1.version,
                idempotency_key="IDEMP-FORBIDDEN-Q1",
                delegated_power_ref="EC_APPROVAL",
                reasons="Premature approval attempt",
            )

        # 2. Stale version rejected with StaleCaseVersionError (HTTP 409)
        with self.assertRaises(StaleCaseVersionError):
            execute_guarded_stage_transition_command(
                actor=self.ro_user,
                case_id=case1.id,
                stage_instance_id=scrutiny1.id,
                action="COMPLETE_STAGE",
                expected_version=case1.version + 99,
                idempotency_key="IDEMP-STALE-Q1",
                reason="Stale version check",
            )

        # 3. Complete SCRUTINY on both cases and test idempotency replay vs payload conflict
        res1 = execute_guarded_stage_transition_command(
            actor=self.ro_user,
            case_id=case1.id,
            stage_instance_id=scrutiny1.id,
            action="COMPLETE_STAGE",
            expected_version=case1.version,
            idempotency_key="IDEMP-SCR1-OK",
            reason="Scrutiny verified",
            recommendation="PROCEED_TO_EVC",
        )
        replay = execute_guarded_stage_transition_command(
            actor=self.ro_user,
            case_id=case1.id,
            stage_instance_id=scrutiny1.id,
            action="COMPLETE_STAGE",
            expected_version=case1.version,
            idempotency_key="IDEMP-SCR1-OK",
            reason="Scrutiny verified",
            recommendation="PROCEED_TO_EVC",
        )
        self.assertTrue(replay.replayed)
        self.assertEqual(res1.body["version"], replay.body["version"])

        with self.assertRaises(IdempotencyConflictError):
            execute_guarded_stage_transition_command(
                actor=self.ro_user,
                case_id=case1.id,
                stage_instance_id=scrutiny1.id,
                action="COMPLETE_STAGE",
                expected_version=case1.version,
                idempotency_key="IDEMP-SCR1-OK",
                reason="DIFFERENT PAYLOAD REASON",
                recommendation="PROCEED_TO_EVC",
            )

        execute_guarded_stage_transition_command(
            actor=self.ro_user,
            case_id=case2.id,
            stage_instance_id=scrutiny2.id,
            action="COMPLETE_STAGE",
            expected_version=case2.version,
            idempotency_key="IDEMP-SCR2-OK",
            reason="Scrutiny verified case 2",
            recommendation="PROCEED_TO_EVC",
        )

        # 4. Atomic EVC slot contention: two ready EVC coordinations compete for the same committee slot
        evc_stage1 = case1.stage_instances.get(stage_type=StageType.EVC)
        evc_stage2 = case2.stage_instances.get(stage_type=StageType.EVC)
        coord1 = check_evc_readiness_and_queue(
            actor=self.ro_user, case_id=case1.id, stage_instance_id=evc_stage1.id, mode=EvcMode.ONLINE
        )
        coord2 = check_evc_readiness_and_queue(
            actor=self.ro_user, case_id=case2.id, stage_instance_id=evc_stage2.id, mode=EvcMode.ONLINE
        )

        now = timezone.now()
        slot_start = now + timedelta(days=3)
        slot_end = now + timedelta(days=3, hours=4)

        slot = reserve_evc_slot_atomically(
            actor=self.ro_user,
            coordination_id=coord1.id,
            committee_id=self.evc_committee.id,
            slot_start=slot_start,
            slot_end=slot_end,
        )
        self.assertTrue(slot.is_reserved)
        coord1.refresh_from_db()
        self.assertEqual(coord1.status, EvcStatus.SLOT_RESERVED)

        # Second coordination attempting to reserve the same or overlapping slot is rejected atomically
        with self.assertRaises(ValidationError):
            reserve_evc_slot_atomically(
                actor=self.ro_user,
                coordination_id=coord2.id,
                committee_id=self.evc_committee.id,
                slot_start=slot_start,
                slot_end=slot_end,
            )
