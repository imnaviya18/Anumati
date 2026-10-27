"""Stage 4 Tests: Approval Routing, Scrutiny, Deficiency Cycles, EVC Coordination, Committees, Dispositions & Appeals (Sheets 02, 04 G1-G5, APH Ch. I-II, Table 2.3)."""
from datetime import timedelta
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from apps.access.models import CaseAssignment, RoleCode
from apps.access.services import assign_role_to_user, create_case_assignment
from apps.cases.models import CaseStatus, StageInstance, StageType
from apps.cases.services import (
    close_processing_instance,
    initiate_appeal_or_reopening,
    submit_deficiency_response,
    submit_or_import_application,
)
from apps.decisions.models import DecisionOutcome
from apps.decisions.services import (
    execute_guarded_decision_command,
    execute_guarded_stage_transition_command,
)
from apps.evc.models import EvcMode, EvcStatus
from apps.evc.services import (
    check_evc_readiness_and_queue,
    confirm_or_reject_evc_schedule,
    conduct_and_complete_evc_report,
    reserve_evc_slot_atomically,
    reschedule_evc_visit,
)
from apps.organisation.models import Committee, CommitteeMembership, Institution
from apps.organisation.services import (
    add_committee_member,
    create_committee,
    create_institution,
    create_region,
)
from apps.policy.models import PolicyVersion

User = get_user_model()


class Stage4ApprovalWorkflowAndEvcTests(TestCase):
    def setUp(self) -> None:
        call_command("bootstrap_anumati")
        self.tech_admin = User.objects.get(username="tech_admin")
        self.region = create_region(
            actor=self.tech_admin,
            code="NWRO",
            name="North Western Regional Office",
            headquarters_city="Chandigarh",
        )
        self.new_inst = create_institution(
            actor=self.tech_admin,
            permanent_id="1-NWRO-5001",
            name="Chandigarh New Tech Institute",
            region=self.region,
            category=Institution.InstitutionCategory.PRIVATE_SELF_FINANCING,
            state="Punjab",
            is_new_institution=True,
        )
        self.user_inst = User.objects.create_user(username="inst_nwro", password="pw")
        self.user_ro = User.objects.create_user(username="ro_nwro", password="pw")
        self.user_scrutiny = User.objects.create_user(username="scrutiny_nwro", password="pw")
        self.user_evc = User.objects.create_user(username="evc_nwro", password="pw")
        self.user_shc = User.objects.create_user(username="shc_nwro", password="pw")
        self.user_sac = User.objects.create_user(username="sac_nwro", password="pw")
        self.user_ca = User.objects.create_user(username="ca_nwro", password="pw")

        assign_role_to_user(
            actor=self.tech_admin,
            target_user=self.user_inst,
            role=RoleCode.INSTITUTION_USER,
            institution=self.new_inst,
            reason="Assign Institution User",
        )
        assign_role_to_user(
            actor=self.tech_admin,
            target_user=self.user_ro,
            role=RoleCode.REGIONAL_OFFICER,
            region=self.region,
            reason="Assign Regional Officer",
        )
        assign_role_to_user(
            actor=self.tech_admin,
            target_user=self.user_scrutiny,
            role=RoleCode.SCRUTINY_MEMBER,
            region=self.region,
            reason="Assign Scrutiny Member",
        )
        assign_role_to_user(
            actor=self.tech_admin,
            target_user=self.user_evc,
            role=RoleCode.EVC_MEMBER,
            region=self.region,
            reason="Assign EVC Member",
        )
        assign_role_to_user(
            actor=self.tech_admin,
            target_user=self.user_shc,
            role=RoleCode.COMMITTEE_MEMBER,
            region=self.region,
            reason="Assign SHC Member",
        )
        assign_role_to_user(
            actor=self.tech_admin,
            target_user=self.user_sac,
            role=RoleCode.COMMITTEE_MEMBER,
            region=self.region,
            reason="Assign SAC Member",
        )
        assign_role_to_user(
            actor=self.tech_admin,
            target_user=self.user_ca,
            role=RoleCode.COMPETENT_AUTHORITY,
            delegated_powers=["GRANT_LOA", "GRANT_EOA", "ISSUE_LOD", "REJECT_LOR", "REFER_BACK"],
            reason="Assign Competent Authority",
        )

        self.policy = PolicyVersion.objects.create(
            policy_code="APH-2024-27",
            version_number=1,
            academic_cycle="2026-27",
            state=PolicyVersion.PolicyState.ACTIVE,
            effective_from=timezone.now() - timedelta(days=1),
            route_rules=[
                {
                    "route_code": "NEW_INST_SCRUTINY_EVC_SHC",
                    "conditions": {
                        "application_category": "NEW_INSTITUTION",
                        "is_new_institution": True,
                    },
                    "stages": [StageType.SCRUTINY, StageType.EVC, StageType.SHC],
                },
                {
                    "route_code": "CHANGE_BANK_ONLY_SCRUTINY",
                    "conditions": {
                        "application_category": "CHANGE_BANK_DETAILS",
                    },
                    "stages": [StageType.SCRUTINY],
                },
                {
                    "route_code": "BREAK_IN_EOA_ONLY_EVC",
                    "conditions": {
                        "application_category": "RESTORATION_BREAK_IN_EOA",
                    },
                    "stages": [StageType.EVC],
                },
            ],
            evc_rules={
                "new_institution": {"scheduling_sla_days": 5, "completion_sla_days": 10},
                "existing_institution": {"scheduling_sla_days": 14, "completion_sla_days": 25},
            },
        )

        self.evc_committee = create_committee(
            actor=self.user_ro,
            code="EVC-NWRO-PANEL-1",
            name="NWRO Expert Visit Committee 1",
            committee_type=Committee.CommitteeType.EVC,
            region=self.region,
        )
        add_committee_member(
            actor=self.user_ro,
            committee=self.evc_committee,
            user=self.user_evc,
            member_role=CommitteeMembership.MemberRole.CHAIRMAN,
        )

    def test_end_to_end_intake_deficiency_rescrutiny_evc_shc_disposition_and_appeal(self) -> None:
        """Exercise complete Sheet 02 A1-C4 & Sheet 04 G1-G5 flow including deficiency cycle, EVC slot contention/reschedule/report, SHC, LoD, and SAC appeal."""
        # 1. A1-A4: Intake & route resolution -> pins policy v1, selects NEW_INST_SCRUTINY_EVC_SHC, opens SCRUTINY stage
        case = submit_or_import_application(
            actor=self.user_inst,
            institution=self.new_inst,
            academic_cycle="2026-27",
            application_category="NEW_INSTITUTION",
            source_id="NSWS-2026-9901",
            requested_courses=[{"programme": "ENGINEERING", "course": "CSE", "intake": 120}],
        )
        self.assertEqual(case.status, CaseStatus.IN_STAGE_PROCESSING)
        self.assertEqual(case.selected_route_code, "NEW_INST_SCRUTINY_EVC_SHC")
        self.assertEqual(case.current_stage_type, StageType.SCRUTINY)

        scrutiny_stage = case.stage_instances.get(stage_type=StageType.SCRUTINY)
        create_case_assignment(
            actor=self.user_ro,
            case=case,
            stage_instance=scrutiny_stage,
            target_user=self.user_scrutiny,
            assignment_scope=CaseAssignment.AssignmentScope.STAGE_REVIEWER,
            reason="Assign scrutiny reviewer",
        )

        # 2. B2: Scrutiny records deficiency -> returns to institution (DEFICIENCY_PENDING)
        def_res = execute_guarded_stage_transition_command(
            actor=self.user_scrutiny,
            case_id=case.id,
            stage_instance_id=scrutiny_stage.id,
            action="RETURN_FOR_DEFICIENCY",
            expected_version=case.version,
            idempotency_key="scrutiny-def-1",
            reason="Certificate-2 Architect registration number missing.",
            findings=[{"code": "CERT_2_ARCH", "issue": "Missing CoA reg number"}],
        )
        self.assertEqual(def_res.body["case_status"], CaseStatus.DEFICIENCY_PENDING)

        # Institution responds -> creates RE_SCRUTINY stage instance preserving SCRUTINY history (APH 1.8f-g)
        re_scrutiny_stage = submit_deficiency_response(
            actor=self.user_inst,
            case_id=case.id,
            expected_version=def_res.body["version"],
            response_text="Uploaded updated Certificate-2 with Council of Architecture registration.",
        )
        self.assertEqual(re_scrutiny_stage.stage_type, StageType.RE_SCRUTINY)
        case.refresh_from_db()
        self.assertEqual(case.status, CaseStatus.IN_STAGE_PROCESSING)
        self.assertEqual(case.current_stage_type, StageType.RE_SCRUTINY)

        # Complete RE_SCRUTINY -> advances automatically to EVC stage
        re_res = execute_guarded_stage_transition_command(
            actor=self.user_scrutiny,
            case_id=case.id,
            stage_instance_id=re_scrutiny_stage.id,
            action="COMPLETE_STAGE",
            expected_version=case.version,
            idempotency_key="rescrutiny-comp-1",
            reason="Deficiency resolved in Re-Scrutiny.",
            recommendation="PROCEED_TO_EVC",
        )
        self.assertEqual(re_res.body["current_stage_type"], StageType.EVC)
        evc_stage = StageInstance.objects.get(id=re_res.body["next_stage_id"])

        # 3. G1-G5: EVC Readiness -> Slot Reservation (with conflict check) -> Reschedule -> Confirm -> Conduct & Report
        coord = check_evc_readiness_and_queue(
            actor=self.user_ro,
            case_id=case.id,
            stage_instance_id=evc_stage.id,
            mode=EvcMode.PHYSICAL,
        )
        self.assertTrue(coord.is_new_institution_rule)
        self.assertEqual(coord.status, EvcStatus.READY)

        slot_start = timezone.now() + timedelta(days=2)
        slot_end = slot_start + timedelta(hours=4)
        reserve_evc_slot_atomically(
            actor=self.user_ro,
            coordination_id=coord.id,
            committee_id=self.evc_committee.id,
            slot_start=slot_start,
            slot_end=slot_end,
        )

        # Confirm schedule
        confirm_or_reject_evc_schedule(
            actor=self.user_ro,
            coordination_id=coord.id,
            confirmed=True,
            reason="Committee chairman and members confirmed availability.",
        )

        # Simulate controlled reschedule with recorded reason preserving old schedule in schedule_history (Sheet 04 G3)
        reschedule_evc_visit(
            actor=self.user_ro,
            coordination_id=coord.id,
            reason="Heavy rain disrupted travel; rescheduling by 1 day.",
        )
        coord.refresh_from_db()
        self.assertEqual(len(coord.schedule_history), 1)
        self.assertEqual(coord.status, EvcStatus.RESCHEDULE_REQUIRED)

        new_start = slot_start + timedelta(days=1)
        new_end = new_start + timedelta(hours=4)
        reserve_evc_slot_atomically(
            actor=self.user_ro,
            coordination_id=coord.id,
            committee_id=self.evc_committee.id,
            slot_start=new_start,
            slot_end=new_end,
        )
        confirm_or_reject_evc_schedule(
            actor=self.user_ro,
            coordination_id=coord.id,
            confirmed=True,
            reason="Rescheduled slot confirmed.",
        )

        # Incomplete EVC report (missing GPS coordinates for Physical EVC per APH 1.9g Note) is rejected at G4 diamond
        case.refresh_from_db()
        with self.assertRaisesMessage(ValidationError, "gps_coordinates"):
            conduct_and_complete_evc_report(
                actor=self.user_evc,
                coordination_id=coord.id,
                expected_case_version=case.version,
                idempotency_key="evc-incomplete-1",
                observations={"classrooms": 12, "labs": 6},
                evidence_version_ids=[],
                video_recording_ref="local-storage://videos/evc_visit_35min.mp4",
                gps_coordinates="",
                report_summary="Labs inspected.",
                recommendation="RECOMMEND_SHC_REVIEW",
            )

        # Complete EVC report with all required records -> advances case to SHC stage (G5 -> B3)
        evc_comp = conduct_and_complete_evc_report(
            actor=self.user_evc,
            coordination_id=coord.id,
            expected_case_version=case.version,
            idempotency_key="evc-complete-1",
            observations={"classrooms": 12, "labs": 6, "library_books": 3000},
            evidence_version_ids=[],
            video_recording_ref="local-storage://videos/evc_visit_35min.mp4",
            gps_coordinates="30.7333N,76.7794E",
            report_summary="Physical EVC completed; minor library journal shortfall noted for SHC.",
            recommendation="PLACE_BEFORE_SHC",
        )
        self.assertEqual(evc_comp["evc_status"], EvcStatus.REPORT_SUBMITTED)
        self.assertEqual(evc_comp["stage_transition"]["current_stage_type"], StageType.SHC)

        # 4. Complete SHC stage -> Case reaches READY_FOR_DISPOSITION (B4 -> C1)
        shc_stage = StageInstance.objects.get(id=evc_comp["stage_transition"]["next_stage_id"])
        create_case_assignment(
            actor=self.user_ro,
            case=case,
            stage_instance=shc_stage,
            target_user=self.user_shc,
            assignment_scope=CaseAssignment.AssignmentScope.HEARING_COMMITTEE,
            reason="Assign SHC hearing member",
        )
        shc_res = execute_guarded_stage_transition_command(
            actor=self.user_shc,
            case_id=case.id,
            stage_instance_id=shc_stage.id,
            action="COMPLETE_STAGE",
            expected_version=evc_comp["stage_transition"]["version"],
            idempotency_key="shc-complete-1",
            reason="SHC heard institution representatives; journal subscription still pending.",
            recommendation="ISSUE_LOD",
        )
        self.assertEqual(shc_res.body["case_status"], CaseStatus.READY_FOR_DISPOSITION)

        # 5. C1-C4: Competent Authority issues LoD, closes processing instance, and Institution files SAC Appeal (APH 1.11)
        lod_res = execute_guarded_decision_command(
            actor=self.user_ca,
            case_id=case.id,
            action="DECIDE_ISSUE_LOD",
            expected_version=shc_res.body["version"],
            idempotency_key="ca-issue-lod-1",
            outcome=DecisionOutcome.ISSUE_LOD,
            reasons="Letter of Deficiency issued due to pending journal subscription.",
            delegated_power_ref="ISSUE_LOD",
        )
        self.assertEqual(lod_res.body["status"], CaseStatus.DEFICIENCY_LETTER_LOD)

        closed_case = close_processing_instance(
            actor=self.user_ca,
            case_id=case.id,
            expected_version=lod_res.body["version"],
        )
        self.assertEqual(closed_case.status, CaseStatus.CLOSED)

        # Linked appeal creates a new linked ApplicationCase in SAC stage (APH 1.11 / Sheet 02 C4)
        appeal_case = initiate_appeal_or_reopening(
            actor=self.user_inst,
            origin_case_id=case.id,
            appeal_reason="Subscribed to all required Scopus/Web of Science journals; appealing before SAC.",
            designated_stages=[StageType.SAC],
        )
        self.assertEqual(appeal_case.parent_case_id, case.id)
        self.assertEqual(appeal_case.current_stage_type, StageType.SAC)
