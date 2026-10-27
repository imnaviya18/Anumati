"""Real PostgreSQL/file restore drill, restricted to the isolated synthetic demo."""
import hashlib
import io
import json
from pathlib import Path
import subprocess
import tarfile
import tempfile
import uuid

ROOT=Path(__file__).resolve().parents[1]
COMPOSE=['docker','compose','-p','anumati-demo','-f',str(ROOT/'docker-compose.demo.yml')]
TARGET='anumati-verification-postgres'

def run(args, data=None):
    return subprocess.run(args,input=data,stdout=subprocess.PIPE,stderr=subprocess.PIPE,check=True).stdout

def main():
    run(['docker','inspect',TARGET])
    # Build an independent audit export before the consistent maintenance snapshot.
    run(COMPOSE+['exec','-T','backend','python','manage.py','shell','-c',
        'from pathlib import Path; from django.conf import settings; from apps.audit.services import export_sealed_audit_bundle; export_sealed_audit_bundle(export_dir=Path(settings.SEALED_AUDIT_EXPORT_ROOT))'])
    sql="SELECT json_build_object('cases',(SELECT count(*) FROM cases_applicationcase),'audit',(SELECT count(*) FROM audit_auditevent),'documents',(SELECT json_agg(json_build_object('key',object_key,'sha',sha256_digest) ORDER BY object_key) FROM documents_documentversion),'chain',(SELECT json_agg(json_build_object('hash',sequence_hash,'previous',previous_hash) ORDER BY occurred_at,id) FROM audit_auditevent))"
    target_db='restore_drill_'+uuid.uuid4().hex[:12]
    try:
        run(COMPOSE+['stop','backend','worker','beat'])
        snapshot=json.loads(run(COMPOSE+['exec','-T','db','psql','-U','anumati_demo','-d','anumati_demo','-At','-c',sql]))
        dump=run(COMPOSE+['exec','-T','db','pg_dump','-U','anumati_demo','-d','anumati_demo','-Fc'])
        files=run(COMPOSE+['run','--rm','--no-deps','-T','backend','tar','-czf','-','-C','/var/lib/anumati','private_storage','sealed_audit_exports'])
    finally:
        run(COMPOSE+['start','backend','worker','beat'])
    run(['docker','exec',TARGET,'createdb','-U','postgres',target_db])
    try:
        run(['docker','exec','-i',TARGET,'pg_restore','--exit-on-error','--single-transaction','--no-owner','--no-privileges','-U','postgres','-d',target_db],dump)
        restored=json.loads(run(['docker','exec',TARGET,'psql','-U','postgres','-d',target_db,'-At','-c',sql]))
        assert snapshot==restored,'Database row counts, document metadata or audit hashes changed on restore'
        with tempfile.TemporaryDirectory(prefix='anumati-restore-') as directory:
            with tarfile.open(fileobj=io.BytesIO(files),mode='r:gz') as archive:
                archive.extractall(directory,filter='data')
            for doc in restored['documents'] or []:
                content=(Path(directory)/'private_storage'/doc['key']).read_bytes()
                assert hashlib.sha256(content).hexdigest()==doc['sha']
            assert list((Path(directory)/'sealed_audit_exports').iterdir())
        previous='GENESIS'
        for event in restored['chain'] or []:
            assert event['previous']==previous,'Restored audit chain linkage is broken'
            previous=event['hash']
        print(json.dumps({'result':'PASS','method':'pg_dump / pg_restore into a separate disposable database plus private-file archive restoration','cases':restored['cases'],'audit_events':restored['audit'],'verified_files':len(restored['documents'] or []),'source':'isolated synthetic demonstration only'},indent=2))
    finally:
        run(['docker','exec',TARGET,'dropdb','-U','postgres',target_db])

if __name__=='__main__':main()
