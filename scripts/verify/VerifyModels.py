"""Real Java RBAC and DPAPI acceptance. No secrets printed or provider requests made."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _bootstrap import ROOT
import json
import os
import uuid

import httpx
import pymysql
from verification_db import business_connection
from listening_common import ServiceSettings
from model_settings import ModelStore, active_connection

runtime = ROOT / '.runtime'
checks = []
def check(name, condition):
    assert condition, name
    checks.append(name)

account = json.loads((runtime / 'stage4-browser-account.json').read_text(encoding='utf-8'))
role = 'model_test_' + uuid.uuid4().hex[:16]
with httpx.Client(base_url='http://127.0.0.1:29183', timeout=15, trust_env=False) as client:
    password = (runtime / 'admin-password').read_text(encoding='utf-8').strip()
    login = client.post('/api/admin/login',json={'username':'admin','password':password})
    login.raise_for_status()
    admin = {'admin-token':login.json()['token']}
    try:
        configuration = client.get('/api/admin/models',headers=admin)
        configuration.raise_for_status()
        check('administrator can read providers', len(configuration.json()['providers']) == 5)
        check('configuration does not expose API Key', all('api_key' not in c for c in configuration.json()['configuration'].values()))
        invalid = client.post('/api/admin/models/test/chat',headers=admin,json={'provider':'custom','base_url':'https://user:private-fixture@models.example','model':'test','api_key':'private-fixture','unexpected':1})
        check('validation errors redact secrets',invalid.status_code==422 and 'private-fixture' not in invalid.text)
        check('anonymous cannot read settings',client.get('/api/admin/models').status_code==401)
        ordinary = client.post('/api/account/login',json={'username':account['username'],'password':account['password']})
        ordinary.raise_for_status()
        check('ordinary token cannot replace admin session',client.get('/api/admin/models',headers={'token':ordinary.json()['token']}).status_code==401)
        db = business_connection(autocommit=True, charset='utf8mb4')
        with db:
            with db.cursor() as cursor:
                cursor.execute('SELECT user_id FROM tingshu_user.access_account WHERE username=%s',(account['username'],))
                uid = cursor.fetchone()[0]
                cursor.execute('INSERT INTO tingshu_user.access_role VALUES(%s,%s)',(role,'本地模型配置验收'))
                try:
                    cursor.execute('INSERT INTO tingshu_user.access_role_permission VALUES(%s,%s)',(role,'admin:access'))
                    cursor.execute('INSERT INTO tingshu_user.access_user_role VALUES(%s,%s)',(uid,role))
                    test_login = client.post('/api/admin/login',json={'username':account['username'],'password':account['password']})
                    test_login.raise_for_status()
                    session={'admin-token':test_login.json()['token']}
                    check('admin access alone cannot configure models',client.get('/api/admin/models',headers=session).status_code==403)
                    cursor.execute('INSERT INTO tingshu_user.access_role_permission VALUES(%s,%s)',(role,'models:manage'))
                    check('permission grant applies to current session',client.get('/api/admin/models',headers=session).status_code==200)
                    cursor.execute('DELETE FROM tingshu_user.access_role_permission WHERE role_code=%s AND permission_code=%s',(role,'models:manage'))
                    check('revocation applies immediately',client.get('/api/admin/models',headers=session).status_code==403)
                    body = {kind:{**c,'api_key':''} for kind,c in configuration.json()['configuration'].items()}
                    for c in body.values(): c.pop('has_api_key')
                    check('revoked session cannot save or test',client.post('/api/admin/models',headers=session,json=body).status_code==403 and client.post('/api/admin/models/test/chat',headers=session,json=body['chat']).status_code==403)
                    client.post('/api/admin/logout',headers=session)
                finally:
                    cursor.execute('DELETE FROM tingshu_user.access_user_role WHERE role_code=%s',(role,))
                    cursor.execute('DELETE FROM tingshu_user.access_role_permission WHERE role_code=%s',(role,))
                    cursor.execute('DELETE FROM tingshu_user.access_role WHERE code=%s',(role,))
        cfg = ServiceSettings()
        store = ModelStore()
        raw = store.path.read_text(encoding='utf-8')
        saved = store.read()
        check('both secrets encrypted and recoverable',all(c['api_key'] and c['api_key'] not in raw for c in saved.values()))
        check('shared config resolves persisted chat and embedding',active_connection(cfg)==saved['chat'] and active_connection(cfg,'embedding')==saved['embedding'])
        check('all six services ready',all(httpx.get(url,timeout=5,trust_env=False).status_code==200 for url in [
            'http://127.0.0.1:19201/v3/api-docs','http://127.0.0.1:19202/v3/api-docs','http://127.0.0.1:19204/v3/api-docs',
            'http://127.0.0.1:29183/health','http://127.0.0.1:29184/health','http://127.0.0.1:29185/health']))
    finally:
        client.post('/api/admin/logout',headers=admin)
report={'passed':len(checks),'checks':checks,'provider_live_status':'existing Aliyun key has Arrearage; no replacement credentials provided'}
(runtime/'model-settings-checks.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(report,ensure_ascii=False,indent=2))
