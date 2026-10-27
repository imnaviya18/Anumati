"""Stage 6 tests: policy governance, deterministic case summaries, standardised communications, role dashboards, 6 statutory reports, and REST APIs."""
from __future__ import annotations

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import Client, TestCase

from apps.access.models import RoleAssignment, RoleCode
from apps.cases.models import CaseStatus, StageType
from apps.cases.services import submit_or_import_application
from apps.communications.models import CommunicationTemplate
from apps.communications.services import (
    issue_standardised_communication,
    render_electronic_case_summary,
)
from apps.organisation.models import Bureau, Institution, Region
from apps.outbox.models import OutboxEvent
from apps.policy.models import PolicyVersion
from apps.policy.services import (
    approve_and_activate_policy_version,
    approve_policy_version,
    draft_policy_version,
    migrate_cases_to_policy_version,
    run_policy_dry_run,
    validate_policy_version,
)
from apps.reporting.selectors import ALLOWED_REPORT_CODES, generate_statutory_report, select_role_dashboard_snapshot
from apps.reporting.services import export_statutory_report_csv

User = get_user_model()


class Stage6PolicyCommsReportsApiTests(TestCase):
    """Verify Sheet 04 J1-J6, Sheet 07 P3-P5, PS Sections A.5, A.6, B, F.3."""

    def setUp(self) -> None:
        self.region_north = Region.objects.create(
            code="NRO-S6", name="Northern Region S6", headquarters_city="Kanpur"
        )
        self.region_south = Region.objects.create(
            code="SRO-S6", name="Southern Region S6", headquarters_city="Chennai"
        )
        self.bureau = Bureau.objects.create(code="APPROVAL-S6", name="Approval Bureau S6")

        self.inst_north = Institution.objects.create(
            permanent_id="INST-N-S6",
            name="North Engineering Institute",
            region=self.region_north,
            state="Uttar Pradesh",
            category=Institution.InstitutionCategory.PRIVATE_SELF_FINANCING,
            is_new_institution=False,
        )
        self.inst_south = Institution.objects.create(
            permanent_id="INST-S-S6",
            name="South Tech College",
            region=self.region_south,
            state="Tamil Nadu",
            category=Institution.InstitutionCategory.PRIVATE_SELF_FINANCING,
            is_new_institution=True,
        )

        self.policy_admin = User.objects.create_user(username="policy_gov_s6", password="Password123!")
        RoleAssignment.objects.create(user=self.policy_admin, role=RoleCode.POLICY_ADMIN)

        self.ca_user = User.objects.create_user(username="ca_s6", password="Password123!")
        RoleAssignment.objects.create(
            user=self.ca_user,
            role=RoleCode.COMPETENT_AUTHORITY,
            delegated_powers=["EC_APPROVAL_POWER"],
        )

        self.ro_north = User.objects.create_user(username="ro_north_s6", password="Password123!")
        RoleAssignment.objects.create(
            user=self.ro_north,
            role=RoleCode.REGIONAL_OFFICER,
            region=self.region_north,
        )

        self.inst_north_user = User.objects.create_user(username="inst_north_s6", password="Password123!")
        RoleAssignment.objects.create(
            user=self.inst_north_user,
            role=RoleCode.INSTITUTION_USER,
            institution=self.inst_north,
        )

        self.tech_admin = User.objects.create_user(username="tech_s6", password="Password123!")
        RoleAssignment.objects.create(user=self.tech_admin, role=RoleCode.TECHNICAL_ADMIN)

    def test_policy_lifecycle_validation_dry_run_activation_and_explicit_migration(self) -> None:
        """Prove Sheet 04 J1-J3 & Sheet 07 P3-P4: draft -> validate -> dry-run -> activate -> explicit migration."""
        # 1. Technical admin is denied policy governance
        with self.assertRaises(PermissionDenied):
            draft_policy_version(
                actor=self.tech_admin,
                policy_code="APH-2026",
                version_number=1,
                academic_cycle="2026-27",
            )

        # 2. Invalid policy with duplicate loop / invalid stage fails validation
        bad_policy = draft_policy_version(
            actor=self.policy_admin,
            policy_code="APH-BAD",
            version_number=1,
            academic_cycle="2026-27",
            route_rules=[
                {
                    "route_code": "LOOP_ROUTE",
                    "conditions": {"application_category": "EOA"},
                    "stages": [StageType.SCRUTINY, StageType.SCRUTINY],
                },
                {
                    "route_code": "INVALID_STAGE_ROUTE",
                    "conditions": {"application_category": "NEW"},
                    "stages": ["NON_EXISTENT_STAGE"],
                },
            ],
        )
        with self.assertRaises(ValidationError):
            validate_policy_version(actor=self.policy_admin, policy=bad_policy)

        # 3. Valid policy v1 passes validation, dry-run (including ambiguous case check), and activation
        policy_v1 = draft_policy_version(
            actor=self.policy_admin,
            policy_code="APH-2026",
            version_number=1,
            academic_cycle="2026-27",
            route_rules=[
                {
                    "route_code": "ONLY_SCRUTINY",
                    "conditions": {"application_category": "EOA_SIMPLE", "is_new_institution": False},
                    "stages": [StageType.SCRUTINY],
                },
                {
                    "route_code": "SCRUTINY_AND_EVC",
                    "conditions": {"application_category": "NEW_INSTITUTION", "is_new_institution": True},
                    "stages": [StageType.SCRUTINY, StageType.EVC],
                },
            ],
            regression_cases=[
                {
                    "name": "Simple EoA routes to ONLY_SCRUTINY",
                    "application_category": "EOA_SIMPLE",
                    "institution_category": Institution.InstitutionCategory.PRIVATE_SELF_FINANCING,
                    "is_new_institution": False,
                    "expected_route_code": "ONLY_SCRUTINY",
                },
                {
                    "name": "Unmatched category requires policy review (never defaults to approval)",
                    "application_category": "UNKNOWN_SPECIAL_SCHEME",
                    "institution_category": Institution.InstitutionCategory.PRIVATE_SELF_FINANCING,
                    "is_new_institution": False,
                    "expect_review_required": True,
                },
            ],
        )
        validate_policy_version(actor=self.policy_admin, policy=policy_v1)
        self.assertEqual(policy_v1.state, PolicyVersion.PolicyState.VALIDATED)

        run_policy_dry_run(actor=self.policy_admin, policy=policy_v1)
        self.assertEqual(policy_v1.state, PolicyVersion.PolicyState.DRY_RUN_PASSED)

        approve_policy_version(actor=self.ca_user, policy=policy_v1, reason="Reviewed test policy v1")
        approve_and_activate_policy_version(actor=self.ca_user, policy=policy_v1)
        self.assertEqual(policy_v1.state, PolicyVersion.PolicyState.ACTIVE)

        # Submit and route a case under policy_v1 (intake automatically resolves active policy_v1)
        case = submit_or_import_application(
            actor=self.inst_north_user,
            institution=self.inst_north,
            source_id="SRC-S6-001",
            academic_cycle="2026-27",
            application_category="EOA_SIMPLE",
            responsible_bureau=self.bureau,
        )
        self.assertEqual(case.pinned_policy_version_id, policy_v1.id)
        self.assertEqual(case.status, CaseStatus.IN_STAGE_PROCESSING)

        # 4. Draft, validate, dry-run, and activate policy_v2; prove existing case stays pinned to v1!
        policy_v2 = draft_policy_version(
            actor=self.policy_admin,
            policy_code="APH-2026",
            version_number=2,
            academic_cycle="2026-27",
            calendar_version="CAL-v2",
            route_rules=policy_v1.route_rules,
            regression_cases=policy_v1.regression_cases,
        )
        validate_policy_version(actor=self.policy_admin, policy=policy_v2)
        run_policy_dry_run(actor=self.policy_admin, policy=policy_v2)
        approve_policy_version(actor=self.ca_user, policy=policy_v2, reason="Reviewed test policy v2")
        approve_and_activate_policy_version(actor=self.ca_user, policy=policy_v2)

        policy_v1.refresh_from_db()
        case.refresh_from_db()
        self.assertEqual(policy_v1.state, PolicyVersion.PolicyState.RETIRED)
        self.assertEqual(case.pinned_policy_version_id, policy_v1.id)

        # 5. Explicit authorised migration moves open case to v2 with audit and reason
        migration = migrate_cases_to_policy_version(
            actor=self.ca_user,
            source_policy=policy_v1,
            target_policy=policy_v2,
            case_ids=[str(case.id)],
            reason="Migrated to APH-2026 v2 per Council notification.",
        )
        case.refresh_from_db()
        self.assertEqual(case.pinned_policy_version_id, policy_v2.id)
        self.assertEqual(migration.affected_case_ids, [str(case.id)])

    def test_electronic_case_summary_and_standardised_communications(self) -> None:
        """Prove PS-A.5 & PS-A.6: deterministic case summary never mutates case state/version; communications queue to outbox."""
        policy = PolicyVersion.objects.create(
            policy_code="APH-COMM",
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
        case = submit_or_import_application(
            actor=self.inst_north_user,
            institution=self.inst_north,
            source_id="SRC-COMM-01",
            academic_cycle="2026-27",
            application_category="EOA",
            responsible_bureau=self.bureau,
        )
        version_before = case.version
        status_before = case.status

        summary1 = render_electronic_case_summary(actor=self.ro_north, case=case)
        summary2 = render_electronic_case_summary(actor=self.ro_north, case=case)
        case.refresh_from_db()

        self.assertEqual(case.version, version_before)
        self.assertEqual(case.status, status_before)
        self.assertEqual(summary1.rendered_body, summary2.rendered_body)
        self.assertIn(case.case_number, summary1.rendered_body)

        # Standardised communication template
        comm_tpl = CommunicationTemplate.objects.create(
            template_code="DEFICIENCY_NOTICE_V1",
            version_number=1,
            category=CommunicationTemplate.TemplateCategory.DEFICIENCY_NOTICE,
            policy_version=policy,
            subject_template="Deficiency Notice for {case_number}",
            body_template="Institution {institution_name} ({institution_code}): {custom_notice}",
            required_fields=["case_number", "institution_name", "custom_notice"],
            is_active=True,
        )
        # Missing required field fails
        with self.assertRaises(ValidationError):
            issue_standardised_communication(actor=self.ro_north, case=case, template=comm_tpl)

        rendered = issue_standardised_communication(
            actor=self.ro_north,
            case=case,
            template=comm_tpl,
            extra_fields={"custom_notice": "Submit fire safety certificate within 7 days."},
        )
        self.assertIn("Submit fire safety certificate", rendered.rendered_body)
        self.assertTrue(
            OutboxEvent.objects.filter(
                case=case,
                event_type="COMMUNICATION_DISPATCH",
            ).exists()
        )

    def test_role_dashboards_six_statutory_reports_and_rest_apis(self) -> None:
        """Prove PS-B & PS-F.3: role dashboards with data_as_of, exact 6 statutory reports + CSV export, and scoped REST APIs."""
        PolicyVersion.objects.create(
            policy_code="APH-REP",
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
        case_n = submit_or_import_application(
            actor=self.inst_north_user,
            institution=self.inst_north,
            source_id="SRC-REP-N",
            academic_cycle="2026-27",
            application_category="EOA",
            responsible_bureau=self.bureau,
        )

        inst_south_user = User.objects.create_user(username="inst_south_s6", password="Password123!")
        RoleAssignment.objects.create(
            user=inst_south_user,
            role=RoleCode.INSTITUTION_USER,
            institution=self.inst_south,
        )
        case_s = submit_or_import_application(
            actor=inst_south_user,
            institution=self.inst_south,
            source_id="SRC-REP-S",
            academic_cycle="2026-27",
            application_category="EOA",
            responsible_bureau=self.bureau,
        )

        # Dashboard for RO North sees only North case; CA sees both
        dash_ro = select_role_dashboard_snapshot(self.ro_north)
        self.assertIn("data_as_of", dash_ro)
        self.assertEqual(dash_ro["total_visible_cases"], 1)

        dash_ca = select_role_dashboard_snapshot(self.ca_user)
        self.assertEqual(dash_ca["total_visible_cases"], 2)

        # Verify all 6 statutory reports succeed and respect scope, and any 7th report code is rejected
        for code in ALLOWED_REPORT_CODES:
            rep = generate_statutory_report(self.ro_north, report_code=code)
            self.assertEqual(rep["report_code"], code)
            self.assertIn("data_as_of", rep)
            csv_str, _ = export_statutory_report_csv(actor=self.ro_north, report_code=code)
            self.assertTrue(len(csv_str.splitlines()) >= 1)

        with self.assertRaises(ValidationError):
            generate_statutory_report(self.ca_user, report_code="unsupported_extra_report")

        # Exercise HTTP API endpoints via Django test Client
        client = Client()
        login_resp = client.post(
            "/api/v1/auth/login/",
            data='{"username": "ro_north_s6", "password": "Password123!"}',
            content_type="application/json",
        )
        self.assertEqual(login_resp.status_code, 200)

        cases_resp = client.get("/api/v1/cases/")
        self.assertEqual(cases_resp.status_code, 200)
        self.assertEqual(cases_resp.json()["count"], 1)

        # Cross-region case detail is denied (403)
        forbidden_detail = client.get(f"/api/v1/cases/{case_s.id}/")
        self.assertEqual(forbidden_detail.status_code, 403)

        csv_resp = client.get("/api/v1/reporting/reports/application_pendency/?export=csv")
        self.assertEqual(csv_resp.status_code, 200)
        self.assertIn("text/csv", csv_resp["Content-Type"])
        self.assertIn(case_n.case_number, csv_resp.content.decode("utf-8"))
        self.assertNotIn(case_s.case_number, csv_resp.content.decode("utf-8"))
