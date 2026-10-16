import json
from pathlib import Path
import httpx
import pytest
from fastapi.testclient import TestClient
from atguigu.listening.app import Settings, create_app, membership


def make_client(tmp_path, handler=None, **options):
    docs = tmp_path / "docs"
    docs.mkdir(exist_ok=True)
    (docs / "三体简介.md").write_text("# 三体简介\n## 内容正文\n三体是刘慈欣的科幻小说，涉及文明与宇宙。\n## 作者介绍\n刘慈欣。", encoding="utf-8")
    def default(request):
        token = request.headers.get("token")
        owner = 2 if token == "other-user" else 1
        if token == "expired":
            return httpx.Response(200, json={"code": 208})
        if request.url.path.endswith("/me"):
            return httpx.Response(200, json={"code": 200, "data": {"id": owner, "nickname": "test", "isVip": 1, "vipExpireTime": "2027-01-01"}})
        if request.url.path.endswith("/progress"):
            return httpx.Response(200, json={"code": 200, "data": [{"trackId": 9, "breakSecond": 125}]})
        if request.url.path.endswith("/permissions"):
            return httpx.Response(200, json={"code": 200, "data": {"permissions": []}})
        raise AssertionError(str(request.url))
    options.setdefault('listening_model_settings_file', str(tmp_path / 'model-settings.json'))
    cfg = Settings(_env_file=None, listening_docs=str(docs), listening_history_db=str(tmp_path / "history.db"), **options)
    return TestClient(create_app(cfg, httpx.MockTransport(handler or default)))


def test_requires_login(tmp_path):
    with make_client(tmp_path) as client:
        assert client.post("/api/assistant/chat", json={"text": "我听到哪里了"}).status_code == 401


def test_local_mode_cannot_read_vm_personal_data(tmp_path,monkeypatch):
    from personal_knowledge import repository
    def forbidden(*args,**kwargs):raise AssertionError('Local identity reached VM personal data')
    monkeypatch.setattr(repository,'items',forbidden)
    with make_client(tmp_path,listening_infrastructure='local') as client:
        response=client.post('/api/assistant/chat',headers={'token':'valid'},json={'text':'我的笔记','knowledge_scope':'personal','knowledge_space_id':'12345678-1234-4234-8234-123456789abc'})
        assert response.status_code==503


def test_progress_and_history_persist_with_sources(tmp_path):
    with make_client(tmp_path) as client:
        response = client.post("/api/assistant/chat", headers={"token": "valid"}, json={"text": "我上次听到哪里了"})
        assert response.status_code == 200
        assert "2 分 5 秒" in response.json()["text"]
        sid = response.json()["session_id"]
        answer = client.post("/api/assistant/chat", headers={"token": "valid"}, json={"text": "三体讲什么", "session_id": sid}).json()
        assert answer["sources"][0]["source"] == "三体简介.md"
    with make_client(tmp_path) as client:
        rows = client.get("/api/history/" + sid, headers={"token": "valid"}).json()["messages"]
        assert len(rows) == 4


def test_session_cannot_be_read_or_written_by_other_user(tmp_path):
    with make_client(tmp_path) as client:
        sid = client.post("/api/assistant/chat", headers={"token": "valid"}, json={"text": "三体"}).json()["session_id"]
        assert client.get("/api/history/" + sid, headers={"token": "other-user"}).status_code == 404
        assert client.post("/api/assistant/chat", headers={"token": "other-user"}, json={"text": "继续", "session_id": sid}).status_code == 404


def test_expired_token_and_demo_disabled(tmp_path):
    with make_client(tmp_path) as client:
        assert client.get("/api/me", headers={"token": "expired"}).status_code == 401
        assert client.post("/api/local/login").status_code == 404


def test_knowledge_upstream_errors_are_not_fake_success(tmp_path):
    calls = []
    def upstream(request):
        if request.url.path.endswith("/me"):
            return httpx.Response(200, json={"code": 200, "data": {"id": 1}})
        assert request.url.path == "/query"
        assert request.headers["x-listening-key"] == "internal-test"
        calls.append(request)
        return httpx.Response(503)
    with make_client(tmp_path, upstream, listening_knowledge_url="http://knowledge", listening_service_key="internal-test") as client:
        assert client.post("/api/assistant/chat", headers={"token": "valid"}, json={"text": "三体"}).status_code == 502
    assert len(calls) == 1


def test_actual_model_tool_loop_forwards_token_and_never_user_id(tmp_path):
    calls = []
    def upstream(request):
        calls.append(request)
        if request.url.path.endswith("/me"):
            return httpx.Response(200, json={"code": 200, "data": {"id": 1}})
        if request.url.path.endswith("/progress"):
            assert request.headers["token"] == "valid"
            assert not request.url.query
            return httpx.Response(200, json={"code": 200, "data": [{"trackId": 9, "breakSecond": 125}]})
        body = json.loads(request.content)
        if body["messages"][-1]["role"] == "tool":
            assert body["tool_choice"] == "auto"
            assert "125" in body["messages"][-1]["content"]
            return httpx.Response(200, json={"choices": [{"message": {"role": "assistant", "content": "你听到了三体第9集。"}}]})
        assert body["tool_choice"] == "required"
        return httpx.Response(200, json={"choices": [{"message": {"role": "assistant", "content": None, "tool_calls": [{"id": "call-1", "type": "function", "function": {"name": "get_progress", "arguments": "{}"}}]}}]})
    with make_client(tmp_path, upstream, listening_use_llm=True, llm_api_key="test-key") as client:
        data = client.post("/api/assistant/chat", headers={"token": "valid"}, json={"text": "收听进度"}).json()
        assert data["mode"] == "llm-tools"
        assert data["trace"][0]["tool"] == "get_progress"
        assert "2 分 5 秒" in data["text"]
        assert "三体" not in data["text"]
        assert "第9集" not in data["text"]
        assert "书名和集数" in data["text"]


def test_model_cannot_request_another_user(tmp_path):
    def upstream(request):
        if request.url.path.endswith("/me"):
            return httpx.Response(200, json={"code": 200, "data": {"id": 1}})
        return httpx.Response(200, json={"choices": [{"message": {"role": "assistant", "content": None, "tool_calls": [{"id": "1", "type": "function", "function": {"name": "get_progress", "arguments": '{"userId": 999}'}}]}}]})
    with make_client(tmp_path, upstream, listening_use_llm=True, llm_api_key="test-key") as client:
        assert client.post("/api/assistant/chat", headers={"token": "valid"}, json={"text": "查询别人"}).status_code == 422


def test_membership_checks_expiry_and_displays_shanghai_time():
    expired = membership({"isVip": 1, "vipExpireTime": "2020-01-01T16:00:00.000+00:00"})
    assert expired["membershipStatus"] == "expired"
    assert expired["vipExpireTimeLocal"] == "2020-01-02 00:00:00"
    assert membership({"isVip": 1, "vipExpireTime": "bad-date"})["membershipStatus"] == "unknown"
    assert membership({"isVip": 0})["membershipStatus"] == "ordinary"


def test_model_without_a_tool_result_is_not_accepted(tmp_path):
    def upstream(request):
        if request.url.path.endswith("/me"):
            return httpx.Response(200, json={"code": 200, "data": {"id": 1}})
        return httpx.Response(200, json={"choices": [{"message": {"role": "assistant", "content": "未经检索的答案"}}]})
    with make_client(tmp_path, upstream, listening_use_llm=True, llm_api_key="test-key") as client:
        response = client.post("/api/assistant/chat", headers={"token": "valid"}, json={"text": "三体讲什么"})
        assert response.status_code == 502
        assert "未执行查询工具" in response.json()["detail"]


def test_operations_permission_is_checked_before_calling_service(tmp_path):
    with make_client(tmp_path, listening_operations_url="http://operations") as client:
        assert client.post("/api/ops/query", headers={"token": "valid"}, json={"text": "用户总数"}).status_code == 403


def test_operations_identity_and_internal_auth_are_bound_by_server(tmp_path):
    def upstream(request):
        if request.url.path.endswith("/me"):
            return httpx.Response(200, json={"code": 200, "data": {"id": 1}})
        if request.url.path.endswith("/permissions"):
            return httpx.Response(200, json={"code": 200, "data": {"permissions": ["operations:read"]}})
        body = json.loads(request.content)
        assert body["actor_id"] == "1"
        assert request.headers["x-listening-key"] == "internal-test"
        return httpx.Response(200, json={"rows": [{"user_count": 10}], "sql": "SELECT user_count FROM v_user_summary LIMIT 100"})
    with make_client(tmp_path, upstream, listening_operations_url="http://operations", listening_service_key="internal-test") as client:
        response = client.post("/api/ops/query", headers={"token": "valid"}, json={"text": "用户总数", "actor_id": "2"})
        assert response.status_code == 200
        assert response.json()["rows"][0]["user_count"] == 10


def test_rag_evidence_answer_is_kept_without_model_rewriting(tmp_path):
    def upstream(request):
        if request.url.path.endswith("/me"):
            return httpx.Response(200, json={"code": 200, "data": {"id": 1}})
        if request.url.path == "/query":
            assert request.headers["x-listening-key"] == "internal-test"
            return httpx.Response(200, json={"answer": "可核验的资料原文 [K1]", "grounded": True, "sources": [{"chunk_id": "known", "quote": "可核验的资料原文"}]})
        body = json.loads(request.content)
        message = {"role": "assistant", "content": "模型编造的剧情"} if body["messages"][-1]["role"] == "tool" else {"role": "assistant", "tool_calls": [{"id": "search", "type": "function", "function": {"name": "search_knowledge", "arguments": '{"query":"三体"}'}}]}
        return httpx.Response(200, json={"choices": [{"message": message}]})
    with make_client(tmp_path, upstream, listening_use_llm=True, llm_api_key="test-key", listening_knowledge_url="http://knowledge", listening_service_key="internal-test") as client:
        response = client.post("/api/assistant/chat", headers={"token": "valid"}, json={"text": "三体"})
        assert response.json()["text"] == "可核验的资料原文 [K1]"


def test_multiple_rag_calls_keep_both_answers_and_unique_citations(tmp_path):
    def upstream(request):
        if request.url.path.endswith("/me"):
            return httpx.Response(200, json={"code": 200, "data": {"id": 1}})
        body = json.loads(request.content)
        if request.url.path == "/query":
            title = body["query"]
            return httpx.Response(200, json={"answer": title + "的原文 [K1]", "sources": [{"citation": "K1", "chunk_id": title, "quote": title + "的原文"}]})
        if body["messages"][-1]["role"] == "tool":
            message = {"role": "assistant", "content": "未经核验的比较"}
        else:
            message = {"role": "assistant", "tool_calls": [{"id": title, "type": "function", "function": {"name": "search_knowledge", "arguments": json.dumps({"query": title})}} for title in ["三体", "活着"]]}
        return httpx.Response(200, json={"choices": [{"message": message}]})
    with make_client(tmp_path, upstream, listening_use_llm=True, llm_api_key="test-key", listening_knowledge_url="http://knowledge", listening_service_key="internal-test") as client:
        body = client.post("/api/assistant/chat", headers={"token": "valid"}, json={"text": "比较三体和活着"}).json()
        assert "三体的原文 [K1]" in body["text"]
        assert "活着的原文 [K2]" in body["text"]
        assert [source["citation"] for source in body["sources"]] == ["K1", "K2"]
