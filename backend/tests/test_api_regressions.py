import base64
import tempfile
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient
from apps.access.models import RoleAssignment, RoleCode
from apps.cases.models import ApplicationCase, CaseStatus
from apps.organisation.models import Institution, Region
from apps.outbox.models import OutboxEvent, OutboxState
from apps.outbox.services import execute_outbox_event


class APIRegressionTests(TestCase):
    def setUp(self):
        self.region = Region.objects.create(code="API-A", name="API A")
        self.other_region = Region.objects.create(code="API-B", name="API B")
        self.inst = Institution.objects.create(
            permanent_id="API-I",
            name="API Institution",
            region=self.region,
            state="Delhi",
        )
        self.other = Institution.objects.create(
            permanent_id="API-O",
            name="Other Institution",
            region=self.other_region,
            state="Other",
        )
        self.user = get_user_model().objects.create_user(
            username="api-inst", password="test-password"
        )
        RoleAssignment.objects.create(
            user=self.user, role=RoleCode.INSTITUTION_USER, institution=self.inst
        )
        self.admin = get_user_model().objects.create_user(username="api-admin")
        RoleAssignment.objects.create(user=self.admin, role=RoleCode.TECHNICAL_ADMIN)
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def test_login_requires_csrf_for_anonymous_browser(self):
        client = APIClient(enforce_csrf_checks=True)
        payload = {"username": "api-inst", "password": "test-password"}
        self.assertEqual(client.post("/api/v1/auth/login/", payload).status_code, 403)
        token = client.get("/api/v1/auth/csrf/").json()["csrfToken"]
        self.assertEqual(
            client.post(
                "/api/v1/auth/login/", payload, HTTP_X_CSRFTOKEN=token
            ).status_code,
            200,
        )
        self.assertIn(
            "INSTITUTION_USER", client.get("/api/v1/auth/me/").json()["scope"]["roles"]
        )

    def test_intake_detail_and_duplicate_conflict(self):
        payload = {
            "institution_id": str(self.inst.id),
            "source_id": "API-SOURCE",
            "academic_cycle": "2026-27",
            "application_category": "EOA",
        }
        response = self.client.post("/api/v1/cases/", payload, format="json")
        self.assertEqual(response.status_code, 201, response.content)
        detail = self.client.get(f"/api/v1/cases/{response.json()['id']}/")
        self.assertEqual(detail.status_code, 200, detail.content)
        self.assertEqual(detail.json()["deficiency_cycles"], [])
        self.assertEqual(
            self.client.post("/api/v1/cases/", payload, format="json").status_code, 409
        )
        payload["institution_id"] = "not-a-uuid"
        self.assertEqual(
            self.client.post("/api/v1/cases/", payload, format="json").status_code, 400
        )

    def test_route_resolution_denies_other_institution(self):
        case = ApplicationCase.objects.create(
            case_number="OTHER",
            source_id="OTHER",
            institution=self.other,
            region=self.other_region,
            academic_cycle="2026-27",
            application_category="EOA",
            status=CaseStatus.POLICY_REVIEW_REQUIRED,
        )
        response = self.client.post(
            f"/api/v1/cases/{case.id}/resolve-route/",
            {"reason": "retry"},
            format="json",
        )
        self.assertEqual(response.status_code, 403)
        case.refresh_from_db()
        self.assertEqual(case.version, 1)

    def test_directory_scope_and_admin_creation(self):
        response = self.client.get("/api/v1/organisation/")
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(
            [x["code"] for x in response.json()["institutions"]], ["API-I"]
        )
        self.client.force_authenticate(self.admin)
        for payload in [
            {
                "entity_type": "REGION",
                "code": "NEW",
                "name": "New Region",
                "headquarters": "Delhi",
            },
            {"entity_type": "BUREAU", "code": "NEW", "name": "New Bureau"},
            {
                "entity_type": "INSTITUTION",
                "code": "NEW",
                "name": "New Institute",
                "region_id": str(self.region.id),
                "state_name": "Delhi",
            },
            {
                "entity_type": "COMMITTEE",
                "code": "NEW",
                "name": "New Committee",
                "region_id": str(self.region.id),
            },
        ]:
            response = self.client.post("/api/v1/organisation/", payload, format="json")
            self.assertEqual(response.status_code, 201, response.content)

    def test_document_upload_worker_scan_download_and_review_denial(self):
        with tempfile.TemporaryDirectory() as storage, override_settings(
            PRIVATE_STORAGE_ROOT=storage
        ):
            payload = {
                "institution_id": str(self.inst.id),
                "document_type": "CERTIFICATE",
                "original_filename": "test.pdf",
                "declared_mime_type": "application/pdf",
                "content_base64": base64.b64encode(
                    b"%PDF-1.7\n test evidence"
                ).decode(),
            }
            response = self.client.post("/api/v1/documents/", payload, format="json")
            self.assertEqual(response.status_code, 201, response.content)
            doc_id = response.json()["id"]
            self.assertEqual(response.json()["lifecycle_state"], "QUARANTINED")
            self.assertEqual(
                self.client.post(
                    f"/api/v1/documents/{doc_id}/download-grant/"
                ).status_code,
                403,
            )
            event = OutboxEvent.objects.get(logical_id=f"doc-scan:{doc_id}")
            execute_outbox_event(event_id=event.id)
            response = self.client.get("/api/v1/documents/")
            self.assertEqual(response.status_code, 200, response.content)
            self.assertEqual(response.json()[0]["lifecycle_state"], "CLEAN")
            grant = self.client.post(f"/api/v1/documents/{doc_id}/download-grant/")
            self.assertEqual(grant.status_code, 200, grant.content)
            downloaded = self.client.get(
                f"/api/v1/documents/{doc_id}/download-grant/?token={grant.json()['grant_token']}"
            )
            self.assertEqual(downloaded.status_code, 200, downloaded.content)
            self.assertTrue(downloaded.content.startswith(b"%PDF"))
            response = self.client.post(
                f"/api/v1/documents/{doc_id}/review/",
                {"accept": True, "notes": "Reviewed"},
                format="json",
            )
            self.assertEqual(response.status_code, 403, response.content)

    def test_operator_replay_calls_real_service_and_rejects_completed(self):
        self.client.force_authenticate(self.admin)
        event = OutboxEvent.objects.create(
            logical_id="api-replay",
            event_type="TEST",
            state=OutboxState.FAILED_OWNED,
            next_attempt_at=timezone.now(),
        )
        url = f"/api/v1/outbox/failed/{event.id}/replay/"
        response = self.client.post(url, {"reason": "Service restored"}, format="json")
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["state"], "PENDING")
        self.assertEqual(
            self.client.post(url, {"reason": "again"}, format="json").status_code, 400
        )

    def test_http_stage_and_decision_commit_replay_and_conflict(self):
        from apps.policy.models import PolicyVersion
        from apps.cases.models import StageInstance, StageType, StageStatus
        from apps.access.models import CaseAssignment

        policy = PolicyVersion.objects.create(
            policy_code="API-P",
            version_number=1,
            academic_cycle="2026-27",
            state="ACTIVE",
        )
        case = ApplicationCase.objects.create(
            case_number="API-FLOW",
            source_id="API-FLOW",
            institution=self.inst,
            region=self.region,
            academic_cycle="2026-27",
            application_category="EOA",
            status=CaseStatus.IN_STAGE_PROCESSING,
            pinned_policy_version=policy,
            prescribed_stages=["SCRUTINY"],
            current_stage_type="SCRUTINY",
        )
        reviewer = get_user_model().objects.create_user(username="api-reviewer")
        RoleAssignment.objects.create(user=reviewer, role=RoleCode.SCRUTINY_MEMBER)
        stage = StageInstance.objects.create(
            case=case,
            stage_type=StageType.SCRUTINY,
            sequence_number=1,
            status=StageStatus.IN_PROGRESS,
            assigned_officer=reviewer,
        )
        CaseAssignment.objects.create(
            user=reviewer,
            case=case,
            stage_instance=stage,
            assignment_scope="STAGE_REVIEWER",
            reason="test",
        )
        self.client.force_authenticate(reviewer)
        url = f"/api/v1/cases/{case.id}/stages/{stage.id}/transition/"
        payload = {
            "action": "COMPLETE_STAGE",
            "expected_version": 1,
            "idempotency_key": "api-stage",
            "reason": "All findings reviewed",
        }
        response = self.client.post(url, payload, format="json")
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["case_status"], "READY_FOR_DISPOSITION")
        self.assertEqual(self.client.post(url, payload, format="json").status_code, 200)
        authority = get_user_model().objects.create_user(username="api-authority")
        RoleAssignment.objects.create(
            user=authority,
            role=RoleCode.COMPETENT_AUTHORITY,
            delegated_powers=["GRANT_EOA"],
        )
        self.client.force_authenticate(authority)
        url = f"/api/v1/decisions/cases/{case.id}/decide/"
        payload = {
            "outcome": "GRANT_EOA",
            "expected_version": 2,
            "idempotency_key": "api-decision",
            "reasons": "Verified decision package",
            "delegated_power_ref": "GRANT_EOA",
        }
        response = self.client.post(url, payload, format="json")
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(self.client.post(url, payload, format="json").status_code, 200)
        payload["reasons"] = "different"
        self.assertEqual(self.client.post(url, payload, format="json").status_code, 409)

    def test_evc_list_scope_and_cross_institution_readiness_denied(self):
        from apps.cases.models import StageInstance

        case = ApplicationCase.objects.create(
            case_number="EVC-OTHER",
            source_id="EVC-OTHER",
            institution=self.other,
            region=self.other_region,
            academic_cycle="2026-27",
            application_category="EOA",
        )
        stage = StageInstance.objects.create(
            case=case, stage_type="EVC", sequence_number=1
        )
        self.assertEqual(self.client.get("/api/v1/evc/").status_code, 200)
        response = self.client.post(
            "/api/v1/evc/",
            {"case_id": str(case.id), "stage_instance_id": str(stage.id)},
            format="json",
        )
        self.assertEqual(response.status_code, 403, response.content)

    def test_user_provisioning_and_role_administration(self):
        self.assertEqual(self.client.get("/api/v1/auth/users/").status_code, 403)
        self.client.force_authenticate(self.admin)
        response = self.client.post(
            "/api/v1/auth/users/",
            {
                "username": "new-institution",
                "password": "Strong-test-8821!",
                "email": "new@example.test",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.content)
        user_id = response.json()["id"]
        response = self.client.post(
            "/api/v1/access/role-assignments/",
            {
                "user_id": user_id,
                "role": "INSTITUTION_USER",
                "institution_id": str(self.inst.id),
                "reason": "Institution representative appointment",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.content)
        response = self.client.get("/api/v1/access/role-assignments/")
        self.assertEqual(response.status_code, 200, response.content)
        self.assertTrue(any(x["institution_code"] == "API-I" for x in response.json()))

    def test_worker_does_not_claim_disabled_email_was_sent(self):
        from apps.notifications.models import LogicalAlert

        alert = LogicalAlert.objects.create(
            recipient=self.user,
            channel="EMAIL_SMTP",
            institution=self.inst,
            milestone_code="TEST",
            subject="Test",
            body="Test",
        )
        event = OutboxEvent.objects.create(
            logical_id="disabled-smtp",
            event_type="DELIVER_ALERT",
            payload={"logical_alert_id": str(alert.id)},
            next_attempt_at=timezone.now(),
        )
        with override_settings(EMAIL_DELIVERY_ENABLED=False):
            result = execute_outbox_event(event_id=event.id)
        self.assertEqual(result["status"], "FAILED_OWNED")
        alert.refresh_from_db()
        self.assertEqual(alert.outcome_state, "FAILED")

    def test_policy_cannot_activate_without_regression_cases_or_revalidate_active(self):
        from apps.policy.models import PolicyVersion

        user = get_user_model().objects.create_user(username="api-policy")
        RoleAssignment.objects.create(user=user, role="POLICY_ADMIN")
        self.client.force_authenticate(user)
        policy = PolicyVersion.objects.create(
            policy_code="EMPTY",
            version_number=1,
            academic_cycle="2026-27",
            state="VALIDATED",
            route_rules=[
                {
                    "route_code": "SCRUTINY",
                    "conditions": {"application_category": "EOA"},
                    "stages": ["SCRUTINY"],
                }
            ],
        )
        response = self.client.post(
            f"/api/v1/policy/{policy.id}/dry-run/", {}, format="json"
        )
        self.assertEqual(response.status_code, 400, response.content)
        policy.state = "ACTIVE"
        policy.save()
        response = self.client.post(
            f"/api/v1/policy/{policy.id}/validate/", {}, format="json"
        )
        self.assertEqual(response.status_code, 400, response.content)
        policy.refresh_from_db()
        self.assertEqual(policy.state, "ACTIVE")

    def test_authoritative_pending_draft_and_demo_production_activation_are_blocked(
        self,
    ):
        from apps.policy.models import PolicyVersion

        authority = get_user_model().objects.create_user(username="policy-owner")
        RoleAssignment.objects.create(user=authority, role="COMPETENT_AUTHORITY")
        self.client.force_authenticate(authority)
        policy = PolicyVersion.objects.create(
            policy_code="PENDING-REAL",
            version_number=1,
            academic_cycle="2026-27",
            state="DRY_RUN_PASSED",
            is_demonstration=False,
            provenance={"pending_validation": ["2026-27 addendum"]},
        )
        response = self.client.post(
            f"/api/v1/policy/{policy.id}/activate/", {}, format="json"
        )
        self.assertEqual(response.status_code, 400, response.content)
        policy.is_demonstration = True
        policy.save()
        with override_settings(ALLOW_DEMONSTRATION_POLICIES=False):
            response = self.client.post(
                f"/api/v1/policy/{policy.id}/activate/", {}, format="json"
            )
        self.assertEqual(response.status_code, 400, response.content)
