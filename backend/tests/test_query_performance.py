"""Sheet 07 N4 & Q4: Query Performance (Zero N+1), Pagination, and Operational Telemetry Suite."""
from __future__ import annotations

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.utils import timezone

from apps.access.models import RoleAssignment, RoleCode
from apps.cases.models import StageType
from apps.cases.services import submit_or_import_application
from apps.compliance.models import Obligation
from apps.organisation.models import Bureau, Institution, Region
from apps.outbox.selectors import select_operations_metrics
from apps.policy.models import PolicyVersion
from apps.reporting.selectors import generate_statutory_report

User = get_user_model()


class Sheet07Q4QueryPerformanceAndTelemetryTests(TestCase):
    """Verify zero N+1 query scaling on case/obligation/report lists, pagination on lists, and operational metrics."""

    def setUp(self) -> None:
        self.region = Region.objects.create(code="ERO-Q4", name="Eastern Region Q4", headquarters_city="Kolkata")
        self.bureau = Bureau.objects.create(code="BUR-Q4", name="Bureau Q4")
        self.policy = PolicyVersion.objects.create(
            policy_code="APH-Q4",
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

        self.ro_user = User.objects.create_user(username="ro_q4", password="Password123!")
        RoleAssignment.objects.create(
            user=self.ro_user,
            role=RoleCode.BUREAU_OFFICER,
            bureau=self.bureau,
            region=self.region,
        )

        for idx in range(12):
            inst = Institution.objects.create(
                permanent_id=f"INST-Q4-{idx:02d}",
                name=f"Eastern College {idx}",
                region=self.region,
                state="West Bengal",
            )
            case = submit_or_import_application(
                actor=self.ro_user,
                institution=inst,
                source_id=f"SRC-Q4-{idx:02d}",
                academic_cycle="2026-27",
                application_category="EOA",
                responsible_bureau=self.bureau,
            )
            Obligation.objects.create(
                institution=inst,
                case=case,
                source_command_ref=f"CMD-Q4-{idx}",
                obligation_code=f"OBL-{idx}",
                condition_text="Maintain faculty ratio",
                evidence_requirement="Signed roster",
                due_at=timezone.now(),
            )

    def test_zero_n_plus_1_on_lists_and_reports_plus_pagination_and_telemetry(self) -> None:
        """Prove bounded query count (zero N+1) across 12 institutions/cases/obligations, pagination, and operational metrics."""
        # 1. Statutory report query count is constant O(1) (5 queries total even with 12 cases/institutions, proving zero N+1)
        with self.assertNumQueries(5):
            rep = generate_statutory_report(self.ro_user, report_code="application_pendency")
        self.assertEqual(len(rep["rows"]), 12)

        with self.assertNumQueries(5):
            ob_rep = generate_statutory_report(self.ro_user, report_code="undertaking_compliance")
        self.assertEqual(len(ob_rep["rows"]), 12)

        # 2. HTTP list pagination check
        client = Client()
        client.post(
            "/api/v1/auth/login/",
            data='{"username": "ro_q4", "password": "Password123!"}',
            content_type="application/json",
        )
        page1 = client.get("/api/v1/cases/?page_size=5").json()
        self.assertEqual(page1["count"], 12)
        self.assertEqual(len(page1["results"]), 5)
        self.assertIsNotNone(page1["next"])

        # 3. Operational telemetry metrics check (Sheet 07 Q4)
        metrics = select_operations_metrics()
        for key in (
            "data_as_of",
            "outbox_backlog",
            "queue_age_seconds",
            "stale_leases",
            "failed_jobs",
            "unknown_reconciling_jobs",
            "due_lag_seconds",
        ):
            self.assertIn(key, metrics)
