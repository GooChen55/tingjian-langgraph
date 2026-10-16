"""Read-only provider and business probes using saved configuration; never print keys."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _bootstrap import ROOT
import json

import httpx

runtime = ROOT / '.runtime'
report = {}
with httpx.Client(base_url='http://127.0.0.1:29183', timeout=120, trust_env=False) as client:
    admin = client.post('/api/admin/login', json={'username': 'admin',
        'password': (runtime / 'admin-password').read_text(encoding='utf-8').strip()})
    admin.raise_for_status()
    headers = {'admin-token': admin.json()['token']}
    token = None
    try:
        configuration = client.get('/api/admin/models', headers=headers).raise_for_status().json()['configuration']
        for kind, value in configuration.items():
            candidate = {k: v for k, v in value.items() if k != 'has_api_key'}
            result = client.post('/api/admin/models/test/' + kind, headers=headers,
                                 json={**candidate, 'api_key': ''})
            report[kind] = {'status': result.status_code, 'result': result.json()}
        account = json.loads((runtime / 'stage4-browser-account.json').read_text(encoding='utf-8'))
        login = client.post('/api/account/login', json={'username': account['username'], 'password': account['password']})
        login.raise_for_status()
        token = login.json()['token']
        for name, question in [('assistant', '请查询我的收听进度，告诉我准确听到哪里。'),
                               ('knowledge', '《三体》的用户评论里有哪些门槛提醒？')]:
            result = client.post('/api/assistant/chat', headers={'token': token}, json={'text': question})
            body = result.json()
            report[name] = {'status': result.status_code,
                'tools': [s['tool'] for s in body.get('trace', [])],
                'source_count': len(body.get('sources', []))}
            if result.status_code != 200:
                report[name]['detail'] = body.get('detail')
        result = client.post('/api/admin/ops/query', headers=headers,
                             json={'text': '平台共有多少个专辑和声音？'})
        body = result.json()
        report['operations'] = {'status': result.status_code, 'mode': body.get('mode'),
                                'row_count': body.get('row_count')}
        if result.status_code != 200:
            report['operations']['detail'] = body.get('detail')
    finally:
        if token:
            client.post('/api/account/logout', headers={'token': token})
        client.post('/api/admin/logout', headers=headers)
report['passed'] = (all(report[k]['status'] == 200 for k in
    ['chat', 'embedding', 'assistant', 'knowledge', 'operations'])
    and 'get_progress' in report['assistant']['tools']
    and report['knowledge']['source_count'] > 0
    and report['operations']['mode'] == 'readonly-nl2sql')
(runtime / 'model-compatibility-live.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps(report, ensure_ascii=False, indent=2))
raise SystemExit(0 if report['passed'] else 1)
