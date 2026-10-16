"""Real local-channel checks. Creates labeled fixtures; no external payment requests."""
import os
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _bootstrap import ROOT
import argparse
import concurrent.futures
import hashlib
import hmac
import json
import time
import uuid
import httpx
import pymysql
from verification_db import business_connection
from listening_common import private_value

runtime=ROOT/'.runtime'
parser=argparse.ArgumentParser()
parser.add_argument('--verify-restart',action='store_true')
args=parser.parse_args()
checks=[]
def check(name,condition):
    assert condition,name
    checks.append(name)
    print('PASS '+name,flush=True)
def poll(fn,predicate,seconds=30):
    end=time.monotonic()+seconds
    while time.monotonic()<end:
        value=fn()
        if predicate(value):return value
        time.sleep(.3)
    raise AssertionError('等待状态超时')
def signed(body):
    text='\n'.join(str(body[k]) for k in ['kind','targetId','receiptId','amount','outcome','timestamp'])
    return hmac.new(private_value('LISTENING_PAYMENT_CALLBACK_SECRET','payment-callback-key').encode(),text.encode(),hashlib.sha256).hexdigest()

with httpx.Client(base_url='http://127.0.0.1:29183',timeout=20,trust_env=False) as client:
    admin_password=os.environ.get('LISTENING_ADMIN_PASSWORD') or (runtime/'admin-password').read_text(encoding='utf-8').strip()
    admin=client.post('/api/admin/login',json={'username':'admin','password':admin_password}).raise_for_status().json()
    ah={'admin-token':admin['token']}
    if args.verify_restart:
        state=json.loads((runtime/'payment-restart-fixture.json').read_text(encoding='utf-8'))
        account=state['account']
        checks=state['checks']
    else:
        account={'username':'paytest_'+uuid.uuid4().hex[:14],'password':uuid.uuid4().hex+'aB9!'}
        client.post('/api/account/register',json=account).raise_for_status()
        (runtime/'payments-browser-account.json').write_text(json.dumps(account),encoding='utf-8')
    token=client.post('/api/account/login',json=account).raise_for_status().json()['token']
    headers={'token':token}
    db=business_connection(database='tingshu_order', autocommit=True, charset='utf8mb4')
    def get(path):return client.get(path,headers=headers).raise_for_status().json()
    def detail(oid):return get('/api/business/local/orders/'+str(oid))
    def sql(query,*params):
        with db.cursor() as cur:
            cur.execute(query,params)
            return cur.fetchall() if cur.description else cur.rowcount
    def create():return client.post('/api/business/local/checkout',headers=headers,json={'product':'listening-demo','idempotencyKey':uuid.uuid4().hex,'confirmed':True}).raise_for_status().json()
    def approve(o):
        client.post('/api/business/local/orders/'+o['orderId']+'/simulate',headers=headers,json={'outcome':'SUCCESS','confirmed':True}).raise_for_status()
        r=client.post('/api/business/after-sales/prepare',headers=headers,json={'orderId':o['orderId'],'reason':'本地支付退款验收申请'}).raise_for_status().json()
        client.post('/api/business/after-sales/'+r['id']+'/confirm',headers=headers,json={'confirmed':True}).raise_for_status()
        client.post('/api/admin/after-sales/'+r['id']+'/review',headers=ah,json={'decision':'APPROVED','note':'本地测试审核通过，无真实资金'}).raise_for_status()
        return r['id']
    def enqueue(rid,scenario):return client.post('/api/admin/refunds/'+rid,headers=ah,json={'scenario':scenario,'confirmed':True}).raise_for_status().json()
    try:
        if args.verify_restart:
            rid,oid=state['request_id'],state['order_id']
            result=poll(lambda:detail(oid),lambda x:x['status']=='0904',45)
            check('PROCESSING job recovered after actual service restart',result['refunds'][0]['status']=='SUCCEEDED')
            check('provider accepted exactly once after lost acknowledgement',sql('SELECT COUNT(*) FROM local_provider_receipt WHERE refund_id=%s',rid)[0][0]==1)
            check('refund success event persisted once',sql("SELECT COUNT(*) FROM after_sales_event WHERE request_id=%s AND event_type='REFUNDED'",rid)[0][0]==1)
            check('refund callback receipt persisted once',sql("SELECT COUNT(*) FROM local_callback WHERE kind='REFUND' AND target_id=%s",rid)[0][0]==1)
            check('request visibly refunded',sql('SELECT status FROM after_sales_request WHERE id=%s',rid)[0][0]=='REFUNDED')
            report={'passed':len(checks),'checks':checks,'real_funds':False,'restart_verified':True}
            (runtime/'payments-acceptance.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
            print(json.dumps(report,ensure_ascii=False,indent=2))
        else:
            check('catalog is explicitly local',get('/api/business/local/products')[0]['channel']=='LOCAL_SIMULATOR')
            body={'product':'listening-demo','idempotencyKey':uuid.uuid4().hex,'confirmed':True}
            check('checkout requires login',client.post('/api/business/local/checkout',json=body).status_code==401)
            check('price injection rejected',client.post('/api/business/local/checkout',headers=headers,json={**body,'amount':'0.01'}).status_code==422)
            check('explicit confirmation required',client.post('/api/business/local/checkout',headers=headers,json={**body,'confirmed':False}).status_code==422)
            with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
                orders=list(pool.map(lambda _:client.post('/api/business/local/checkout',headers=headers,json=body).raise_for_status().json(),range(6)))
            o=orders[0];oid=o['orderId']
            check('six concurrent checkouts produce one order',len({v['orderId'] for v in orders})==1)
            check('server price and marked order',o['amount']=='9.90' and o['orderNo'].startswith('LOCAL-TEST-'))
            other=client.post('/api/local/login').raise_for_status().json()['token']
            check('another user cannot read or pay order',client.get('/api/business/local/orders/'+oid,headers={'token':other}).status_code==404 and client.post('/api/business/local/orders/'+oid+'/simulate',headers={'token':other},json={'outcome':'SUCCESS','confirmed':True}).status_code==404)
            callback={'kind':'PAYMENT','targetId':o['paymentId'],'receiptId':uuid.uuid4().hex,'amount':'9.90','outcome':'SUCCESS','timestamp':int(time.time())}
            def send(b,signature):return client.post('http://127.0.0.1:19204/api/order/local/callback',json=b,headers={'x-payment-signature':signature})
            check('forged callback denied',send(callback,'forged').status_code==401)
            stale={**callback,'timestamp':int(time.time())-400}
            check('expired callback denied',send(stale,signed(stale)).status_code==401)
            wrong={**callback,'amount':'0.01'}
            check('signed wrong amount denied',send(wrong,signed(wrong)).status_code==409)
            check('failed payment recorded',client.post('/api/business/local/orders/'+oid+'/simulate',headers=headers,json={'outcome':'FAILED','confirmed':True}).raise_for_status().json()['paymentStatus']=='FAILED')
            with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
                replies=list(pool.map(lambda _:send(callback,signed(callback)),range(6)))
            check('six callback replays accepted idempotently',all(r.status_code==200 for r in replies))
            check('one payment success event',sql("SELECT COUNT(*) FROM local_transaction_event WHERE order_id=%s AND event_type='PAYMENT_SUCCEEDED'",oid)[0][0]==1)
            check('one receipt for repeated callback',sql('SELECT COUNT(*) FROM local_callback WHERE receipt_id=%s',callback['receiptId'])[0][0]==1)
            check('paid order cannot cancel',client.post('/api/business/local/orders/'+oid+'/cancel',headers=headers).status_code==409)
            check('late failure cannot undo success',client.post('/api/business/local/orders/'+oid+'/simulate',headers=headers,json={'outcome':'FAILED','confirmed':True}).raise_for_status().json()['paymentStatus']=='SUCCEEDED')
            b=create();client.post('/api/business/local/orders/'+b['orderId']+'/cancel',headers=headers).raise_for_status()
            check('cancelled order cannot revive',client.post('/api/business/local/orders/'+b['orderId']+'/simulate',headers=headers,json={'outcome':'SUCCESS','confirmed':True}).raise_for_status().json()['status']=='0903')
            b=create();sql('UPDATE local_checkout SET expires_at=DATE_SUB(NOW(),INTERVAL 1 SECOND) WHERE order_id=%s',b['orderId'])
            poll(lambda:detail(b['orderId']),lambda v:v['status']=='0903')
            check('scheduler cancels expired local order',detail(b['orderId'])['paymentStatus']=='CLOSED')
            b=create();rid=approve(b)
            check('ordinary token cannot dispatch refund',client.post('/api/admin/refunds/'+rid,headers=headers,json={'scenario':'SUCCESS','confirmed':True}).status_code==401)
            check('refund needs explicit confirmation',client.post('/api/admin/refunds/'+rid,headers=ah,json={'scenario':'SUCCESS','confirmed':False}).status_code==422)
            enqueue(rid,'ALWAYS_FAIL')
            for attempt in range(1,6):
                poll(lambda:detail(b['orderId'])['refunds'][0],lambda j:j['attempts']>=attempt and j['status'] in {'PENDING','FAILED'})
                if attempt<5:
                    sql("UPDATE local_refund_job SET available_at=NOW() WHERE id=%s AND status='PENDING'",rid)
            check('bounded retries stop at five attempts',detail(b['orderId'])['refunds'][0]['status']=='FAILED' and detail(b['orderId'])['refunds'][0]['attempts']==5)
            check('failed refund did not invent receipt',sql('SELECT COUNT(*) FROM local_provider_receipt WHERE refund_id=%s',rid)[0][0]==0)
            enqueue(rid,'SUCCESS');poll(lambda:detail(b['orderId']),lambda x:x['status']=='0904')
            check('administrator retry recovers failed refund',detail(b['orderId'])['refunds'][0]['status']=='SUCCEEDED')
            check('refunded order cannot create second application',client.post('/api/business/after-sales/prepare',headers=headers,json={'orderId':b['orderId'],'reason':'重复退款测试申请'}).status_code==409)
            # Durable fixture for a real restart, before provider acknowledgement is delivered.
            b=create();rid=approve(b);enqueue(rid,'TIMEOUT_ONCE')
            poll(lambda:detail(b['orderId'])['refunds'][0],lambda j:j['attempts']==1 and j['status']=='PENDING')
            check('provider receipt survives response loss',sql('SELECT COUNT(*) FROM local_provider_receipt WHERE refund_id=%s',rid)[0][0]==1)
            sql("UPDATE local_refund_job SET status='PROCESSING',available_at=DATE_ADD(NOW(),INTERVAL 20 SECOND) WHERE id=%s AND status='PENDING'",rid)
            state={'account':account,'order_id':b['orderId'],'request_id':rid,'checks':checks}
            (runtime/'payment-restart-fixture.json').write_text(json.dumps(state,ensure_ascii=False),encoding='utf-8')
            print('READY_FOR_ACTUAL_ORDER_SERVICE_RESTART',flush=True)
    finally:
        db.close()
        client.post('/api/account/logout',headers=headers)
        client.post('/api/admin/logout',headers=ah)
