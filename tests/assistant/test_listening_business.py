import json
import httpx
import pytest
from atguigu.listening.app import TOOLS
from test_listening import make_client

REQUEST_ID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
ORDER = {"id": "1", "orderNo": "demo-1", "title": "演示订单", "statusLabel": "已支付", "amount": "29.90"}


def upstream(request):
    if request.url.path.endswith("/me"):
        return httpx.Response(200, json={"code": 200, "data": {"id": 42}})
    assert request.headers["token"] == "owner-token"
    assert not request.url.query
    if request.url.path.endswith("/orders"):
        return httpx.Response(200, json={"code": 200, "data": [ORDER]})
    if request.url.path.endswith("/after-sales"):
        return httpx.Response(200, json={"code": 200, "data": []})
    if request.url.path.endswith("/prepare"):
        assert json.loads(request.content) == {"orderId": "1", "reason": "误购这个专辑"}
        return httpx.Response(200, json={"code": 200, "data": {"id": REQUEST_ID, "status": "DRAFT"}})
    if request.url.path.endswith("/confirm"):
        assert json.loads(request.content) == {"confirmed": True}
        return httpx.Response(200, json={"code": 200, "data": {"id": REQUEST_ID, "status": "SUBMITTED"}})
    if request.url.path.endswith("/withdraw"):
        return httpx.Response(404, json={"detail": "售后申请不存在"})
    raise AssertionError(str(request.url))


def test_orders_and_draft_forward_only_authenticated_token(tmp_path):
    with make_client(tmp_path, upstream, listening_order_url="http://order") as client:
        assert client.get("/api/business/orders").status_code == 401
        headers = {"token": "owner-token"}
        assert client.get("/api/business/orders", headers=headers).json()["records"][0]["amount"] == "29.90"
        response = client.post("/api/business/after-sales/prepare", headers=headers, json={"orderId": "1", "reason": "误购这个专辑"})
        assert response.json()["status"] == "DRAFT"
        assert client.post(f"/api/business/after-sales/{REQUEST_ID}/confirm", headers=headers, json={"confirmed": True}).json()["status"] == "SUBMITTED"
        assert client.post(f"/api/business/after-sales/{REQUEST_ID}/withdraw", headers=headers).status_code == 404


@pytest.mark.parametrize("payload", [{}, {"confirmed": False}, {"confirmed": 1}, {"confirmed": "true"}, {"confirmed": True, "userId": 43}])
def test_confirmation_requires_literal_true_and_no_extra_fields(tmp_path, payload):
    with make_client(tmp_path, upstream, listening_order_url="http://order") as client:
        assert client.post(f"/api/business/after-sales/{REQUEST_ID}/confirm", headers={"token": "owner-token"}, json=payload).status_code == 422


@pytest.mark.parametrize("extra", [{"userId": 43}, {"amount": "1.00"}, {"status": "SUBMITTED"}])
def test_client_cannot_override_owner_amount_or_state(tmp_path, extra):
    with make_client(tmp_path, upstream, listening_order_url="http://order") as client:
        assert client.post("/api/business/after-sales/prepare", headers={"token": "owner-token"}, json={"orderId": "1", "reason": "误购这个专辑", **extra}).status_code == 422


def test_model_cannot_submit_after_sales_and_cannot_claim_refund_success(tmp_path):
    assert {t["function"]["name"] for t in TOOLS}.isdisjoint({"confirm_after_sales", "withdraw_after_sales", "refund", "prepare_after_sales"})
    def model(request):
        if request.url.path.endswith("/chat/completions"):
            body = json.loads(request.content)
            if body["messages"][-1]["role"] == "tool":
                return httpx.Response(200, json={"choices": [{"message": {"role": "assistant", "content": "退款已到账。"}}]})
            return httpx.Response(200, json={"choices": [{"message": {"role": "assistant", "tool_calls": [{"id": "1", "type": "function", "function": {"name": "get_orders", "arguments": "{}"}}]}}]})
        return upstream(request)
    with make_client(tmp_path, model, listening_order_url="http://order", listening_use_llm=True, llm_api_key="test") as client:
        data = client.post("/api/assistant/chat", headers={"token": "owner-token"}, json={"text": "帮我退款"}).json()
        assert "29.90" in data["text"]
        assert "退款已到账" not in data["text"]
        assert "待人工审核" in data["text"]


def test_unavailable_business_service_does_not_fake_success(tmp_path):
    def failed(request):
        if request.url.path.endswith("/me"):
            return upstream(request)
        return httpx.Response(503)
    with make_client(tmp_path, failed, listening_order_url="http://order") as client:
        assert client.get("/api/business/orders", headers={"token": "owner-token"}).status_code == 502
