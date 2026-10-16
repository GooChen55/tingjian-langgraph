"""Real VM acceptance. Prepare, restart this project, then accept durable flows.

Creates clearly marked test accounts/orders/documents only in owned resources.
Never submits a real payment or prints credentials.
"""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from _bootstrap import ROOT
import argparse
import io
import json
import secrets
import time
import uuid
import httpx
import pymysql
from pypdf import PdfWriter
from search_sync import connection
from resource_scope import OWNER

FILE=ROOT/'.runtime/fusion-fixture-private.json'
REPORT=ROOT/'.runtime/fusion-acceptance.json'
BASE='http://127.0.0.1:29183'


def wait_document(client,headers,identity,status,timeout=120):
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        rows=client.get('/api/admin/knowledge/documents',headers=headers).raise_for_status().json()['records']
        row=next(d for d in rows if d['id']==identity)
        if row['status']==status:return row
        if row['status']=='FAILED' and status!='FAILED':raise AssertionError(('Import failed',row['error_code']))
        time.sleep(.5)
    raise AssertionError('Document task timed out: '+str(identity))


def prepare(client,admin):
    account={'username':'fusion_'+uuid.uuid4().hex[:12],'password':secrets.token_urlsafe(24)}
    client.post('/api/account/register',json=account).raise_for_status()
    token=client.post('/api/account/login',json=account).raise_for_status().json()['token'];headers={'token':token}
    owner=client.get('/api/me',headers=headers).raise_for_status().json()['id']
    with connection('tingshu_order',autocommit=True) as db:
        with db.cursor() as cur:
            cur.execute('SELECT COALESCE(MAX(id),900002)+1 FROM order_info');order=cur.fetchone()[0]
            cur.execute("INSERT INTO order_info(id,user_id,order_title,order_no,order_status,order_amount,original_amount) VALUES(%s,%s,'【融合验收】售后流程',%s,'0902',9.90,9.90)",(order,owner,'FUSION-'+uuid.uuid4().hex))
    with connection('tingshu_user',autocommit=True) as db:
        with db.cursor() as cur:cur.execute('UPDATE user_info SET wx_open_id=%s WHERE id=%s',('local-demo-fusion-'+str(owner),owner))
    task=client.post('/api/assistant/tasks',headers=headers,json={'action':'start'}).raise_for_status().json()
    sid=task['session_id'];identity=task['task']['id']
    def reply(text):return client.post('/api/assistant/tasks',headers=headers,json={'action':'reply','session_id':sid,'task_id':identity,'text':text}).raise_for_status().json()
    reply(str(order));pending=reply('融合验收：误购，请人工审核申请。')
    assert pending['task']['field']=='confirmation'
    title='融合验收指南'+uuid.uuid4().hex[:6]
    text=f'# {title}\n\n## 验收标记\n本资料的识别短语是赤橙湖泊。该短语只用于验证文档更新，不能用于真实业务判断。'
    upload=client.post('/api/admin/knowledge/documents',headers=admin,data={'title':title},files={'file':('fusion.md',text.encode(),'text/markdown')}).raise_for_status().json()
    row=wait_document(client,admin,upload['id'],'ACTIVE')
    fixture={'account':account,'owner':owner,'task':identity,'session':sid,'draft':pending['task']['draft']['id'],'document':upload['id'],'revision':row['active_revision'],'title':title}
    FILE.write_text(json.dumps(fixture,ensure_ascii=False,indent=2),encoding='utf-8')
    client.post('/api/account/logout',headers=headers).raise_for_status()
    print('Prepared: task waiting for explicit confirmation; document active. Restart this project before --phase accept.',flush=True)


def accept(client,admin):
    fixture=json.loads(FILE.read_text(encoding='utf-8'));checks=[]
    def checked(label,condition):
        assert condition,label
        checks.append(label);print('PASS:',label,flush=True)
    token=client.post('/api/account/login',json=fixture['account']).raise_for_status().json()['token'];headers={'token':token}
    try:
        pending=client.get('/api/assistant/tasks/current/'+fixture['session'],headers=headers).raise_for_status().json()['task']
        checked('重启后恢复待确认任务',pending['task']['id']==fixture['task'])
        payload={'action':'reply','task_id':fixture['task'],'session_id':fixture['session'],'text':'确认'}
        checked('自然语言确认不能代替确认按钮',client.post('/api/assistant/tasks',headers=headers,json=payload).status_code==422)
        payload.update(action='confirm',confirmed=True,draft_id=fixture['draft'])
        done=client.post('/api/assistant/tasks',headers=headers,json=payload).raise_for_status().json()
        repeated=client.post('/api/assistant/tasks',headers=headers,json=payload).raise_for_status().json()
        checked('确认提交及重复请求幂等',done==repeated and done['result']['status']=='SUBMITTED')
        checked('普通听友不能管理知识库',client.get('/api/admin/knowledge/documents',headers={'admin-token':token}).status_code in (401,403))
        other={'username':'fusion_other_'+uuid.uuid4().hex[:10],'password':secrets.token_urlsafe(24)}
        client.post('/api/account/register',json=other).raise_for_status()
        other_token=client.post('/api/account/login',json=other).raise_for_status().json()['token']
        try:
            checked('其他用户不能恢复任务',client.post('/api/assistant/tasks',headers={'token':other_token},json=payload).status_code==404)
        finally:client.post('/api/account/logout',headers={'token':other_token})
        def ask(marker):
            response=client.post('/api/assistant/chat',headers=headers,json={'text':'《'+fixture['title']+'》中用于验证更新的识别短语是什么？'}).raise_for_status().json()
            return any(marker in source.get('quote','') and source.get('source','').startswith('uploaded:'+str(fixture['document'])+':') for source in response['sources'])
        checked('上传资料通过真实检索与引用核验',ask('赤橙湖泊'))
        text='# '+fixture['title']+'\n\n## 验收标记\n本资料更新后的识别短语是蓝银海湾。该短语只用于验证文档更新，不能用于真实业务判断。'
        response=client.post('/api/admin/knowledge/documents',headers=admin,data={'title':fixture['title'],'document_id':str(fixture['document'])},files={'file':('fusion.md',text.encode(),'text/markdown')}).raise_for_status().json()
        row=wait_document(client,admin,fixture['document'],'ACTIVE')
        checked('文件更新产生新版本',row['active_revision']!=fixture['revision'])
        checked('问答切换到更新后的资料',ask('蓝银海湾'))
        client.delete('/api/admin/knowledge/documents/'+str(fixture['document']),headers=admin).raise_for_status()
        wait_document(client,admin,fixture['document'],'DELETED')
        response=client.post('/api/assistant/chat',headers=headers,json={'text':'《'+fixture['title']+'》的识别短语是什么？'}).raise_for_status().json()
        checked('删除的资料不再作为引用',not any(s.get('source','').startswith('uploaded:'+str(fixture['document'])+':') for s in response['sources']))
        with client.stream('POST','/api/assistant/chat/stream',headers=headers,json={'text':'查询我的收听进度'}) as response:
            response.raise_for_status();stream=''.join(response.iter_text())
        checked('助手流式返回实际节点与最终结果','event: progress' in stream and 'event: result' in stream)
        ops=client.post('/api/admin/ops/query',headers=admin,json={'text':'平台共有多少个专辑和声音？'}).raise_for_status().json()
        nodes={r['node'] for r in ops['trace']}
        checked('问数关键词与三路召回真实运行',{'extract_keywords','recall_columns','recall_metrics','recall_values','filter_tables_and_metrics','execute'}<=nodes)
        writer=PdfWriter();writer.add_blank_page(width=100,height=100);raw=io.BytesIO();writer.write(raw)
        bad=client.post('/api/admin/knowledge/documents',headers=admin,data={'title':'【融合验收】扫描PDF失败提示'},files={'file':('scan.pdf',raw.getvalue(),'application/pdf')}).raise_for_status().json()
        row=wait_document(client,admin,bad['id'],'FAILED')
        checked('扫描PDF明确提示需要OCR','ScannedPdfNeedsOcr' in row['error_code'])
        for _ in range(90):
            with connection() as db:
                with db.cursor() as cur:
                    cur.execute('SELECT status,attempts FROM search_outbox WHERE id=%s',(bad['requestId'],));state,attempts=cur.fetchone()
            if state=='DEAD':break
            time.sleep(.5)
        checked('导入失败有限重试后终止',state=='DEAD' and attempts==3)
        from listening_jobs.worker import broker
        broker_client,ch=broker()
        try:checked('失败消息进入项目死信队列',ch.queue_declare(queue='aillisten.dev.knowledge.dead',passive=True).method.message_count>=1)
        finally:broker_client.close()
        report={'owner':OWNER,'passed':True,'checks':checks,'external_services':'WeChat payment, Tencent VOD, avatar deferred by user'}
        REPORT.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        print('Fusion acceptance passed:',len(checks),flush=True)
    finally:client.post('/api/account/logout',headers=headers)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--phase',choices=['prepare','accept'],required=True);args=parser.parse_args()
    with httpx.Client(base_url=BASE,timeout=120,trust_env=False) as client:
        login=client.post('/api/admin/login',json={'username':'admin','password':(ROOT/'.runtime/admin-password').read_text(encoding='utf-8').strip()}).raise_for_status().json()
        admin={'admin-token':login['token']}
        try:(prepare if args.phase=='prepare' else accept)(client,admin)
        finally:client.post('/api/admin/logout',headers=admin)
