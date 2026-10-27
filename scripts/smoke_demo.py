"""Exercise only the explicitly seeded local demonstration over real HTTP and Celery."""
import base64
import http.cookiejar
import json
import os
import time
import urllib.request
import uuid

BASE=os.environ.get('DEMO_URL','http://127.0.0.1:15173')
PASSWORD=os.environ.get('DEMO_PASSWORD','DemoOnly-2026-Local!')


class Session:
    def __init__(self,name):
        self.cookies=http.cookiejar.CookieJar()
        self.http=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.cookies))
        self.request('/api/v1/auth/csrf/')
        self.actor=self.request('/api/v1/auth/login/',{'username':'demo_'+name,'password':PASSWORD})

    def request(self,path,payload=None,raw=False):
        headers={'Accept':'application/json'}
        if payload is not None:
            headers['Content-Type']='application/json'
            headers['X-CSRFToken']=next(c.value for c in self.cookies if c.name=='csrftoken')
        request=urllib.request.Request(BASE+path,data=json.dumps(payload).encode() if payload is not None else None,headers=headers)
        try:
            with self.http.open(request,timeout=20) as response:
                content=response.read()
                return content if raw else json.loads(content)
        except urllib.error.HTTPError as exc:
            raise RuntimeError(f'{path}: HTTP {exc.code}: {exc.read().decode()}') from exc


def main():
    institution=Session('institution');admin=Session('admin');officer=Session('officer');authority=Session('authority');auditor=Session('auditor')
    source='DEMO-HTTP-'+uuid.uuid4().hex[:10]
    inst_id=institution.actor['scope']['institution_ids'][0]
    case=institution.request('/api/v1/cases/',{'institution_id':inst_id,'source_id':source,'academic_cycle':'2026-27','application_category':'EOA'})
    assert case['is_demonstration'] is True
    case_id=case['id'];detail=institution.request(f'/api/v1/cases/{case_id}/');stage=detail['stage_instances'][0]
    admin.request('/api/v1/access/case-assignments/',{'case_id':case_id,'stage_id':stage['id'],'user_id':officer.actor['id'],'reason':'Synthetic HTTP workflow test'})
    file_bytes=b'%PDF-1.7\nSynthetic local demonstration evidence only.\n%%EOF'
    doc=institution.request('/api/v1/documents/',{'institution_id':inst_id,'case_id':case_id,'document_type':'DEMO_CERTIFICATE','original_filename':'synthetic-evidence.pdf','declared_mime_type':'application/pdf','content_base64':base64.b64encode(file_bytes).decode()})
    assert doc['lifecycle_state']=='QUARANTINED'
    deadline=time.monotonic()+45
    while time.monotonic()<deadline:
        docs=institution.request('/api/v1/documents/')
        current=next(d for d in docs if d['id']==doc['id'])
        if current['lifecycle_state']=='CLEAN':break
        time.sleep(1)
    else:raise AssertionError('Celery did not complete the document scan within 45 seconds')
    officer.request(f"/api/v1/documents/{doc['id']}/review/",{'accept':True,'notes':'Synthetic evidence reviewed for test'})
    grant=institution.request(f"/api/v1/documents/{doc['id']}/download-grant/",{})
    assert institution.request(f"/api/v1/documents/{doc['id']}/download-grant/?token={grant['grant_token']}",raw=True)==file_bytes
    transition=officer.request(f"/api/v1/cases/{case_id}/stages/{stage['id']}/transition/",{'action':'COMPLETE_STAGE','expected_version':detail['version'],'idempotency_key':source+'-stage','reason':'Synthetic scrutiny complete','findings':[{'document_version_id':doc['id'],'finding':'verified synthetic document'}]})
    payload={'outcome':'GRANT_EOA','expected_version':transition['version'],'idempotency_key':source+'-decision','reasons':'Demonstration decision only','delegated_power_ref':'GRANT_EOA','reviewed_evidence_version_ids':[doc['id']],'obligations_specs':[{'obligation_code':'DEMO-FOLLOWUP','condition_text':'Synthetic continuing evidence requirement','due_days':5}]}
    decision=authority.request(f'/api/v1/decisions/cases/{case_id}/decide/',payload)
    replay=authority.request(f'/api/v1/decisions/cases/{case_id}/decide/',payload)
    assert decision==replay
    obligations=institution.request('/api/v1/compliance/obligations/')
    obligation=next(o for o in obligations if o['case_number']==case['case_number'])
    sub=institution.request(f"/api/v1/compliance/obligations/{obligation['id']}/submit/",{'document_version_id':doc['id']})
    verified=officer.request(f"/api/v1/compliance/obligations/{obligation['id']}/verify/",{'submission_id':sub['submission_id'],'is_fulfilled':True,'finding_notes':'Synthetic obligation fulfilled'})
    assert verified['state']=='FULFILLED'
    csv=auditor.request('/api/v1/reporting/reports/application_pendency/?export=csv',raw=True)
    assert case['case_number'].encode() in csv
    audit=auditor.request('/api/v1/audit/events/?case_id='+case_id)
    assert audit
    summary=institution.request(f'/api/v1/communications/cases/{case_id}/summary/',{})
    assert case['case_number'] in summary['rendered_body']
    assert '{status}' not in summary['rendered_body']
    policies=authority.request('/api/v1/policy/')
    research=next(p for p in policies if p['policy_code']=='APH-2024-2027-RESEARCH-DRAFT')
    assert research['state']=='DRAFT' and research['is_demonstration'] is False
    print(json.dumps({'result':'PASS','case_number':case['case_number'],'checks':['session login + CSRF','synthetic intake','reviewer assignment','real Celery quarantine scan','human evidence review','authorised download','stage transition','decision commit and identical replay','continuing obligation submission and verification','scoped CSV export','audit history','rendered case summary','authoritative APH draft remains blocked']},indent=2))


if __name__=='__main__':main()
