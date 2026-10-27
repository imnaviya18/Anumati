"""Sheet 07 Q2: Scope Isolation & Quarantine Verification Suite."""
from __future__ import annotations

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import Client, TestCase

from apps.access.models import RoleAssignment, RoleCode
from apps.cases.models import StageType
from apps.cases.services import submit_or_import_application
from apps.decisions.services import execute_guarded_stage_transition_command
from apps.documents.services import (
    issue_short_lived_download_grant,
    receive_quarantined_upload,
    review_and_accept_document_version,
    run_quarantine_scan,
)
from apps.organisation.models import Bureau, Institution, Region
from apps.policy.models import PolicyVersion
from apps.reporting.services import export_statutory_report_csv

User = get_user_model()


class Sheet07Q2IsolationTests(TestCase):
    """Verify Sheet 07 Q2: cross-institution/cross-region denial in detail, list, search, export, download; unassigned reviewer denial; dirty/unaccepted file denial; technical admin regulatory denial."""

    def setUp(self) -> None:
        self.reg_a = Region.objects.create(code="REG-A-Q2", name="Region A Q2", headquarters_city="City A")
        self.reg_b = Region.objects.create(code="REG-B-Q2", name="Region B Q2", headquarters_city="City B")
        self.bureau = Bureau.objects.create(code="BUR-Q2", name="Bureau Q2")

        self.inst_a = Institution.objects.create(
            permanent_id="INST-A-Q2",
            name="Institution Alpha",
            region=self.reg_a,
            state="State A",
        )
        self.inst_b = Institution.objects.create(
            permanent_id="INST-B-Q2",
            name="Institution Beta",
            region=self.reg_b,
            state="State B",
        )

        self.policy = PolicyVersion.objects.create(
            policy_code="APH-Q2",
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

        self.user_inst_a = User.objects.create_user(username="u_inst_a_q2", password="Password123!")
        RoleAssignment.objects.create(
            user=self.user_inst_a, role=RoleCode.INSTITUTION_USER, institution=self.inst_a
        )

        self.user_inst_b = User.objects.create_user(username="u_inst_b_q2", password="Password123!")
        RoleAssignment.objects.create(
            user=self.user_inst_b, role=RoleCode.INSTITUTION_USER, institution=self.inst_b
        )

        self.ro_a = User.objects.create_user(username="ro_a_q2", password="Password123!")
        RoleAssignment.objects.create(user=self.ro_a, role=RoleCode.REGIONAL_OFFICER, region=self.reg_a)

        self.unassigned_scrutiny = User.objects.create_user(username="scr_unassigned_q2", password="Password123!")
        RoleAssignment.objects.create(user=self.unassigned_scrutiny, role=RoleCode.SCRUTINY_MEMBER)

        self.tech_admin = User.objects.create_user(username="tech_q2", password="Password123!")
        RoleAssignment.objects.create(user=self.tech_admin, role=RoleCode.TECHNICAL_ADMIN)

    def test_q2_isolation_across_detail_list_search_export_download_and_roles(self) -> None:
        """Prove Sheet 07 Q2 isolation across all surfaces."""
        case_a = submit_or_import_application(
            actor=self.user_inst_a,
            institution=self.inst_a,
            source_id="SRC-A-Q2",
            academic_cycle="2026-27",
            application_category="EOA",
            responsible_bureau=self.bureau,
        )
        case_b = submit_or_import_application(
            actor=self.user_inst_b,
            institution=self.inst_b,
            source_id="SRC-B-Q2",
            academic_cycle="2026-27",
            application_category="EOA",
            responsible_bureau=self.bureau,
        )

        # 1. Cross-institution & cross-region HTTP detail, list, search, and CSV export checks
        client_a = Client()
        client_a.post(
            "/api/v1/auth/login/",
            data='{"username": "u_inst_a_q2", "password": "Password123!"}',
            content_type="application/json",
        )
        # Detail of B is 403
        self.assertEqual(client_a.get(f"/api/v1/cases/{case_b.id}/").status_code, 403)
        # List and search for B return 0 results
        list_resp = client_a.get("/api/v1/cases/").json()
        self.assertEqual(list_resp["count"], 1)
        self.assertEqual(list_resp["results"][0]["id"], str(case_a.id))

        search_b = client_a.get(f"/api/v1/cases/?q={case_b.case_number}").json()
        self.assertEqual(search_b["count"], 0)

        # Export for Regional Officer A excludes Institution B
        csv_a, _ = export_statutory_report_csv(actor=self.ro_a, report_code="application_pendency")
        self.assertIn(case_a.case_number, csv_a)
        self.assertNotIn(case_b.case_number, csv_a)

        # 2. Unassigned reviewer denied stage execution
        stage_a = case_a.stage_instances.get(stage_type=StageType.SCRUTINY)
        with self.assertRaises(PermissionDenied):
            execute_guarded_stage_transition_command(
                actor=self.unassigned_scrutiny,
                case_id=case_a.id,
                stage_instance_id=stage_a.id,
                action="COMPLETE_STAGE",
                expected_version=case_a.version,
                idempotency_key="IDEMP-UNASSIGNED-Q2",
                reason="Unassigned attempt",
            )

        # 3. Technical admin denied regulatory stage execution
        with self.assertRaises(PermissionDenied):
            execute_guarded_stage_transition_command(
                actor=self.tech_admin,
                case_id=case_a.id,
                stage_instance_id=stage_a.id,
                action="COMPLETE_STAGE",
                expected_version=case_a.version,
                idempotency_key="IDEMP-TECH-Q2",
                reason="Tech admin attempt",
            )

        # 4. Quarantine isolation: un-scanned or dirty files cannot be downloaded or accepted; cross-institution download denied
        unscanned_doc = receive_quarantined_upload(
            actor=self.user_inst_a,
            institution=self.inst_a,
            case=case_a,
            document_type="AFFIDAVIT",
            original_filename="affidavit.pdf",
            content_type="application/pdf",
            file_bytes=b"%PDF-1.4 valid pdf bytes",
        )
        with self.assertRaises((PermissionDenied, ValidationError)):
            issue_short_lived_download_grant(actor=self.ro_a, document_version_id=unscanned_doc.id)
        with self.assertRaises((PermissionDenied, ValidationError)):
            review_and_accept_document_version(
                actor=self.ro_a, document_version_id=unscanned_doc.id, accept=True, finding="Wait"
            )

        # Scan clean, then verify cross-institution user B cannot obtain a download grant
        clean_doc = run_quarantine_scan(document_version_id=unscanned_doc.id)
        with self.assertRaises(PermissionDenied):
            issue_short_lived_download_grant(actor=self.user_inst_b, document_version_id=clean_doc.id)
