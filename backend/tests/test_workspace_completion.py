from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from rest_framework.test import APIClient
from apps.access.models import RoleAssignment
from apps.policy.models import PolicyVersion, SourceRecord, SyncException
from apps.audit.models import AuditEvent
from apps.organisation.models import Region, Institution, Bureau
from apps.cases.models import ApplicationCase, StageInstance


@override_settings(DEBUG=True, ALLOW_DEMONSTRATION_POLICIES=True)
class WorkspaceCompletionTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.policy_user = self.user("governor", "POLICY_ADMIN")
        self.authority = self.user("authority", "COMPETENT_AUTHORITY")
        self.technical = self.user("technical", "TECHNICAL_ADMIN")
        self.client.force_authenticate(self.policy_user)

    def user(self, name, role):
        user = get_user_model().objects.create_user(username=name)
        RoleAssignment.objects.create(user=user, role=role)
        return user

    def post(self, path, payload):
        return self.client.post(path, payload, format="json")

    def event(self, event_id="event-1", payload=None):
        return self.post("/api/v1/policy/sync-exceptions/", {
            "event_id":event_id,"source_id":"synthetic-reference", "payload":payload or {"display_name":"Demo name"}, "reason":"Synthetic source conflict"})

    def resolve(self, item, action="ACCEPT_SOURCE", **extra):
        return self.post(f"/api/v1/policy/sync-exceptions/{item['id']}/resolve/", {
            "expected_version":item["version"], "action":action,"reason":"Compared the source and local values", **extra})

    def test_sync_deduplication_conflict_audit_and_source_ownership(self):
        first=self.event()
        self.assertEqual(first.status_code,201,first.content)
        item=first.json()
        self.assertEqual(self.event().json()["id"],item["id"])
        self.assertEqual(self.event(payload={"notes":"changed"}).status_code,409)
        self.assertEqual(SyncException.objects.count(),1)
        result=self.resolve(item)
        self.assertEqual(result.status_code,200,result.content)
        self.assertEqual(SourceRecord.objects.get().payload,{"display_name":"Demo name"})
        self.assertEqual(self.resolve(item).status_code,409)
        self.assertTrue(AuditEvent.objects.filter(action="SYNC_EXCEPTION_ACCEPT_SOURCE").exists())
        self.assertEqual(self.event("bad", {"decision":"APPROVED"}).status_code,400)
        self.assertEqual(ApplicationCase.objects.count(),0)

    def test_sync_stale_baseline_requires_fresh_review_and_owner_reassignment(self):
        one=self.event().json()
        two=self.event("event-2", {"display_name":"Other incoming"}).json()
        reassigned=self.resolve(two,"REASSIGN",owner_id=self.authority.id)
        self.assertEqual(reassigned.status_code,200,reassigned.content)
        self.assertEqual(reassigned.json()["owner"],self.authority.username)
        self.assertEqual(self.resolve(one).status_code,200)
        self.assertEqual(self.resolve(reassigned.json()).status_code,409)
        self.assertEqual(self.resolve(reassigned.json(),"KEEP_LOCAL").status_code,200)
        self.assertEqual(SourceRecord.objects.get().payload["display_name"],"Demo name")
        self.assertEqual(self.client.get('/api/v1/policy/sync-exceptions/?state=RESOLVED').json()['count'],2)

    def test_sync_denies_technical_roles_and_production_mock_ingestion(self):
        self.client.force_authenticate(self.technical)
        self.assertEqual(self.event().status_code,403)
        self.assertEqual(self.client.get('/api/v1/policy/sync-exceptions/').status_code,403)
        self.client.force_authenticate(self.policy_user)
        with override_settings(DEBUG=False):
            self.assertEqual(self.event().status_code,403)

    def test_policy_requires_explicit_approval_before_activation(self):
        payload={"policy_code":"LOCAL-TEST","version_number":1,"academic_cycle":"2026-27","is_demonstration":True,
            "route_rules":[{"route_code":"EOA","conditions":{"application_category":"EOA"},"stages":["SCRUTINY"]}],
            "regression_cases":[{"name":"EOA","application_category":"EOA","expected_route_code":"EOA"}]}
        result=self.post('/api/v1/policy/',payload)
        self.assertEqual(result.status_code,201,result.content)
        base=f"/api/v1/policy/{result.json()['id']}/"
        for action in ['validate','dry-run']:
            response=self.post(base+action+'/',{})
            self.assertEqual(response.status_code,200,response.content)
        self.assertEqual(self.post(base+'activate/',{}).status_code,400)
        self.assertEqual(self.post(base+'approve/',{'reason':'Reviewed synthetic rules'}).status_code,403)
        self.client.force_authenticate(self.authority)
        approved=self.post(base+'approve/',{'reason':'Reviewed synthetic rules'})
        self.assertEqual(approved.status_code,200,approved.content)
        self.assertEqual(approved.json()['state'],'APPROVED')
        self.assertEqual(self.post(base+'edit/',{'changes':{},'reason':'mutate'}).status_code,400)
        active=self.post(base+'activate/',{})
        self.assertEqual(active.status_code,200,active.content)
        self.assertEqual(active.json()['state'],'ACTIVE')
        self.assertEqual(PolicyVersion.objects.get().approved_by,self.authority)

    def test_oversight_bureau_filter_workload_and_cross_region_isolation(self):
        bureau=Bureau.objects.create(code='B1',name='Bureau 1')
        region=Region.objects.create(code='R1',name='Region 1')
        other=Region.objects.create(code='R2',name='Region 2')
        officer=get_user_model().objects.create_user(username='regional')
        RoleAssignment.objects.create(user=officer,role='REGIONAL_OFFICER',region=region)
        for i,reg in enumerate([region,other]):
            inst=Institution.objects.create(permanent_id=f'INST-{i}',name=f'Institution {i}',region=reg,state='Synthetic')
            case=ApplicationCase.objects.create(case_number=f'C-{i}',source_id=f'S-{i}',institution=inst,region=reg,responsible_bureau=bureau,academic_cycle='2026-27',application_category='EOA',status='IN_STAGE_PROCESSING',current_stage_type='SCRUTINY')
            StageInstance.objects.create(case=case,stage_type='SCRUTINY',sequence_number=1,assigned_officer=officer)
        self.client.force_authenticate(officer)
        data=self.client.get('/api/v1/reporting/dashboard/?bureau_code=B1').json()
        self.assertEqual(data['total_visible_cases'],1)
        self.assertEqual(data['status_by_bureau'][0]['count'],1)
        self.assertEqual(data['workload_by_officer'][0]['active_cases'],1)
        self.assertEqual(data['status_by_bureau'][0]['pending_count'],1)
        ApplicationCase.objects.filter(region=region).update(status='APPROVED_EOA')
        self.assertEqual(self.client.get('/api/v1/reporting/dashboard/?bureau_code=B1').json()['status_by_bureau'][0]['pending_count'],0)
        self.assertEqual(self.client.get('/api/v1/cases/?region_code=R2').json()['count'],0)
        self.assertEqual(self.client.get('/api/v1/reporting/dashboard/?bureau_code=UNKNOWN').json()['total_visible_cases'],0)

    def test_evidence_cannot_be_reused_from_a_different_processing_case(self):
        from django.core.exceptions import ValidationError
        from django.utils import timezone
        from apps.documents.models import DocumentVersion
        from apps.documents.services import validate_case_evidence
        region=Region.objects.create(code='EVIDENCE',name='Evidence region')
        inst=Institution.objects.create(permanent_id='EVIDENCE',name='Synthetic',region=region,state='Demo')
        cases=[ApplicationCase.objects.create(case_number=f'E-{i}',source_id=f'E-{i}',institution=inst,region=region,academic_cycle='2026-27',application_category='EOA') for i in range(2)]
        doc=DocumentVersion.objects.create(institution=inst,case=cases[0],object_key='synthetic-only',document_type='TEST',original_filename='test.pdf',content_type='application/pdf',size_bytes=1,sha256_digest='0'*64,received_at=timezone.now(),uploaded_by=self.authority,quarantine_status='CLEAN',acceptance_status='ACCEPTED')
        validate_case_evidence(actor=self.authority,case=cases[0],evidence_ids=[str(doc.id)],accepted=True)
        with self.assertRaises(ValidationError):
            validate_case_evidence(actor=self.authority,case=cases[1],evidence_ids=[str(doc.id)],accepted=True)
        doc.quarantine_status='QUARANTINED'
        doc.save()
        with self.assertRaises(ValidationError):
            validate_case_evidence(actor=self.authority,case=cases[0],evidence_ids=[str(doc.id)])
