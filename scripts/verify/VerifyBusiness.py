"""第三阶段真实服务验证：仅操作 900001 的演示订单和本次测试申请，不执行支付退款。"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _bootstrap import ROOT
import json
import os
import socket
import uuid
from concurrent.futures import ThreadPoolExecutor

import httpx
import pymysql
from verification_db import business_connection

BASE = "http://127.0.0.1:29183"
JAVA = "http://127.0.0.1:19204/api/order/assistant"
report = {"passed": False}


def redis_command(*args):
    # 本地隔离 Redis：临时身份仅用于所有权拒绝测试，不输出或保存令牌。
    encoded = [str(a).encode("utf-8") for a in args]
    request = b"*" + str(len(encoded)).encode() + b"\r\n" + b"".join(b"$" + str(len(a)).encode() + b"\r\n" + a + b"\r\n" for a in encoded)
    with socket.create_connection(("127.0.0.1", 17389), timeout=5) as connection:
        connection.sendall(request)
        stream = connection.makefile("rb")
        header = stream.readline()
        if header.startswith(b"$"):
            length = int(header[1:])
            if length == -1:
                return None
            value = stream.read(length)
            assert stream.read(2) == b"\r\n"
            return value
        assert header[:1] in {b"+", b":"}, "Redis 命令失败"
        return header[1:].strip()


db = business_connection(database="tingshu_order", charset="utf8mb4", autocommit=True, cursorclass=pymysql.cursors.DictCursor)
other_token = "business-test-" + str(uuid.uuid4())
try:
    with httpx.Client(base_url=BASE, timeout=120, trust_env=False) as client:
        report["health"] = client.get("/health").raise_for_status().json()
        token = client.post("/api/local/login").raise_for_status().json()["token"]
        headers = {"token": token}
        assert client.get("/api/business/orders").status_code == 401
        assert client.get(JAVA + "/orders").json()["code"] == 208
        client.headers.update(headers)
        orders = client.get("/api/business/orders").raise_for_status().json()["records"]
        assert len(orders) == 2 and all(row["demo"] for row in orders)
        assert {row["amount"] for row in orders} == {"29.90", "20.00"}
        assert client.post("/api/business/after-sales/prepare", json={"orderId": "900002", "reason": "联调演示：误购会员"}).status_code == 409
        assert client.post("/api/business/after-sales/prepare", json={"orderId": "1", "reason": "联调演示：错误订单"}).status_code == 404
        assert client.post(JAVA + "/after-sales/prepare", json={"orderId": "900001", "reason": "联调演示：误购专辑", "userId": 15}).status_code == 422
        # 重跑时仅撤回演示账号的活跃申请，保留全部历史。
        for row in client.get("/api/business/after-sales").json()["records"]:
            if row["status"] in {"DRAFT", "SUBMITTED"}:
                client.post(f"/api/business/after-sales/{row['id']}/withdraw").raise_for_status()
        payload = {"orderId": "900001", "reason": "联调演示：误购此专辑，希望申请售后"}
        def post_parallel(path, body):
            with httpx.Client(base_url=BASE, headers=headers, timeout=30, trust_env=False) as parallel:
                return parallel.post(path, json=body).raise_for_status().json()
        with ThreadPoolExecutor(max_workers=6) as workers:
            drafts = list(workers.map(lambda _: post_parallel("/api/business/after-sales/prepare", payload), range(6)))
        draft = drafts[0]
        assert len({row["id"] for row in drafts}) == 1 and draft["status"] == "DRAFT"
        assert draft["submittedAt"] is None
        with db.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) AS n FROM after_sales_event WHERE request_id=%s AND event_type='PREPARED'", (draft["id"],))
            assert cursor.fetchone()["n"] == 1
        report["concurrent_prepare_reuses_one_draft"] = True

        raw = redis_command("GET", "user:login:" + token)
        auth = json.loads(raw)
        if isinstance(auth["id"], list):
            auth["id"][-1] = 15
        else:
            auth["id"] = 15
        redis_command("SET", "user:login:" + other_token, json.dumps(auth, ensure_ascii=False), "EX", 120)
        with httpx.Client(headers={"token": other_token}, timeout=30, trust_env=False) as other:
            assert other.post(JAVA + f"/after-sales/{draft['id']}/confirm", json={"confirmed": True}).status_code == 404
            assert other.post(JAVA + f"/after-sales/{draft['id']}/withdraw").status_code == 404
        report["foreign_user_confirm_and_withdraw_denied"] = True

        assert client.post(f"/api/business/after-sales/{draft['id']}/confirm", json={"confirmed": False}).status_code == 422
        assert client.post(f"/api/business/after-sales/{draft['id']}/confirm", json={"confirmed": True, "amount": "0.01"}).status_code == 422
        with db.cursor() as cursor:
            cursor.execute("UPDATE after_sales_request SET expires_at=DATE_SUB(UTC_TIMESTAMP(),INTERVAL 1 DAY) WHERE id=%s AND user_id=900001 AND status='DRAFT'", (draft["id"],))
        assert client.post(f"/api/business/after-sales/{draft['id']}/confirm", json={"confirmed": True}).status_code == 410
        report["expired_confirmation_denied"] = True
        new_draft = client.post("/api/business/after-sales/prepare", json=payload).raise_for_status().json()
        assert new_draft["id"] != draft["id"]
        with ThreadPoolExecutor(max_workers=6) as workers:
            confirmations = list(workers.map(lambda _: post_parallel(f"/api/business/after-sales/{new_draft['id']}/confirm", {"confirmed": True}), range(6)))
        assert len({row["id"] for row in confirmations}) == 1
        assert all(row["status"] == "SUBMITTED" for row in confirmations)
        with db.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) AS n FROM after_sales_event WHERE request_id=%s AND event_type='CONFIRMED'", (new_draft["id"],))
            assert cursor.fetchone()["n"] == 1
        report["concurrent_confirmation_records_one_event"] = True
        report["submitted_request_id"] = new_draft["id"]
        for question, tool in [("我的订单和支付状态是什么？", "get_orders"), ("我的售后申请记录和当前状态是什么？", "get_after_sales")]:
            reply = client.post("/api/assistant/chat", json={"text": question}).raise_for_status().json()
            assert any(trace["tool"] == tool for trace in reply["trace"])
            assert "退款已到账" not in reply["text"]
            report[tool] = {"text": reply["text"], "trace": reply["trace"]}
        path = f"/api/business/after-sales/{new_draft['id']}/withdraw"
        assert client.post(path).raise_for_status().json()["status"] == "WITHDRAWN"
        assert client.post(path).raise_for_status().json()["status"] == "WITHDRAWN"
        assert client.post(f"/api/business/after-sales/{new_draft['id']}/confirm", json={"confirmed": True}).status_code == 409
        with db.cursor() as cursor:
            cursor.execute("SELECT order_status,order_amount FROM order_info WHERE id=900001 AND user_id=900001")
            row = cursor.fetchone()
            assert row["order_status"] == "0902" and str(row["order_amount"]) == "29.90"
            cursor.execute("SELECT COUNT(*) AS n FROM after_sales_event WHERE request_id=%s AND event_type='WITHDRAWN'", (new_draft["id"],))
            assert cursor.fetchone()["n"] == 1
        report["withdrawal_idempotent_and_order_unchanged"] = True
finally:
    redis_command("DEL", "user:login:" + other_token)
    db.close()
report["passed"] = True
ROOT.joinpath(".runtime", "business-v3.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps({key: value for key, value in report.items() if key not in {"get_orders", "get_after_sales"}}, ensure_ascii=False, indent=2))
