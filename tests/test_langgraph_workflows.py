import asyncio
import json
import sqlite3
import uuid
import pytest
import pymysql
from fastapi import HTTPException
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.types import Command
from listening.graph import build_query_graph
from listening.runs import claim, mark
from atguigu.listening.graph import build_assistant_graph


SQL = 'SELECT album_count FROM v_content_summary'


def initial():
    return {'question': '专辑总量', 'actor_id': '1', 'request_id': str(uuid.uuid4()),
            'repairs': 0, 'clarifications': 0, 'trace': []}


def test_invalid_column_is_repaired_and_revalidated():
    calls, executed = [], []
    async def generate(system, user):
        calls.append(json.loads(user))
        return {'sql': 'SELECT unknown FROM v_content_summary' if len(calls) == 1 else SQL}
    async def execute(sql):
        executed.append(sql)
        assert sql.endswith('LIMIT 100')
        return [{'album_count': 12}]
    result = asyncio.run(build_query_graph(generate, execute).ainvoke(initial()))
    assert result['repairs'] == 1
    assert len(calls) == 2 and len(executed) == 1
    assert calls[1]['validation_error'] == '字段不在指标目录中'
    assert [e['status'] for e in result['trace'] if e['node'] == 'validate_sql'] == ['rejected', 'passed']


@pytest.mark.parametrize('sql', [
    'DELETE FROM v_content_summary',
    'SELECT * FROM user_info',
    'SELECT album_count FROM v_content_summary JOIN v_user_summary ON 1=1',
    'SELECT album_count FROM v_content_summary; DROP TABLE user_info',
    'SELECT SLEEP(10) FROM v_content_summary',
    'SELECT album_count FROM v_content_summary LIMIT 101',
])
def test_policy_violations_never_repair_or_execute(sql):
    calls = []
    async def generate(system, user):
        calls.append(user)
        return {'sql': sql}
    async def execute(sql):
        pytest.fail('Forbidden SQL reached executor')
    result = asyncio.run(build_query_graph(generate, execute).ainvoke(initial()))
    assert result['route'] == 'reject' and result['repairs'] == 0
    assert len(calls) == 1


def test_repair_budget_is_two():
    calls = []
    async def generate(system, user):
        calls.append(user)
        return {'sql': 'SELECT unknown FROM v_content_summary'}
    async def execute(sql):
        pytest.fail('Invalid SQL reached executor')
    result = asyncio.run(build_query_graph(generate, execute).ainvoke(initial()))
    assert result['route'] == 'reject' and result['repairs'] == 2 and len(calls) == 3


def test_database_unavailable_does_not_trigger_sql_repair():
    calls = []
    async def generate(system, user):
        calls.append(user)
        return {'sql': SQL}
    async def execute(sql):
        raise pymysql.OperationalError(2003, 'private connection details')
    with pytest.raises(HTTPException) as error:
        asyncio.run(build_query_graph(generate, execute).ainvoke(initial()))
    assert error.value.status_code == 502 and len(calls) == 1
    assert 'private' not in error.value.detail


def test_clarification_survives_new_graph_and_new_sqlite_connection(tmp_path):
    async def run():
        async def generate(system, user):
            return {'sql': SQL} if '用户补充' in json.loads(user)['question'] else {'clarification': '请确认统计专辑总量？'}
        async def execute(sql):
            return [{'album_count': 12}]
        path = str(tmp_path / 'checkpoints.sqlite')
        config = {'configurable': {'thread_id': 'isolated-query'}}
        async with AsyncSqliteSaver.from_conn_string(path) as saver:
            result = await build_query_graph(generate, execute, saver).ainvoke(initial(), config)
            assert result['__interrupt__'][0].value['question'] == '请确认统计专辑总量？'
        async with AsyncSqliteSaver.from_conn_string(path) as saver:
            result = await build_query_graph(generate, execute, saver).ainvoke(Command(resume='确认'), config)
            assert result['rows'] == [{'album_count': 12}] and result['clarifications'] == 1
    asyncio.run(run())


def test_clarification_cannot_loop_forever(tmp_path):
    async def run():
        async def generate(system, user):
            return {'clarification': '请补充口径'}
        async def execute(sql):
            pytest.fail('Ambiguous query reached executor')
        async with AsyncSqliteSaver.from_conn_string(str(tmp_path / 'checkpoint.sqlite')) as saver:
            graph = build_query_graph(generate, execute, saver)
            config = {'configurable': {'thread_id': 'query'}}
            await graph.ainvoke(initial(), config)
            result = await graph.ainvoke(Command(resume='仍不清楚'), config)
            assert result['route'] == 'reject'
    asyncio.run(run())


def test_run_owner_one_use_and_expiry(tmp_path):
    path = tmp_path / 'runs.sqlite'
    claim(path, 'one', '1')
    mark(path, 'one', 'pending')
    with pytest.raises(HTTPException) as error:
        claim(path, 'one', '2', resume=True)
    assert error.value.status_code == 404
    claim(path, 'one', '1', resume=True)
    with pytest.raises(HTTPException) as error:
        claim(path, 'one', '1', resume=True)
    assert error.value.status_code == 409
    mark(path, 'one', 'pending')
    with sqlite3.connect(path) as db:
        db.execute('UPDATE runs SET updated=0')
    with pytest.raises(HTTPException) as error:
        claim(path, 'one', '1', resume=True)
    assert error.value.status_code == 410


def test_assistant_graph_loops_with_tools_then_finishes():
    async def model(messages, index):
        if index == 0:
            return {'role': 'assistant', 'tool_calls': [{'id': 'one'}]}
        assert messages[-1]['role'] == 'tool'
        return {'role': 'assistant', 'content': '查询完成'}
    async def tools(calls):
        return [{'role': 'tool', 'tool_call_id': 'one', 'content': '真实结果'}]
    result = asyncio.run(build_assistant_graph(model, tools).ainvoke({'messages': [], 'round_index': 0, 'node_trace': []}))
    assert result['answer'] == '查询完成'
    assert result['node_trace'] == ['model', 'tools', 'guard', 'model']


def test_assistant_graph_stops_at_four_rounds():
    executed = []
    async def model(messages, index):
        return {'role': 'assistant', 'tool_calls': [{'id': str(index)}]}
    async def tools(calls):
        executed.append(calls)
        return []
    with pytest.raises(HTTPException) as error:
        asyncio.run(build_assistant_graph(model, tools).ainvoke({'messages': [], 'round_index': 0, 'node_trace': []}))
    assert error.value.status_code == 502 and len(executed) == 4


def test_query_api_restores_pending_run_and_rejects_other_owner_or_replay(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from listening import service
    from listening_common import require_service
    monkeypatch.setattr(service, 'RUNTIME', tmp_path)
    async def generate(cfg, system, user):
        return {'sql': SQL} if '用户补充' in json.loads(user)['question'] else {'clarification': '统计专辑总量吗？'}
    monkeypatch.setattr(service, 'model_json', generate)
    monkeypatch.setattr(service, 'execute_readonly', lambda sql: [{'album_count': 12}])
    service.app.dependency_overrides[require_service] = lambda: None
    try:
        with TestClient(service.app) as client:
            response = client.post('/query', json={'question': '统计总量', 'actor_id': '1'})
            assert response.status_code == 200
            body = response.json()
            assert body['status'] == 'clarification_required'
            run_id = body['request_id']
        # New client / saver connection simulate a fresh request after service reconstruction.
        with TestClient(service.app) as client:
            response = client.post('/query', json={'question': '确认', 'actor_id': '2', 'run_id': run_id})
            assert response.status_code == 404
            response = client.post('/query', json={'question': '确认', 'actor_id': '1', 'run_id': run_id})
            assert response.status_code == 200 and response.json()['row_count'] == 1
            assert response.json()['orchestrator'] == 'langgraph'
            response = client.post('/query', json={'question': '确认', 'actor_id': '1', 'run_id': run_id})
            assert response.status_code == 409
    finally:
        service.app.dependency_overrides.clear()


def test_admin_resume_rechecks_permissions_and_uses_authenticated_actor(tmp_path):
    from test_listening import make_client
    import httpx
    rid = str(uuid.uuid4())
    calls = []
    def backend(request):
        if request.url.path.endswith('/me'):
            return httpx.Response(200, json={'code': 200, 'data': {'id': '42', 'permissions':
                ['operations:read'] if request.headers['admin-token'] == 'allowed' else []}})
        calls.append(json.loads(request.content))
        return httpx.Response(200, json={'rows': []})
    with make_client(tmp_path, backend, listening_operations_url='http://ops', listening_service_key='test') as client:
        body = {'text': '补充口径', 'run_id': rid}
        assert client.post('/api/admin/ops/query', headers={'admin-token': 'revoked'}, json=body).status_code == 403
        assert not calls
        assert client.post('/api/admin/ops/query', headers={'admin-token': 'allowed'}, json={**body, 'run_id': []}).status_code == 422
        assert client.post('/api/admin/ops/query', headers={'admin-token': 'allowed'}, json=body).status_code == 200
    assert calls == [{'question': '补充口径', 'actor_id': '42', 'run_id': rid}]
