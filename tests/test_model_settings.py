import asyncio
import json
import os

import httpx
import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from listening_common import ServiceSettings, model_json
from model_settings import (ModelStore, ModelConnection, ModelConfiguration, active_connection,
                            embedding_payload, chat_payload, test_connection as probe, check_response)
from test_listening import make_client


def connection(**changes):
    return {'provider': 'custom', 'base_url': 'https://models.example/v1', 'model': 'chat-test',
            'api_key': 'private-test-key', 'dimensions': 3, 'send_dimensions': False, **changes}


def configuration(**changes):
    return ModelConfiguration(chat=ModelConnection(**connection(**changes)),
                              embedding=ModelConnection(**connection(model='embed-test')))


def administrator(request):
    token = request.headers.get('admin-token')
    if not token:
        return httpx.Response(401, json={'detail': '请登录管理端'})
    return httpx.Response(200, json={'code': 200, 'data': {'id': '42', 'permissions':
        ['admin:access', 'models:manage'] if token == 'administrator' else ['admin:access']}})


def test_encrypted_round_trip_and_empty_key_retention(tmp_path):
    cfg = ServiceSettings(_env_file=None, llm_api_key='old-env-key')
    store = ModelStore(tmp_path / 'settings.json')
    result = store.save(cfg, configuration())
    assert result['chat']['has_api_key'] is True
    assert 'private-test-key' not in store.path.read_text()
    assert 'api_key' not in result['chat']
    assert ModelStore(store.path).read()['chat']['api_key'] == 'private-test-key'
    store.save(cfg, configuration(api_key=''))
    assert store.read()['chat']['api_key'] == 'private-test-key'
    assert cfg.llm_api_key == 'old-env-key'


def test_changing_endpoint_or_provider_cannot_reuse_old_key(tmp_path):
    cfg = ServiceSettings(_env_file=None, llm_api_key='env-key')
    store = ModelStore(tmp_path / 'settings.json')
    store.save(cfg, configuration())
    original = store.path.read_bytes()
    for changes in [{'provider': 'deepseek'}, {'base_url': 'https://another.example/v1'}]:
        with pytest.raises(HTTPException) as error:
            store.save(cfg, configuration(api_key='', **changes))
        assert error.value.status_code == 422
        assert store.path.read_bytes() == original


@pytest.mark.parametrize('url', ['http://models.example/v1', 'https://user:secret@models.example/v1',
    'https://models.example/v1?key=secret', 'https://models.example/v1/chat/completions', 'file:///tmp/test'])
def test_invalid_base_url_is_rejected(url):
    with pytest.raises(ValidationError):
        ModelConnection(**connection(base_url=url))


def test_local_compatible_server_and_dimensions_switch():
    local = ModelConnection(**connection(base_url='http://127.0.0.1:11434/v1/'))
    assert local.base_url.endswith('/v1')
    assert 'dimensions' not in embedding_payload(local.model_dump(), ['hello'])
    assert embedding_payload(connection(send_dimensions=True), ['hello'])['dimensions'] == 3


def test_model_configuration_requires_current_admin_permission(tmp_path):
    with make_client(tmp_path, administrator) as client:
        for headers, expected in [({}, 401), ({'token': 'administrator'}, 401), ({'admin-token': 'reviewer'}, 403)]:
            assert client.get('/api/admin/models', headers=headers).status_code == expected
            body = configuration().model_dump(mode='json')
            body['chat']['api_key'] = body['embedding']['api_key'] = 'private-test-key'
            assert client.post('/api/admin/models', headers=headers, json=body).status_code == expected
            assert client.post('/api/admin/models/test/chat', headers=headers, json=connection()).status_code == expected
        assert not (tmp_path / 'model-settings.json').exists()


def test_save_and_read_never_echo_key_and_validation_error_redacts_body(tmp_path):
    with make_client(tmp_path, administrator) as client:
        headers = {'admin-token': 'administrator'}
        response = client.post('/api/admin/models', headers=headers, json={'chat': connection(), 'embedding': connection(model='embed-test')})
        assert response.status_code == 200, response.text
        assert 'private-test-key' not in response.text
        assert 'private-test-key' not in client.get('/api/admin/models', headers=headers).text
        invalid = connection(dimensions='private-test-key', unexpected='private-test-key')
        response = client.post('/api/admin/models/test/chat', headers=headers, json=invalid)
        assert response.status_code == 422
        assert 'private-test-key' not in response.text


def test_revoked_permission_prevents_existing_session_from_writing(tmp_path):
    allowed = True
    def backend(request):
        return httpx.Response(200, json={'code': 200, 'data': {'permissions': ['models:manage'] if allowed else []}})
    with make_client(tmp_path, backend) as client:
        headers = {'admin-token': 'same-session'}
        assert client.get('/api/admin/models', headers=headers).status_code == 200
        allowed = False
        assert client.post('/api/admin/models', headers=headers, json={'chat': connection(), 'embedding': connection()}).status_code == 403
        assert not (tmp_path / 'model-settings.json').exists()


def test_chat_probe_checks_normal_json_and_tools_without_saving(tmp_path):
    paths = []
    def backend(request):
        if request.url.path.endswith('/admin/me'):
            return administrator(request)
        paths.append(request.url.path)
        body = json.loads(request.content)
        if 'tools' in body:
            message = {'tool_calls': [{'function': {'name': 'connection_check', 'arguments': '{"ok":true}'}}]}
        else:
            message = {'content': '{"ok":true}' if 'response_format' in body else 'OK'}
        return httpx.Response(200, json={'choices': [{'message': message}]})
    with make_client(tmp_path, backend) as client:
        response = client.post('/api/admin/models/test/chat', headers={'admin-token': 'administrator'}, json=connection())
        assert response.status_code == 200, response.text
        assert response.json()['ok'] is True
        assert paths == ['/v1/chat/completions'] * 3
        assert not (tmp_path / 'model-settings.json').exists()


@pytest.mark.parametrize('response', [httpx.Response(200, json={'data': [{'embedding': [1, 2]}]}),
    httpx.Response(200, json={'data': [{'embedding': [0, 0, 0]}]}),
    httpx.Response(200, json={'choices': [{'message': {'content': 'I do not support tools'}}]})])
def test_probe_rejects_mismatched_dimensions_or_tool_incompatibility(response):
    def client(): return httpx.AsyncClient(transport=httpx.MockTransport(lambda r: response))
    with pytest.raises(HTTPException) as error:
        asyncio.run(probe(connection(), 'embedding' if 'data' in response.json() else 'chat', client))
    assert error.value.status_code == 502


@pytest.mark.parametrize('status,code,expected', [(400,'Arrearage',503),(429,'insufficient_quota',503),
    (401,None,502),(403,None,502),(402,None,503),(404,None,502),(429,None,503),(500,None,502)])
def test_provider_errors_are_sanitized(status,code,expected):
    response = httpx.Response(status, json={'error': {'code': code, 'message': 'private-test-key'}})
    with pytest.raises(HTTPException) as error:
        check_response(response)
    assert error.value.status_code == expected
    assert 'private-test-key' not in error.value.detail


def test_saved_chat_configuration_is_used_by_live_assistant(tmp_path):
    models = []
    def backend(request):
        if request.url.path.endswith('/admin/me'):
            return administrator(request)
        if request.url.path.endswith('/me'):
            return httpx.Response(200,json={'code':200,'data':{'id':1}})
        if request.url.path.endswith('/progress'):
            return httpx.Response(200,json={'code':200,'data':[]})
        payload = json.loads(request.content)
        models.append((payload['model'], request.headers['authorization'], request.url.host))
        message = {'role':'assistant','content':'result'} if any(m['role']=='tool' for m in payload['messages']) else {'role':'assistant','tool_calls':[{'id':'call1','type':'function','function':{'name':'get_progress','arguments':'{}'}}]}
        return httpx.Response(200,json={'choices':[{'message':message}]})
    with make_client(tmp_path, backend, listening_use_llm=True) as client:
        headers = {'admin-token':'administrator'}
        for model in ['first-model','second-model']:
            assert client.post('/api/admin/models',headers=headers,json={'chat':connection(model=model),'embedding':connection(model='embed')}).status_code == 200
            response = client.post('/api/assistant/chat',headers={'token':'valid'},json={'text':'收听进度'})
            assert response.status_code == 200, response.text
        assert [m[0] for m in models] == ['first-model','first-model','second-model','second-model']
        assert all(m[1:] == ('Bearer private-test-key','models.example') for m in models)


def test_embedding_model_namespace_does_not_reuse_vectors_from_other_provider(tmp_path):
    from app.listening.index import VectorIndex
    docs = tmp_path / 'docs'
    docs.mkdir()
    (docs/'书简介.md').write_text('## 内容\n听书测试资料内容',encoding='utf-8')
    cfg = ServiceSettings(_env_file=None,listening_docs=str(docs),listening_index_db=str(tmp_path/'index.db'))
    requests=[]
    def backend(request):
        requests.append(str(request.url))
        assert 'dimensions' not in json.loads(request.content)
        return httpx.Response(200,json={'data':[{'index':0,'embedding':[1,0,0]}]})
    for url in ['https://one.example/v1','https://one.example/v1','https://two.example/v1']:
        index = VectorIndex(cfg,httpx.MockTransport(backend),connection=connection(base_url=url))
        asyncio.run(index.build())
    assert len(requests)==2


def test_shared_json_call_reads_saved_provider(tmp_path,monkeypatch):
    cfg = ServiceSettings(_env_file=None,listening_model_settings_file=str(tmp_path/'model-settings.json'))
    ModelStore(cfg.listening_model_settings_file).save(cfg,configuration(model='json-model'))
    real = httpx.AsyncClient
    def backend(request):
        assert request.url.host=='models.example'
        assert json.loads(request.content)['model']=='json-model'
        return httpx.Response(200,json={'choices':[{'message':{'content':'{"ok":true}'}}]})
    monkeypatch.setattr(httpx,'AsyncClient',lambda **kwargs: real(**kwargs,transport=httpx.MockTransport(backend)))
    assert asyncio.run(model_json(cfg,'Return JSON','test')) == {'ok':True}


def test_embedding_probe_accepts_exact_dimensions():
    def backend(request):
        assert request.url.path == '/v1/embeddings'
        assert 'dimensions' not in json.loads(request.content)
        return httpx.Response(200,json={'data':[{'embedding':[1,0,0]}]})
    def client(): return httpx.AsyncClient(transport=httpx.MockTransport(backend))
    result = asyncio.run(probe(connection(), 'embedding', client))
    assert result['ok'] and result['dimensions'] == 3


def test_deepseek_non_thinking_applies_only_to_official_host():
    official = connection(provider='deepseek', base_url='https://api.deepseek.com/v1')
    assert chat_payload(official, tool_choice='required')['thinking'] == {'type': 'disabled'}
    assert 'thinking' not in chat_payload(connection(), tool_choice='required')
    assert 'thinking' not in chat_payload(connection(base_url='https://api.deepseek.com.example/v1'))


def test_probe_and_live_json_use_deepseek_mode(monkeypatch):
    official = connection(provider='deepseek', base_url='https://api.deepseek.com/v1')
    def backend(request):
        body = json.loads(request.content)
        assert body['thinking'] == {'type': 'disabled'}
        if 'tools' in body:
            message = {'tool_calls': [{'function': {'name': 'connection_check', 'arguments': '{"ok":true}'}}]}
        else:
            message = {'content': '{"ok":true}' if 'response_format' in body else 'OK'}
        if 'max_tokens' in body:
            assert body['max_tokens'] >= 1024
        return httpx.Response(200, json={'choices': [{'finish_reason': 'stop', 'message': message}]})
    real = httpx.AsyncClient
    factory = lambda **kwargs: real(**kwargs, transport=httpx.MockTransport(backend))
    assert asyncio.run(probe(official, 'chat', factory))['ok']
    monkeypatch.setattr('listening_common.active_connection', lambda cfg: official)
    monkeypatch.setattr(httpx, 'AsyncClient', factory)
    assert asyncio.run(model_json(ServiceSettings(_env_file=None), 'Return JSON', 'test')) == {'ok': True}


@pytest.mark.parametrize('failure_stage', ['普通对话', 'JSON 输出', '工具调用'])
def test_probe_identifies_truncated_stage_without_leaking_response(failure_stage):
    def backend(request):
        body = json.loads(request.content)
        stage = '工具调用' if 'tools' in body else 'JSON 输出' if 'response_format' in body else '普通对话'
        message = {'content': '{"ok":true}' if stage == 'JSON 输出' else 'OK'}
        if stage == failure_stage:
            message = {'content': None, 'reasoning_content': 'private-test-key'}
        return httpx.Response(200, json={'choices': [{'finish_reason': 'length' if stage == failure_stage else 'stop', 'message': message}]})
    def factory(): return httpx.AsyncClient(transport=httpx.MockTransport(backend))
    with pytest.raises(HTTPException) as error:
        asyncio.run(probe(connection(), 'chat', factory))
    assert failure_stage in error.value.detail and '截断' in error.value.detail
    assert 'private-test-key' not in error.value.detail


def test_dimension_error_reports_expected_and_actual():
    def factory(): return httpx.AsyncClient(transport=httpx.MockTransport(lambda r:
        httpx.Response(200, json={'data': [{'embedding': [1, 2]}]})))
    with pytest.raises(HTTPException) as error:
        asyncio.run(probe(connection(), 'embedding', factory))
    assert '配置 3 维' in error.value.detail and '返回 2 维' in error.value.detail


def test_rag_switch_is_lazy_serialized_and_keeps_request_index(monkeypatch):
    import app.listening.service as service
    selected = connection()
    builds = []
    class FakeIndex:
        def __init__(self, cfg, connection):
            self.connection = connection.copy()
            self.vectors = None
            self.generation = 'test-corpus'
        async def build(self):
            builds.append(self.connection['model'])
            await asyncio.sleep(0)
            self.vectors = [self.connection['model']]
    monkeypatch.setattr(service,'VectorIndex',FakeIndex)
    monkeypatch.setattr(service,'active_connection',lambda *args: selected.copy())
    monkeypatch.setattr(service,'index',FakeIndex(service.cfg,selected))
    monkeypatch.setattr(service,'index_lock',asyncio.Lock())
    async def scenario():
        first, duplicate = await asyncio.gather(service.current_index(), service.current_index())
        assert first is duplicate
        selected['model']='changed-embedding'
        second = await service.current_index()
        assert second is not first
        assert first.vectors == ['chat-test']
        assert second.vectors == ['changed-embedding']
        assert builds == ['chat-test','changed-embedding']
    asyncio.run(scenario())
