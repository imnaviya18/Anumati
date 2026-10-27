"""Stage 1 Tests: Organisation, Roles, Access Scope, Relational Models & Transition Contracts (Sheet 01, 02, 06 K2/K5, 07 N1-N4, P1, P5, Q1, Q2)."""
from datetime import timedelta
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from apps.access.models import CaseAssignment, RoleAssignment, RoleCode
from apps.access.selectors import (
    scope_cases_queryset,
    scope_documents_queryset,
    scope_obligations_queryset,
    scope_validity_records_queryset,
)
from apps.access.services import (
    assign_role_to_user,
    check_case_read_access,
    check_stage_execution_access,
    create_case_assignment,
    resolve_actor_scope,
)
from apps.cases.models import ApplicationCase, CaseStatus, StageInstance, StageStatus, StageType
from apps.compliance.models import Obligation, ObligationState
from apps.documents.models import (
    DocumentValidityRecord,
    DocumentVersion,
    QuarantineStatus,
    ReviewAcceptanceStatus,
    ValidityMonitorState,
)
from apps.organisation.models import Bureau, Committee, CommitteeMembership, Institution
from apps.organisation.services import (
    add_committee_member,
    create_bureau,
    create_committee,
    create_institution,
    create_region,
)
from apps.policy.models import PolicyVersion
from apps.routing.services import (
    TransitionViolationError,
    evaluate_policy_route,
    validate_case_transition,
)

User = get_user_model()


class Stage1OrganisationAccessAndTransitionTests(TestCase):
    def setUp(self) -> None:
        call_command("bootstrap_anumati")
        self.tech_admin = User.objects.get(username="tech_admin")

        self.region_north = create_region(
            actor=self.tech_admin,
            code="NORTH",
            name="Northern Regional Office",
            headquarters_city="Kanpur",
            states_covered=["Uttar Pradesh", "Uttarakhand", "Bihar"],
        )
        self.region_south = create_region(
            actor=self.tech_admin,
            code="SOUTH",
            name="Southern Regional Office",
            headquarters_city="Chennai",
            states_covered=["Tamil Nadu", "Puducherry"],
        )
        self.reg_bureau = create_bureau(
            actor=self.tech_admin,
            code="REG-BUR",
            name="Regulation Bureau",
            bureau_type=Bureau.BureauType.REGULATION,
        )

        self.inst_north = create_institution(
            actor=self.tech_admin,
            permanent_id="1-NORTH-1001",
            name="Northern Institute of Technology",
            region=self.region_north,
            category=Institution.InstitutionCategory.PRIVATE_SELF_FINANCING,
            state="Uttar Pradesh",
            is_new_institution=True,
        )
        self.inst_south = create_institution(
            actor=self.tech_admin,
            permanent_id="1-SOUTH-2002",
            name="Southern College of Engineering",
            region=self.region_south,
            category=Institution.InstitutionCategory.PRIVATE_SELF_FINANCING,
            state="Tamil Nadu",
            is_new_institution=False,
        )

        self.user_inst_north = User.objects.create_user(username="inst_north", password="pw")
        self.user_inst_south = User.objects.create_user(username="inst_south", password="pw")
        self.user_ro_north = User.objects.create_user(username="ro_north", password="pw")
        self.user_ro_south = User.objects.create_user(username="ro_south", password="pw")
        self.user_scrutiny_assigned = User.objects.create_user(username="scrutiny_assigned", password="pw")
        self.user_scrutiny_unassigned = User.objects.create_user(username="scrutiny_unassigned", password="pw")
        self.user_ca = User.objects.create_user(username="ec_authority", password="pw")
        self.user_oversight = User.objects.create_user(username="oversight1", password="pw")

        assign_role_to_user(
            actor=self.tech_admin,
            target_user=self.user_inst_north,
            role=RoleCode.INSTITUTION_USER,
            institution=self.inst_north,
            reason="Assign North institution user",
        )
        assign_role_to_user(
            actor=self.tech_admin,
            target_user=self.user_inst_south,
            role=RoleCode.INSTITUTION_USER,
            institution=self.inst_south,
            reason="Assign South institution user",
        )
        assign_role_to_user(
            actor=self.tech_admin,
            target_user=self.user_ro_north,
            role=RoleCode.REGIONAL_OFFICER,
            region=self.region_north,
            reason="Assign North RO",
        )
        assign_role_to_user(
            actor=self.tech_admin,
            target_user=self.user_ro_south,
            role=RoleCode.REGIONAL_OFFICER,
            region=self.region_south,
            reason="Assign South RO",
        )
        assign_role_to_user(
            actor=self.tech_admin,
            target_user=self.user_scrutiny_assigned,
            role=RoleCode.SCRUTINY_MEMBER,
            region=self.region_north,
            reason="Assign scrutiny member 1",
        )
        assign_role_to_user(
            actor=self.tech_admin,
            target_user=self.user_scrutiny_unassigned,
            role=RoleCode.SCRUTINY_MEMBER,
            region=self.region_north,
            reason="Assign scrutiny member 2",
        )
        assign_role_to_user(
            actor=self.tech_admin,
            target_user=self.user_ca,
            role=RoleCode.COMPETENT_AUTHORITY,
            delegated_powers=["GRANT_LOA", "GRANT_EOA", "ISSUE_LOD", "REJECT_LOR", "REFER_BACK"],
            reason="Assign Executive Committee authority",
        )
        assign_role_to_user(
            actor=self.tech_admin,
            target_user=self.user_oversight,
            role=RoleCode.OVERSIGHT_AUDITOR,
            reason="Assign oversight auditor",
        )

        self.policy = PolicyVersion.objects.create(
            policy_code="APH-2024-27",
            version_number=1,
            academic_cycle="2026-27",
            state=PolicyVersion.PolicyState.ACTIVE,
            route_rules=[
                {
                    "route_code": "NEW_INST_SCRUTINY_EVC",
                    "conditions": {
                        "application_category": "NEW_INSTITUTION",
                        "is_new_institution": True,
                    },
                    "stages": [StageType.SCRUTINY, StageType.EVC],
                },
                {
                    "route_code": "EOA_SELF_DISCLOSURE",
                    "conditions": {
                        "application_category": "EOA_SELF_DISCLOSURE",
                        "is_new_institution": False,
                    },
                    "stages": [StageType.SELF_DISCLOSURE_CHECK],
                },
            ],
        )

        self.case_north = ApplicationCase.objects.create(
            case_number="CASE-2026-0001",
            source_id="SRC-NSWS-0001",
            institution=self.inst_north,
            region=self.region_north,
            responsible_bureau=self.reg_bureau,
            academic_cycle="2026-27",
            application_category="NEW_INSTITUTION",
            pinned_policy_version=self.policy,
            selected_route_code="NEW_INST_SCRUTINY_EVC",
            prescribed_stages=[StageType.SCRUTINY, StageType.EVC],
            status=CaseStatus.IN_STAGE_PROCESSING,
            current_stage_type=StageType.SCRUTINY,
        )
        self.stage_north = StageInstance.objects.create(
            case=self.case_north,
            stage_type=StageType.SCRUTINY,
            sequence_number=1,
            iteration_number=1,
            status=StageStatus.IN_PROGRESS,
        )
        create_case_assignment(
            actor=self.user_ro_north,
            case=self.case_north,
            stage_instance=self.stage_north,
            target_user=self.user_scrutiny_assigned,
            assignment_scope=CaseAssignment.AssignmentScope.STAGE_REVIEWER,
            reason="Assign scrutiny reviewer to CASE-2026-0001",
        )

        self.case_south = ApplicationCase.objects.create(
            case_number="CASE-2026-0002",
            source_id="SRC-NSWS-0002",
            institution=self.inst_south,
            region=self.region_south,
            academic_cycle="2026-27",
            application_category="EOA_SELF_DISCLOSURE",
            pinned_policy_version=self.policy,
            selected_route_code="EOA_SELF_DISCLOSURE",
            prescribed_stages=[StageType.SELF_DISCLOSURE_CHECK],
            status=CaseStatus.IN_STAGE_PROCESSING,
            current_stage_type=StageType.SELF_DISCLOSURE_CHECK,
        )

    def test_cross_institution_and_cross_region_isolation(self) -> None:
        """Prove cross-institution, cross-region, and unassigned reviewer access is denied (Sheet 07 Q2)."""
        # North institution can read own case, denied South case
        check_case_read_access(self.user_inst_north, self.case_north)
        with self.assertRaises(PermissionDenied):
            check_case_read_access(self.user_inst_north, self.case_south)

        # North RO can read North case, denied South case
        check_case_read_access(self.user_ro_north, self.case_north)
        with self.assertRaises(PermissionDenied):
            check_case_read_access(self.user_ro_north, self.case_south)

        # Assigned scrutiny reviewer can read & execute North stage; unassigned scrutiny reviewer is denied
        check_case_read_access(self.user_scrutiny_assigned, self.case_north)
        check_stage_execution_access(
            self.user_scrutiny_assigned,
            self.case_north,
            self.stage_north,
            "COMPLETE_STAGE_NEXT",
        )
        with self.assertRaises(PermissionDenied):
            check_case_read_access(self.user_scrutiny_unassigned, self.case_north)
        with self.assertRaises(PermissionDenied):
            check_stage_execution_access(
                self.user_scrutiny_unassigned,
                self.case_north,
                self.stage_north,
                "COMPLETE_STAGE_NEXT",
            )

        # List/search queryset scoping
        self.assertEqual(list(scope_cases_queryset(self.user_inst_north)), [self.case_north])
        self.assertEqual(list(scope_cases_queryset(self.user_ro_south)), [self.case_south])
        self.assertEqual(list(scope_cases_queryset(self.user_scrutiny_unassigned)), [])
        self.assertEqual(scope_cases_queryset(self.user_oversight).count(), 2)

    def test_technical_admin_holds_no_regulatory_authority(self) -> None:
        """Prove TECHNICAL_ADMIN cannot hold delegated regulatory powers or execute stages/decisions (Sheet 07 P5)."""
        with self.assertRaises(ValidationError):
            bad_ra = RoleAssignment(
                user=self.tech_admin,
                role=RoleCode.TECHNICAL_ADMIN,
                delegated_powers=["GRANT_LOA"],
            )
            bad_ra.full_clean()

        with self.assertRaises(PermissionDenied):
            check_case_read_access(self.tech_admin, self.case_north)

        with self.assertRaises(PermissionDenied):
            check_stage_execution_access(
                self.tech_admin,
                self.case_north,
                self.stage_north,
                "COMPLETE_STAGE_NEXT",
            )

    def test_expired_role_or_case_assignment_is_denied(self) -> None:
        """Prove validity-period expiration revokes access automatically (Sheet 07 N1)."""
        past = timezone.now() - timedelta(days=2)
        expired_user = User.objects.create_user(username="expired_ro", password="pw")
        RoleAssignment.objects.create(
            user=expired_user,
            role=RoleCode.REGIONAL_OFFICER,
            region=self.region_north,
            valid_from=past - timedelta(days=5),
            valid_until=past,
            is_active=True,
        )
        with self.assertRaises(PermissionDenied):
            resolve_actor_scope(expired_user)

    def test_permitted_vs_forbidden_transitions_and_prescribed_stages(self) -> None:
        """Prove permitted vs forbidden transitions and no automatic approval / skipping stages (Sheet 02, 06 K5, 07 Q1)."""
        # Permitted stage return for deficiency by Scrutiny member
        rule = validate_case_transition(
            case=self.case_north,
            action="RETURN_FOR_DEFICIENCY",
            actor_roles=frozenset({RoleCode.SCRUTINY_MEMBER}),
            active_stage_type=StageType.SCRUTINY,
        )
        self.assertEqual(rule.destination_status, CaseStatus.DEFICIENCY_PENDING)

        # Institution user cannot complete scrutiny stage
        with self.assertRaises(TransitionViolationError):
            validate_case_transition(
                case=self.case_north,
                action="COMPLETE_STAGE_NEXT",
                actor_roles=frozenset({RoleCode.INSTITUTION_USER}),
                active_stage_type=StageType.SCRUTINY,
            )

        # Cannot jump directly from IN_STAGE_PROCESSING to DECIDE_GRANT_LOA
        with self.assertRaises(TransitionViolationError):
            validate_case_transition(
                case=self.case_north,
                action="DECIDE_GRANT_LOA",
                actor_roles=frozenset({RoleCode.COMPETENT_AUTHORITY}),
            )

        # Even if case status is READY_FOR_DISPOSITION, cannot grant LoA if prescribed stages (SCRUTINY, EVC) are not COMPLETED
        self.case_north.status = CaseStatus.READY_FOR_DISPOSITION
        self.case_north.save()
        with self.assertRaisesMessage(TransitionViolationError, "Required prescribed stage"):
            validate_case_transition(
                case=self.case_north,
                action="DECIDE_GRANT_LOA",
                actor_roles=frozenset({RoleCode.COMPETENT_AUTHORITY}),
            )

        # Complete both prescribed stages -> Competent Authority disposition is now permitted
        self.stage_north.status = StageStatus.COMPLETED
        self.stage_north.save()
        StageInstance.objects.create(
            case=self.case_north,
            stage_type=StageType.EVC,
            sequence_number=2,
            iteration_number=1,
            status=StageStatus.COMPLETED,
        )
        loa_rule = validate_case_transition(
            case=self.case_north,
            action="DECIDE_GRANT_LOA",
            actor_roles=frozenset({RoleCode.COMPETENT_AUTHORITY}),
        )
        self.assertEqual(loa_rule.destination_status, CaseStatus.APPROVED_LOA)

    def test_policy_route_selection_never_defaults_to_approval(self) -> None:
        """Prove missing or conflicting route rules never default to approval (Sheet 02 A2, Sheet 07 P3)."""
        match = evaluate_policy_route(
            policy=self.policy,
            application_category="NEW_INSTITUTION",
            institution_category=Institution.InstitutionCategory.PRIVATE_SELF_FINANCING,
            is_new_institution=True,
        )
        self.assertEqual(match["matched_count"], 1)
        self.assertEqual(match["selected_route"]["route_code"], "NEW_INST_SCRUTINY_EVC")

        unmatched = evaluate_policy_route(
            policy=self.policy,
            application_category="UNKNOWN_CATEGORY",
            institution_category=Institution.InstitutionCategory.PRIVATE_SELF_FINANCING,
            is_new_institution=True,
        )
        self.assertEqual(unmatched["matched_count"], 0)
        self.assertIsNone(unmatched["selected_route"])

    def test_committee_and_scoped_obligation_document_queries(self) -> None:
        """Verify Committee membership validity and scoped obligation/document selectors."""
        comm = create_committee(
            actor=self.user_ro_north,
            code="EVC-NORTH-01",
            name="Northern EVC Panel 1",
            committee_type=Committee.CommitteeType.EVC,
            region=self.region_north,
        )
        member = add_committee_member(
            actor=self.user_ro_north,
            committee=comm,
            user=self.user_scrutiny_assigned,
            member_role=CommitteeMembership.MemberRole.CHAIRMAN,
        )
        self.assertTrue(member.is_currently_valid())

        doc = DocumentVersion.objects.create(
            object_key="north/doc1.pdf",
            institution=self.inst_north,
            case=self.case_north,
            document_type="FIRE_SAFETY",
            original_filename="fire.pdf",
            content_type="application/pdf",
            size_bytes=1024,
            sha256_digest="a" * 64,
            received_at=timezone.now(),
            uploaded_by=self.user_inst_north,
            quarantine_status=QuarantineStatus.CLEAN,
            acceptance_status=ReviewAcceptanceStatus.ACCEPTED,
        )
        val_rec = DocumentValidityRecord.objects.create(
            institution=self.inst_north,
            document_type="FIRE_SAFETY",
            accepted_version=doc,
            valid_from=timezone.now().date(),
            valid_until=(timezone.now() + timedelta(days=365)).date(),
            state=ValidityMonitorState.VALID,
            accepted_by=self.user_ro_north,
            accepted_at=timezone.now(),
        )
        oblig = Obligation.objects.create(
            institution=self.inst_north,
            case=self.case_north,
            source_command_ref="CMD-1",
            obligation_code="OBLIG-1",
            condition_text="Submit faculty list",
            evidence_requirement="Signed PDF",
            due_at=timezone.now() + timedelta(days=30),
            state=ObligationState.OPEN,
        )

        self.assertEqual(list(scope_documents_queryset(self.user_inst_north)), [doc])
        self.assertEqual(list(scope_documents_queryset(self.user_inst_south)), [])
        self.assertEqual(list(scope_validity_records_queryset(self.user_inst_north)), [val_rec])
        self.assertEqual(list(scope_validity_records_queryset(self.user_inst_south)), [])
        self.assertEqual(list(scope_obligations_queryset(self.user_inst_north)), [oblig])
        self.assertEqual(list(scope_obligations_queryset(self.user_inst_south)), [])
