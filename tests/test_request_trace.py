import asyncio
import json
import sqlite3
import uuid

import httpx
from atguigu.listening.app import Settings, create_app
from test_listening import make_client


def test_trace_id_is_forwarded_without_sensitive_logs(tmp_path, caplog):
    rid = str(uuid.uuid4())
    seen = []
    def backend(request):
        seen.append(request.headers.get('x-request-id'))
        if request.url.path.endswith('/me'):
            return httpx.Response(200,json={'code':200,'data':{'id':1}})
        return httpx.Response(200,json={'code':200,'data':[]})
    with make_client(tmp_path,backend) as client, caplog.at_level('INFO',logger='uvicorn.error'):
        result=client.post('/api/assistant/chat',headers={'token':'private-user-token','x-request-id':rid},json={'text':'我上次听到哪里了'})
        assert result.status_code==200 and result.headers['x-request-id']==rid
        assert seen and all(v==rid for v in seen)
    assert 'private-user-token' not in caplog.text and '我上次听到哪里了' not in caplog.text
    assert rid in caplog.text


def test_invalid_trace_ids_are_replaced_and_validation_redacts_password(tmp_path):
    with make_client(tmp_path) as client:
        r=client.post('/api/account/login',headers={'x-request-id':'invalid-id'},json={'username':'x','password':'private-secret'})
        assert r.status_code==422 and 'private-secret' not in r.text
        uuid.UUID(r.headers['x-request-id'])


def test_rate_limit_rejects_second_call_and_preserves_history(tmp_path):
    with make_client(tmp_path,listening_ai_rate_limit=1) as client:
        r=client.post('/api/assistant/chat',headers={'token':'valid'},json={'text':'我的收听进度'})
        assert r.status_code==200
        again=client.post('/api/assistant/chat',headers={'token':'valid'},json={'text':'重复请求'})
        assert again.status_code==429 and again.headers['Retry-After']=='5'
        assert len(client.get('/api/history/'+r.json()['session_id'],headers={'token':'valid'}).json()['messages'])==2


def test_timeout_cancels_model_and_does_not_save_partial_history(tmp_path):
    slow = True
    async def backend(request):
        if request.url.path.endswith('/me'):
            return httpx.Response(200,json={'code':200,'data':{'id':1}})
        if slow:
                await asyncio.sleep(.5)
        return httpx.Response(200,json={'code':200,'data':[]})
    # Verify cancellation and rollback, without treating Windows scheduling as a 30 ms SLA.
    with make_client(tmp_path,backend,listening_ai_timeout=.15) as client:
        r=client.post('/api/assistant/chat',headers={'token':'valid'},json={'text':'我的收听进度'})
        assert r.status_code==504
        with sqlite3.connect(tmp_path/'history.db') as db:
            assert db.execute('SELECT COUNT(*) FROM turns').fetchone()[0]==0
        slow=False
        assert client.post('/api/assistant/chat',headers={'token':'valid'},json={'text':'我的收听进度'}).status_code==200


def test_concurrency_rejects_excess_work_then_recovers(tmp_path):
    async def scenario():
        entered, release = asyncio.Event(),asyncio.Event()
        async def backend(request):
            if request.url.path.endswith('/me'):
                return httpx.Response(200,json={'code':200,'data':{'id':1}})
            entered.set()
            await release.wait()
            return httpx.Response(200,json={'code':200,'data':[]})
        cfg=Settings(_env_file=None,listening_history_db=':memory:',listening_docs=str(tmp_path),listening_ai_concurrency=1)
        app=create_app(cfg,httpx.MockTransport(backend))
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
            first=asyncio.create_task(client.post('/api/assistant/chat',headers={'token':'one'},json={'text':'我的收听进度'}))
            await entered.wait()
            second=await client.post('/api/assistant/chat',headers={'token':'two'},json={'text':'我的收听进度'})
            assert second.status_code==429
            release.set()
            assert (await first).status_code==200
            assert (await client.post('/api/assistant/chat',headers={'token':'three'},json={'text':'我的收听进度'})).status_code==200
    asyncio.run(scenario())
