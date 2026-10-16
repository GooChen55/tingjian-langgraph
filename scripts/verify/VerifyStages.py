"""前两阶段验收：真实 Java RBAC、审核并发、H5 业务 API 和进度隔离。

仅新增带本地验收标记的账号和订单，保留审计；不执行支付或退款。
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _bootstrap import ROOT
import json
import os
import secrets
import uuid
from concurrent.futures import ThreadPoolExecutor

import httpx
import pymysql
from verification_db import business_connection

BASE = 'http://127.0.0.1:29183'
report = {'passed': False, 'checks': []}
db = business_connection(charset='utf8mb4', autocommit=True, cursorclass=pymysql.cursors.DictCursor)

def checked(label, condition):
    assert condition, label
    report['checks'].append(label)

with db, httpx.Client(base_url=BASE,timeout=120,trust_env=False) as client:
    admin_body={'username':'admin','password':(ROOT/'.runtime/admin-password').read_text().strip()}
    checked('未登录管理端被拒绝',client.get('/api/admin/me').status_code==401)
    checked('错误管理密码被拒绝',client.post('/api/admin/login',json={**admin_body,'password':'wrong-password-123'}).status_code==401)
    admin_headers={'admin-token':client.post('/api/admin/login',json=admin_body).raise_for_status().json()['token']}
    checked('管理端角色和权限来自 Java', 'after_sales:review' in client.get('/api/admin/me',headers=admin_headers).json()['permissions'])
    credentials={'username':'test_'+uuid.uuid4().hex[:12],'password':secrets.token_urlsafe(24)}
    client.post('/api/account/register',json=credentials).raise_for_status()
    checked('注册重名被拒绝',client.post('/api/account/register',json=credentials).status_code==409)
    checked('普通账号不能登录管理端',client.post('/api/admin/login',json=credentials).status_code==403)
    checked('错误听友密码被拒绝',client.post('/api/account/login',json={**credentials,'password':'wrong-password-123'}).status_code==401)
    token=client.post('/api/account/login',json=credentials).raise_for_status().json()['token']
    headers={'token':token}
    owner=int(client.get('/api/me',headers=headers).raise_for_status().json()['id'])
    checked('普通听友没有运营权限',client.post('/api/ops/query',headers=headers,json={'text':'用户总数'}).status_code==403)
    checked('听友令牌不能替代管理会话',client.get('/api/admin/me',headers={'admin-token':token}).status_code==401)
    with db.cursor() as cursor:
        cursor.execute("UPDATE tingshu_user.user_info SET nickname='本地验收听友',wx_open_id=%s WHERE id=%s",('local-demo-test-'+credentials['username'],owner))
        cursor.execute('SELECT COALESCE(MAX(id),900002)+1 AS next_id FROM tingshu_order.order_info')
        first_id=cursor.fetchone()['next_id']
        for index in range(3):
            cursor.execute("INSERT INTO tingshu_order.order_info(id,user_id,order_title,order_no,order_status,order_amount,original_amount) VALUES(%s,%s,%s,%s,'0902',9.90,9.90)",
                (first_id+index,owner,'【本地验收】审核流程 '+str(index+1),'LOCAL-TEST-'+uuid.uuid4().hex))
    drafts=[]
    for index in range(3):
        draft=client.post('/api/business/after-sales/prepare',headers=headers,json={'orderId':str(first_id+index),'reason':'本地验收：误购，请审核售后原因'}).raise_for_status().json()
        drafts.append(draft['id'])
        client.post('/api/business/after-sales/'+draft['id']+'/confirm',headers=headers,json={'confirmed':True}).raise_for_status()
    checked('订单分页与所有权',client.get('/api/business/orders/page?size=1&page=2',headers=headers).json()['total']==3)
    checked('伪造审核人参数被拒绝',client.post('/api/admin/after-sales/'+drafts[0]+'/review',headers=admin_headers,json={'decision':'APPROVED','note':'本地审核验证通过','actor_id':owner}).status_code==422)
    def review_parallel(index):
        decision='APPROVED' if index%2==0 else 'REJECTED'
        with httpx.Client(base_url=BASE,timeout=30,trust_env=False) as concurrent:
            result=concurrent.post('/api/admin/after-sales/'+drafts[0]+'/review',headers=admin_headers,json={'decision':decision,'note':'本地审核并发验证意见'})
            return result.status_code,result.json()
    with ThreadPoolExecutor(max_workers=6) as workers: outcomes=list(workers.map(review_parallel,range(6)))
    checked('并发审核只允许一种结果且重试幂等',len({body['status'] for status,body in outcomes if status==200})==1 and all(status in (200,409) for status,_ in outcomes))
    events=client.get('/api/admin/after-sales/'+drafts[0]+'/events',headers=admin_headers).raise_for_status().json()
    reviews=[event for event in events if event['event_type'] in ('APPROVED','REJECTED')]
    checked('审核审计只写一次且绑定真实管理身份',len(reviews)==1 and reviews[0]['actor_id']==900010)
    rejected=client.post('/api/admin/after-sales/'+drafts[1]+'/review',headers=admin_headers,json={'decision':'REJECTED','note':'本地验收：请补充购买情况后重新申请'}).raise_for_status().json()
    user_requests=client.get('/api/business/after-sales/page',headers=headers).raise_for_status().json()['records']
    checked('审核意见回显给申请人',any(r['id']==drafts[1] and r['reviewNote']==rejected['reviewNote'] for r in user_requests))
    checked('已审核申请不可撤回',client.post('/api/business/after-sales/'+drafts[1]+'/withdraw',headers=headers).status_code==409)
    checked('普通身份不能审核',client.post('/api/admin/after-sales/'+drafts[2]+'/review',headers={'admin-token':token},json={'decision':'APPROVED','note':'本地验收审批意见'}).status_code==401)
    # 仅给本次创建的验收账号临时授予 reviewer，验证权限分级和即时撤销，finally 移除。
    with db.cursor() as cursor:cursor.execute("INSERT INTO tingshu_user.access_user_role VALUES(%s,'reviewer')",(owner,))
    try:
        reviewer_headers={'admin-token':client.post('/api/admin/login',json=credentials).raise_for_status().json()['token']}
        checked('审核角色无运营权限',client.post('/api/admin/ops/query',headers=reviewer_headers,json={'text':'用户总数'}).status_code==403)
        client.get('/api/admin/after-sales',headers=reviewer_headers).raise_for_status()
        with db.cursor() as cursor:cursor.execute("DELETE FROM tingshu_user.access_user_role WHERE user_id=%s AND role_code='reviewer'",(owner,))
        checked('撤销角色后原会话立即失效',client.get('/api/admin/after-sales',headers=reviewer_headers).status_code==403)
    finally:
        with db.cursor() as cursor:cursor.execute("DELETE FROM tingshu_user.access_user_role WHERE user_id=%s AND role_code='reviewer'",(owner,))
        client.post('/api/admin/logout',headers=reviewer_headers)
    role='test_'+uuid.uuid4().hex[:12]
    with db.cursor() as cursor:
        cursor.execute('INSERT INTO tingshu_user.access_role(code,label) VALUES(%s,%s)',(role,'本地权限验收'))
        for permission in ['admin:access','after_sales:read','after_sales:review']:
            cursor.execute('INSERT INTO tingshu_user.access_role_permission VALUES(%s,%s)',(role,permission))
        cursor.execute('INSERT INTO tingshu_user.access_user_role VALUES(%s,%s)',(owner,role))
    restricted_headers={}
    try:
        restricted_headers={'admin-token':client.post('/api/admin/login',json=credentials).raise_for_status().json()['token']}
        checked('独立验收角色可读取审核列表',client.get('/api/admin/after-sales',headers=restricted_headers).status_code==200)
        with db.cursor() as cursor:cursor.execute("DELETE FROM tingshu_user.access_role_permission WHERE role_code=%s AND permission_code='admin:access'",(role,))
        checked('撤销管理入口权限后保留审核权限也不能访问',client.get('/api/admin/after-sales',headers=restricted_headers).status_code==403)
        with db.cursor() as cursor:
            cursor.execute("INSERT INTO tingshu_user.access_role_permission VALUES(%s,'admin:access')",(role,))
            cursor.execute('UPDATE tingshu_user.access_account SET enabled=0 WHERE user_id=%s',(owner,))
        checked('禁用账号立即阻止已有管理会话',client.get('/api/admin/after-sales',headers=restricted_headers).status_code==403)
        with db.cursor() as cursor:
            cursor.execute('UPDATE tingshu_user.access_account SET enabled=1 WHERE user_id=%s',(owner,))
            cursor.execute('UPDATE tingshu_user.user_info SET is_deleted=1 WHERE id=%s',(owner,))
        checked('已逻辑删除的账号不能重新登录',client.post('/api/account/login',json=credentials).status_code==401)
    finally:
        with db.cursor() as cursor:
            cursor.execute('UPDATE tingshu_user.user_info SET is_deleted=0 WHERE id=%s',(owner,))
            cursor.execute('UPDATE tingshu_user.access_account SET enabled=1 WHERE user_id=%s',(owner,))
            cursor.execute('DELETE FROM tingshu_user.access_user_role WHERE user_id=%s AND role_code=%s',(owner,role))
            cursor.execute('DELETE FROM tingshu_user.access_role_permission WHERE role_code=%s',(role,))
            cursor.execute('DELETE FROM tingshu_user.access_role WHERE code=%s',(role,))
        client.post('/api/admin/logout',headers=restricted_headers)
    checked('H5 产物可访问',client.get('/listen/').status_code==200)
    album=client.get('/api/content/albums/900001').raise_for_status().json()
    checked('真实专辑和声音列表',album['id']==900001 and client.get('/api/content/albums/900001/tracks').json()['total']==2)
    response=client.get('/api/media/900001',headers={'Range':'bytes=0-1023'})
    checked('音频支持浏览器分段读取',response.status_code==206 and len(response.content)==1024)
    checked('未登录不能保存进度',client.post('/api/playback/progress',json={'albumId':900001,'trackId':900001,'breakSecond':8}).status_code==401)
    client.post('/api/playback/progress',headers=headers,json={'albumId':900001,'trackId':900001,'breakSecond':8.25}).raise_for_status()
    checked('真实 MongoDB 进度保存并读回',float(client.get('/api/playback/progress/900001',headers=headers).json()['breakSecond'])==8.25)
    checked('伪造进度用户参数被拒绝',client.post('/api/playback/progress',headers=headers,json={'albumId':900001,'trackId':900001,'breakSecond':1,'userId':900001}).status_code==422)
    checked('专辑声音关系必须匹配',client.post('/api/playback/progress',headers=headers,json={'albumId':1,'trackId':900001,'breakSecond':1}).status_code==404)
    checked('负数进度被拒绝',client.post('/api/playback/progress',headers=headers,json={'albumId':900001,'trackId':900001,'breakSecond':-1}).status_code==422)
    other={'username':'other_'+uuid.uuid4().hex[:12],'password':secrets.token_urlsafe(24)}
    client.post('/api/account/register',json=other).raise_for_status()
    other_headers={'token':client.post('/api/account/login',json=other).raise_for_status().json()['token']}
    other_id=int(client.get('/api/me',headers=other_headers).json()['id'])
    with db.cursor() as cursor:cursor.execute('UPDATE tingshu_user.user_info SET wx_open_id=%s WHERE id=%s',('local-demo-test-'+other['username'],other_id))
    checked('进度按登录用户隔离',float(client.get('/api/playback/progress/900001',headers=other_headers).json()['breakSecond'])==0)
    checked('售后分页按登录用户隔离',client.get('/api/business/after-sales/page',headers=other_headers).json()['total']==0)
    with db.cursor() as cursor:
        cursor.execute("SELECT t.id FROM tingshu_album.track_info t JOIN tingshu_album.album_info a ON a.id=t.album_id WHERE a.pay_type!='0101' AND t.order_num>a.tracks_for_free AND a.is_deleted=0 AND a.is_open='1' AND a.status='0301' AND t.is_deleted=0 AND t.is_open='1' AND t.status='0501' LIMIT 1")
        paid=cursor.fetchone()
    checked('付费声音权限未被绕过',client.get('/api/content/tracks/'+str(paid['id'])).status_code==403)
    client.post('/api/account/logout',headers=other_headers).raise_for_status()
    checked('听友退出后旧令牌失效',client.get('/api/me',headers=other_headers).status_code==401)
    client.post('/api/admin/logout',headers=admin_headers).raise_for_status()
    checked('管理员退出后旧会话失效',client.get('/api/admin/me',headers=admin_headers).status_code==401)
    # 私有浏览器测试账号文件，仅用于本地验收登录，不输出密码或令牌。
    (ROOT/'.runtime/stage4-browser-account.json').write_text(json.dumps(credentials),encoding='utf-8')
    report.update(passed=True,user_id=owner,pending_request=drafts[2],concurrency_statuses=[s for s,_ in outcomes])
(ROOT/'.runtime/stages-v4.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'passed':True,'checks':len(report['checks']),'concurrency_statuses':report['concurrency_statuses']},ensure_ascii=False))
