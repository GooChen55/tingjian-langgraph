import sys,json,time,uuid,re
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from _bootstrap import ROOT
root=ROOT
import httpx
from search_sync import connection
from resource_scope import SCOPE,OWNER
report={'owner':OWNER,'checks':{}}
with httpx.Client(base_url='http://127.0.0.1:29183',timeout=25,trust_env=False) as client:
    html=client.get('/listen/').raise_for_status().text
    assets=re.findall(r'<script[^>]+src="([^"]+)"',html)
    assert assets
    for asset in assets:
        client.get(asset if asset.startswith('/') else '/listen/'+asset).raise_for_status()
    report['checks']['h5_and_javascript_assets']=True
    results=client.get('/api/content/albums',params={'q':'三体'}).raise_for_status().json()
    assert results['total']>0 and results['records']
    report['checks']['elasticsearch_search_results']=len(results['records'])
    client.get('/api/content/suggest',params={'q':'三'}).raise_for_status()
    report['checks']['search_suggestions']=True
    admin=client.post('/api/admin/login',json={'username':'admin','password':(root/'.runtime/admin-password').read_text(encoding='utf-8').strip()}).raise_for_status().json()
    headers={'admin-token':admin['token']}
    try:
        with connection('tingshu_album') as db:
            with db.cursor() as cur:
                cur.execute('SELECT album_title,is_open,status FROM album_info WHERE id=900001 AND is_deleted=0')
                title,visibility,status=cur.fetchone()
                assert status=='0301' and visibility=='1'
        identity=str(uuid.uuid4())
        payload={'albumTitle':title,'published':True,'requestId':identity}
        client.patch('/api/admin/content/albums/900001',headers=headers,json=payload).raise_for_status()
        replay=client.patch('/api/admin/content/albums/900001',headers=headers,json=payload).raise_for_status().json()
        assert replay['replayed'] is True
        report['checks']['same_request_is_idempotent']=True
        conflict=client.patch('/api/admin/content/albums/900001',headers=headers,json={**payload,'albumTitle':title+'冲突'})
        assert conflict.status_code==409
        report['checks']['conflicting_request_rejected']=True
        for _ in range(40):
            with connection() as db:
                with db.cursor() as cur:
                    cur.execute('SELECT status,attempts FROM search_outbox WHERE id=%s',(identity,))
                    state,attempts=cur.fetchone()
            if state in ('COMPLETED','DEAD'):break
            time.sleep(.5)
        assert state=='COMPLETED',(state,attempts)
        doc=client.get('http://192.168.6.100:9200/'+SCOPE.es_index('albums')+'/_doc/900001').raise_for_status().json()
        assert doc['_source']['albumTitle']==title
        report['checks']['outbox_rabbitmq_es_completed']={'event':identity,'attempts':attempts}
        client.get('/api/admin/content/index-jobs',headers=headers).raise_for_status()
        report['checks']['admin_sync_status']=True
    finally:
        client.post('/api/admin/logout',headers=headers).raise_for_status()
worker=json.loads((root/'.runtime/vm/search-worker.json').read_text(encoding='utf-8'))
assert worker['owner']==OWNER and worker['ready'] and time.time()-worker['updated']<10
report['checks']['message_worker_ready']=True
report['passed']=True
(root/'.runtime/project-launch-smoke.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(report,ensure_ascii=False,indent=2))