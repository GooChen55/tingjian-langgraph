"""Real private-space isolation, MQ import, consented RAG and listening checks."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from _bootstrap import ROOT
import argparse
import json
import secrets
import time
import uuid

import httpx

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--verify-restart',action='store_true')
args=parser.parse_args()
runtime=ROOT/'.runtime';checks=[]


def check(label,value):
    assert value,label
    checks.append(label);print('PASS '+label,flush=True)


def wait_item(client,headers,space,identity,status='ACTIVE',seconds=120):
    end=time.monotonic()+seconds
    while time.monotonic()<end:
        data=client.get(f'/api/personal/spaces/{space}/items',headers=headers).raise_for_status().json()
        row=next((r for r in data['records'] if r['id']==identity),None)
        if row and row['status']==status:return row
        if row and row['status']=='FAILED' and status!='FAILED':raise AssertionError('Personal import failed: '+str(row['error_code']))
        time.sleep(.5)
    raise AssertionError('Personal item timed out')


with httpx.Client(base_url='http://127.0.0.1:29183',timeout=120,trust_env=False) as client:
    tokens=[]
    try:
        if args.verify_restart:
            fixture=json.loads((runtime/'personal-fixture-private.json').read_text(encoding='utf-8'))
            token=client.post('/api/account/login',json=fixture['account']).raise_for_status().json()['token'];tokens.append(token)
            headers={'token':token};space=fixture['space']
            result=client.post('/api/assistant/chat',headers=headers,json={'text':fixture['marker'],'knowledge_scope':'personal','knowledge_space_id':space,'session_id':fixture['session_id']}).raise_for_status().json()
            check('private session and source persist after actual restart',bool(result['sources']) and fixture['marker'] in result['text'])
            report=json.loads((runtime/'personal-acceptance.json').read_text(encoding='utf-8'));report['checks']+=checks;report['restart_verified']=True
            (runtime/'personal-acceptance.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        else:
            accounts=[{'username':'personal_'+uuid.uuid4().hex[:12],'password':secrets.token_urlsafe(24)} for _ in range(2)]
            for account in accounts:
                client.post('/api/account/register',json=account).raise_for_status()
                tokens.append(client.post('/api/account/login',json=account).raise_for_status().json()['token'])
            a,b=[{'token':token} for token in tokens]
            check('anonymous personal access denied',client.get('/api/personal/spaces').status_code==401)
            check('forged owner field rejected',client.post('/api/personal/spaces',headers=a,json={'name':'我的空间','owner_id':900001}).status_code==422)
            space=client.post('/api/personal/spaces',headers=a,json={'name':'【验收】私人听书空间'}).raise_for_status().json()['id']
            other=client.post('/api/personal/spaces',headers=b,json={'name':'【验收】另一个用户'}).raise_for_status().json()['id']
            check('space names are idempotent within account',client.post('/api/personal/spaces',headers=a,json={'name':'【验收】私人听书空间'}).json()['id']==space)
            check('space list contains only current owner',all(s['id']!=space for s in client.get('/api/personal/spaces',headers=b).json()['records']))
            base='/api/personal/spaces/'+space
            marker='紫杉湖泊'+secrets.token_hex(4)
            body={'kind':'NOTE','title':'【验收】紫杉湖泊的笔记','content':marker+'：这条笔记只属于账号甲，核心观点是先记录事实，再进行复习。','album_id':900001,'track_id':900001,'anchor_second':4.0}
            note=client.post(base+'/items',headers=a,json=body).raise_for_status().json()['id']
            row=wait_item(client,a,space,note)
            second=client.post('/api/personal/spaces',headers=a,json={'name':'【验收】同账号另一个空间'}).raise_for_status().json()['id']
            second_base='/api/personal/spaces/'+second
            check('same owner cannot update an item through another space',client.patch(second_base+'/items/'+str(note),headers=a,json=body).status_code==404)
            check('same owner spaces keep separate retrieval scopes',not client.post(second_base+'/query',headers=a,json={'question':marker}).raise_for_status().json()['sources'])
            check('note asynchronously published without AI consent',row['active_revision'] is not None and not client.get(base+'/items',headers=a).json()['space']['ai_enabled'])
            for method,suffix,payload in [('GET','/items',None),('POST','/query',{'question':marker}),('PATCH','/items/'+str(note),body),('DELETE','/items/'+str(note),None),('POST','/items/'+str(note)+'/retry',{})]:
                check('foreign owner denied '+method+' '+suffix,client.request(method,base+suffix,headers=b,json=payload).status_code==404)
            found=client.post(base+'/query',headers=a,json={'question':marker}).raise_for_status().json()
            check('private keyword result has own source and verbatim quote',found['mode']=='private-keyword' and any(marker in s['quote'] for s in found['sources']) and all(s['space_id']==space for s in found['sources']))
            empty=client.post('/api/personal/spaces/'+other+'/query',headers=b,json={'question':marker}).raise_for_status().json()
            check('another user cannot recall the marker',not empty['sources'] and marker not in empty['text'])
            data=('# 私人资料\n\n'+marker+' 的第二份资料说明：复习时需要保留原文和声音时间点。').encode()
            doc=client.post(base+'/documents',headers=a,data={'title':'【验收】私人文字资料'},files={'file':('personal.md',data,'text/markdown')}).raise_for_status().json()['id']
            wait_item(client,a,space,doc)
            check('private original downloaded through authenticated owner',client.get(base+f'/documents/{doc}/download',headers=a).content==data)
            check('foreign download denied',client.get(base+f'/documents/{doc}/download',headers=b).status_code==404)
            check('same owner cannot download through a different space',client.get(second_base+f'/documents/{doc}/download',headers=a).status_code==404)
            old_revision=wait_item(client,a,space,doc)['active_revision']
            client.post(base+'/documents',headers=a,data={'title':'【验收】失败更新仍保留旧版','identity':str(doc)},files={'file':('bad.pdf',b'%PDF-invalid-document','application/pdf')}).raise_for_status()
            failed=wait_item(client,a,space,doc,'FAILED')
            check('failed document update preserves the previously active version',failed['active_revision']==old_revision)
            check('public upload API remains administrator only',client.post('/api/admin/knowledge/documents',headers=a,data={'title':'不允许提升权限'},files={'file':('x.md',data)}).status_code==401)
            bookmark=client.post(base+'/items',headers=a,json={'kind':'BOOKMARK','title':'【验收】四秒书签','album_id':900001,'track_id':900001,'anchor_second':4.0}).raise_for_status().json()['id']
            wait_item(client,a,space,bookmark)
            check('bookmark preserves validated time point',next(r for r in client.get(base+'/items',headers=a).json()['records'] if r['id']==bookmark)['anchor_second']=='4.00' or float(next(r for r in client.get(base+'/items',headers=a).json()['records'] if r['id']==bookmark)['anchor_second'])==4)
            before=client.get('/api/playback/progress/900001',headers=a).raise_for_status().json()['breakSecond']
            segment={'session_id':str(uuid.uuid4()),'sequence':0,'album_id':900001,'track_id':900001,'start':0.,'end':8.,'elapsed':8.}
            client.post('/api/personal/listening/segments',headers=a,json=segment).raise_for_status()
            check('listening segment replay is idempotent',client.post('/api/personal/listening/segments',headers=a,json=segment).raise_for_status().json()['replayed'])
            check('reused segment number with conflicting content rejected',client.post('/api/personal/listening/segments',headers=a,json={**segment,'end':7.}).status_code==409)
            check('seek jump cannot become listened coverage',client.post('/api/personal/listening/segments',headers=a,json={**segment,'sequence':1,'end':60.,'elapsed':1.}).status_code==422)
            client.post('/api/personal/listening/segments',headers=a,json={**segment,'sequence':1,'start':6.,'end':12.,'elapsed':6.}).raise_for_status()
            check('late interval does not change resume position',client.get('/api/playback/progress/900001',headers=a).json()['breakSecond']==before)
            review=client.get(base+'/review',headers=a).raise_for_status().json();track=next(t for t in review['records'] if t['track_id']==900001)
            check('overlapping coverage merged without counting skipped positions',track['intervals']==[[0.,12.]] and track['covered_seconds']==12)
            check('listening review grounded in own notes',any(n['id']==note for n in track['notes']) and marker in json.dumps(review,ensure_ascii=False))
            recalled=client.post(base+'/query',headers=a,json={'question':'查看我的听书回顾'}).raise_for_status().json()
            check('personal assistant can answer listening review without inventing book text',recalled['mode']=='private-listening' and '12.0' in recalled['text'] and marker in recalled['text'])
            other_review=client.get('/api/personal/spaces/'+other+'/review',headers=b).raise_for_status().json()
            check('listening history isolated by owner',not other_review['records'] and marker not in json.dumps(other_review))
            new_marker='赤松山谷'+secrets.token_hex(4)
            client.patch(base+'/items/'+str(note),headers=a,json={**body,'content':new_marker+'：更新后的笔记仍需保留来源。'}).raise_for_status()
            wait_item(client,a,space,note)
            check('note update activates a new version',new_marker in client.post(base+'/query',headers=a,json={'question':new_marker}).raise_for_status().json()['text'])
            client.delete(base+'/items/'+str(doc),headers=a).raise_for_status()
            check('deleted original cannot be downloaded',client.get(base+f'/documents/{doc}/download',headers=a).status_code==404)
            private=client.post('/api/assistant/chat',headers=a,json={'text':new_marker,'knowledge_scope':'personal','knowledge_space_id':space}).raise_for_status().json()
            check('embedded assistant supports private scope',private['scope']=='personal' and new_marker in private['text'])
            check('private session cannot be reused for platform model',client.post('/api/assistant/chat',headers=a,json={'text':'你好','session_id':private['session_id']}).status_code==409)
            check('private chat cannot enable web search',client.post('/api/assistant/chat',headers=a,json={'text':new_marker,'knowledge_scope':'personal','knowledge_space_id':space,'allow_web':True}).status_code==422)
            with client.stream('POST','/api/assistant/chat/stream',headers=a,json={'text':new_marker,'knowledge_scope':'personal','knowledge_space_id':space}) as response:
                stream=''.join(response.iter_text())
            check('private SSE contains progress and grounded result','event: progress' in stream and 'event: result' in stream and new_marker in stream)
            client.patch(base,headers=a,json={'ai_enabled':True}).raise_for_status()
            wait_item(client,a,space,note)
            ai=client.post(base+'/query',headers=a,json={'question':new_marker+'的笔记说了什么？'}).raise_for_status().json()
            check('consented real Milvus and model query returns scoped evidence',ai['mode']=='private-rag' and 'private_milvus' in ai['graph_trace'] and any(new_marker in s['quote'] for s in ai['sources']))
            client.patch(base,headers=a,json={'ai_enabled':False}).raise_for_status()
            fixture={'account':accounts[0],'space':space,'note':note,'marker':new_marker,'session_id':private['session_id']}
            (runtime/'personal-fixture-private.json').write_text(json.dumps(fixture,ensure_ascii=False),encoding='utf-8')
            report={'passed':True,'checks':checks,'restart_verified':False,'external_cloud_adapter':'not configured; current MinIO/Milvus only','real_funds':False}
            (runtime/'personal-acceptance.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    finally:
        for token in tokens:client.post('/api/account/logout',headers={'token':token})
print('Personal checks passed:',len(checks),flush=True)
