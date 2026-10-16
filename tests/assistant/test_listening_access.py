import json

import httpx
import pytest
from test_listening import make_client

RID='deea68fb-2e48-4a47-a654-3f484a1c1380'

@pytest.mark.parametrize('status',[401,403,409,429])
def test_java_access_errors_keep_their_status(tmp_path,status):
    def backend(request):
        return httpx.Response(status,json={'detail':'Java 拒绝此请求'})
    with make_client(tmp_path,backend) as client:
        response=client.post('/api/admin/login',json={'username':'admin','password':'valid-length-secret'})
        assert response.status_code==status

def test_role_cannot_be_injected_during_registration(tmp_path):
    def never_called(request):raise AssertionError('无效字段不应转发')
    with make_client(tmp_path,never_called) as client:
        assert client.post('/api/account/register',json={'username':'test_user','password':'valid-length-secret','role':'administrator'}).status_code==422

def test_review_requires_explicit_decision_and_no_actor_override(tmp_path):
    def never_called(request):raise AssertionError('无效审核不应转发')
    with make_client(tmp_path,never_called) as client:
        for body in [{'decision':'REFUNDED','note':'审核意见完整文本'}, {'decision':'APPROVED','note':'审核意见完整文本','actor_id':900010}]:
            assert client.post('/api/admin/after-sales/'+RID+'/review',json=body).status_code==422

def test_admin_session_and_user_token_are_not_interchangeable(tmp_path):
    def backend(request):
        assert not request.headers.get('token')
        assert not request.headers.get('admin-token')
        return httpx.Response(401,json={'detail':'请登录管理端'})
    with make_client(tmp_path,backend) as client:
        assert client.get('/api/admin/me',headers={'token':'ordinary-user-token'}).status_code==401

def test_review_actor_is_taken_only_from_java_session(tmp_path):
    def backend(request):
        assert request.headers['admin-token']=='real-admin-session'
        assert not request.headers.get('token')
        assert json.loads(request.content)=={'decision':'REJECTED','note':'请补充购买情况说明'}
        return httpx.Response(200,json={'code':200,'data':{'status':'REJECTED','reviewNote':'请补充购买情况说明'}})
    with make_client(tmp_path,backend,listening_order_url='http://orders') as client:
        response=client.post('/api/admin/after-sales/'+RID+'/review',headers={'admin-token':'real-admin-session','token':'ordinary'},json={'decision':'REJECTED','note':'请补充购买情况说明'})
        assert response.status_code==200,response.text
        assert response.json()['status']=='REJECTED'

def test_admin_operations_actor_is_bound_and_reviewer_is_denied(tmp_path):
    def backend(request):
        if request.url.path.endswith('/admin/me'):
            permissions=['admin:access','operations:read'] if request.headers['admin-token']=='operator' else ['admin:access','after_sales:review']
            return httpx.Response(200,json={'code':200,'data':{'id':'42','permissions':permissions}})
        assert json.loads(request.content)=={'question':'用户总数','actor_id':'42'}
        assert request.headers['x-listening-key']=='test-private-key'
        return httpx.Response(200,json={'rows':[]})
    with make_client(tmp_path,backend,listening_operations_url='http://ops',listening_service_key='test-private-key') as client:
        assert client.post('/api/admin/ops/query',headers={'admin-token':'reviewer'},json={'text':'用户总数'}).status_code==403
        assert client.post('/api/admin/ops/query',headers={'admin-token':'operator'},json={'text':'用户总数','actor_id':'999'}).status_code==422
        assert client.post('/api/admin/ops/query',headers={'admin-token':'operator'},json={'text':'用户总数'}).status_code==200

def test_invalid_paging_is_rejected_before_upstream(tmp_path):
    def never_called(request):raise AssertionError('无界分页不应访问数据库')
    with make_client(tmp_path,never_called) as client:
        for path in ['/api/admin/after-sales?size=500','/api/content/albums?page=0','/api/business/orders/page?size=0']:
            assert client.get(path).status_code==422

def test_media_path_cannot_read_arbitrary_files(tmp_path):
    with make_client(tmp_path) as client:
        assert client.get('/api/media/12345').status_code==404

def test_model_arrearage_is_reported_without_fabricated_success(tmp_path):
    def backend(request):
        if request.url.path.endswith('/me'):
            return httpx.Response(200,json={'code':200,'data':{'id':42}})
        return httpx.Response(400,json={'error':{'code':'Arrearage'}})
    with make_client(tmp_path,backend,listening_use_llm=True,llm_api_key='test-key') as client:
        response=client.post('/api/assistant/chat',headers={'token':'valid'},json={'text':'收听进度'})
        assert response.status_code==503
        assert '余额不足' in response.json()['detail']
        assert 'text' not in response.json()
