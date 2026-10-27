"""Actual HTTP acceptance of the four synthetic workspaces; no external I/O."""
import base64
import json
import time
import uuid
from datetime import datetime, timedelta, timezone
from smoke_demo import Session


def main():
    inst, officer, admin, evc, policy, authority, auditor = [Session(x) for x in ['institution','officer','admin','evc','policy','authority','auditor']]
    run=uuid.uuid4().hex[:12]
    directory=inst.request('/api/v1/organisation/')
    institution=next(i for i in directory['institutions'] if i['is_new_institution'])
    case=inst.request('/api/v1/cases/',{'institution_id':institution['id'],'source_id':'WORKSPACES-'+run,'academic_cycle':'2026-27','application_category':'NEW_INSTITUTION'})
    cid=case['id']
    detail=officer.request(f'/api/v1/cases/{cid}/')
    stage=detail['stage_instances'][0]
    admin.request('/api/v1/access/case-assignments/',{'case_id':cid,'stage_id':stage['id'],'user_id':officer.actor['id'],'reason':'Synthetic workflow acceptance'})
    doc=inst.request('/api/v1/documents/',{'institution_id':institution['id'],'case_id':cid,'document_type':'DEMO_VALIDITY','original_filename':'demonstration.pdf','declared_mime_type':'application/pdf','content_base64':base64.b64encode(b'%PDF-1.7\nSynthetic demonstration only\n%%EOF').decode()})
    for _ in range(60):
        rows=inst.request('/api/v1/documents/')
        if next(d for d in rows if d['id']==doc['id'])['lifecycle_state']=='CLEAN':break
        time.sleep(1)
    else: raise AssertionError('Document scan timed out')
    officer.request(f"/api/v1/documents/{doc['id']}/review/",{'accept':True,'notes':'Synthetic reviewed evidence'})
    transition=f"/api/v1/cases/{cid}/stages/{stage['id']}/transition/"
    officer.request(transition,{'action':'RETURN_FOR_DEFICIENCY','expected_version':detail['version'],'idempotency_key':run+'-return','reason':'Clarify demonstration reference','deficiencies':[{'document_version_id':doc['id'],'finding':'Please clarify synthetic reference'}]})
    detail=inst.request(f'/api/v1/cases/{cid}/')
    cycle=detail['deficiency_cycles'][0]
    inst.request(f"/api/v1/cases/{cid}/deficiencies/{cycle['id']}/respond/",{'expected_version':detail['version'],'idempotency_key':run+'-respond','response_text':'Synthetic clarification supplied','evidence_version_ids':[doc['id']]})
    detail=officer.request(f'/api/v1/cases/{cid}/')
    assert detail['deficiency_history'][0]['institution_response']=='Synthetic clarification supplied'
    stage=next(s for s in detail['stage_instances'] if s['status'] in ['PENDING','IN_PROGRESS'])
    admin.request('/api/v1/access/case-assignments/',{'case_id':cid,'stage_id':stage['id'],'user_id':officer.actor['id'],'reason':'Re-review synthetic clarification'})
    officer.request(f"/api/v1/cases/{cid}/stages/{stage['id']}/transition/",{'action':'COMPLETE_STAGE','expected_version':detail['version'],'idempotency_key':run+'-complete','reason':'Synthetic scrutiny completed','findings':[{'document_version_id':doc['id'],'finding':'Clarification verified'}]})
    detail=officer.request(f'/api/v1/cases/{cid}/')
    stage=next(s for s in detail['stage_instances'] if s['stage_type']=='EVC')
    coord=officer.request('/api/v1/evc/',{'case_id':cid,'stage_instance_id':stage['id'],'reason':'Synthetic prerequisites complete'})
    committee=next(c for c in admin.request('/api/v1/organisation/')['committees'] if c['code']=='DEMO-EVC')
    start=datetime.now(timezone.utc)+timedelta(days=2,seconds=int(run[:6],16))
    officer.request(f"/api/v1/evc/{coord['id']}/reserve/",{'committee_id':committee['id'],'slot_start':start.isoformat(),'slot_end':(start+timedelta(hours=1)).isoformat(),'reason':'Synthetic committee slot'})
    officer.request(f"/api/v1/evc/{coord['id']}/confirm/",{'confirmed':True,'reason':'Synthetic human confirmation'})
    report_payload={'expected_version':detail['version'],'idempotency_key':run+'-evc','reason':'Synthetic evaluation report','observations':{'finding':'Synthetic inspection complete'},'video_recording_ref':'DEMO-VIDEO-'+run,'evidence_version_ids':[doc['id']]}
    report=evc.request(f"/api/v1/evc/{coord['id']}/report/",report_payload)
    assert evc.request(f"/api/v1/evc/{coord['id']}/report/",report_payload)==report
    assert report['evc_status']=='REPORT_SUBMITTED'
    registered=officer.request('/api/v1/compliance/validity/',{'document_version_id':doc['id'],'valid_from':'2026-01-01','valid_until':'2027-01-01'})
    # A new immutable upload is required for renewal, even when the bytes are the same.
    renewed=inst.request('/api/v1/documents/',{'institution_id':institution['id'],'case_id':cid,'document_type':'DEMO_VALIDITY','original_filename':'renewal.pdf','declared_mime_type':'application/pdf','content_base64':base64.b64encode(b'%PDF-1.7\nSynthetic renewal\n%%EOF').decode()})
    for _ in range(60):
        if next(d for d in inst.request('/api/v1/documents/') if d['id']==renewed['id'])['lifecycle_state']=='CLEAN':break
        time.sleep(1)
    else: raise AssertionError('Renewal scan timed out')
    inst.request(f"/api/v1/compliance/validity/{registered['id']}/submit/",{'document_version_id':renewed['id']})
    pending=next(v for v in inst.request('/api/v1/compliance/validity/') if v['id']==registered['id'])
    assert pending['state']=='PENDING_RENEWAL_REVIEW' and pending['accepted_version_id']==doc['id']
    officer.request(f"/api/v1/compliance/validity/{registered['id']}/review/",{'accept':True,'valid_from':'2027-01-01','valid_until':'2028-01-01','notes':'Synthetic renewal verified'})
    detail=authority.request(f'/api/v1/cases/{cid}/')
    authority.request(f'/api/v1/decisions/cases/{cid}/decide/',{'outcome':'GRANT_LOA','expected_version':detail['version'],'idempotency_key':run+'-decision','reasons':'Synthetic decision after scrutiny and EVC','delegated_power_ref':'GRANT_LOA','reviewed_evidence_version_ids':[doc['id']]})
    draft=policy.request('/api/v1/policy/',{'policy_code':'DEMO-REVIEW-'+run,'version_number':1,'academic_cycle':'DEMO-'+run,'is_demonstration':True,'route_rules':[{'route_code':'LOCAL','conditions':{'application_category':'EOA'},'stages':['SCRUTINY']}],'regression_cases':[{'name':'Local EOA','application_category':'EOA','expected_route_code':'LOCAL'}]})
    for action in ['validate','dry-run']:policy.request(f"/api/v1/policy/{draft['id']}/{action}/",{})
    approved=authority.request(f"/api/v1/policy/{draft['id']}/approve/",{'reason':'Synthetic policy regression reviewed'})
    assert approved['state']=='APPROVED'
    active=authority.request(f"/api/v1/policy/{draft['id']}/activate/",{})
    assert active['state']=='ACTIVE'
    event=policy.request('/api/v1/policy/sync-exceptions/',{'event_id':run,'source_id':'DEMO-'+run,'payload':{'display_name':'Synthetic reference'},'reason':'Source reconciliation test'})
    resolved=policy.request(f"/api/v1/policy/sync-exceptions/{event['id']}/resolve/",{'expected_version':event['version'],'action':'ACCEPT_SOURCE','reason':'Compared mock reference fields'})
    assert resolved['state']=='RESOLVED'
    dashboard=auditor.request('/api/v1/reporting/dashboard/')
    assert 'status_by_bureau' in dashboard and 'workload_by_officer' in dashboard and 'ageing' in dashboard
    assert auditor.request(f'/api/v1/cases/{cid}/')['deficiency_history']
    print(json.dumps({'result':'PASS','case_number':case['case_number'],'checks':['institution intake and deficiency response history','Celery evidence processing','assigned scrutiny findings','EVC readiness/reservation/confirmation/committee report','accepted validity registration','pending renewal preserves accepted version','human renewal verification','authorised final decision','separate policy draft/validation/dry-run/approval/activation','owned mock sync reconciliation','bureau/workload/ageing and case history']},indent=2))

if __name__=='__main__':main()
