import asyncio
import json
import sqlite3
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pymysql
from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel, Field

from listening_common import RUNTIME, ServiceSettings, model_json, private_value, require_service
from .catalog import CATALOG, SYSTEM
from .guard import UnsafeSQL, validate_sql
from .graph import build_query_graph
from .runs import claim, mark
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.types import Command

cfg = ServiceSettings()
app = FastAPI(title="听见 · 运营问数")
from request_trace import RequestTraceMiddleware
app.add_middleware(RequestTraceMiddleware,service='operations',rate_limit=60)


class Query(BaseModel):
    question: str = Field(min_length=1, max_length=1000)
    actor_id: str = Field(pattern=r"^\d{1,20}$")
    run_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$")


def audit(request_id: str, actor: str, question: str, sql: str, status: str, count: int):
    RUNTIME.mkdir(exist_ok=True)
    with sqlite3.connect(RUNTIME / "operations-audit.sqlite") as db:
        db.execute("CREATE TABLE IF NOT EXISTS queries(id TEXT PRIMARY KEY, actor TEXT, question TEXT, sql TEXT, status TEXT, row_count INTEGER, created_at TEXT)")
        db.execute("INSERT INTO queries VALUES(?,?,?,?,?,?,?)", (request_id, actor, question, sql,
            status, count, datetime.now(timezone.utc).isoformat()))


def execute_readonly(sql: str) -> list[dict]:
    # 执行前再次校验，避免未来绕过生成步骤的代码路径执行不安全 SQL。
    sql, _ = validate_sql(sql)
    password = cfg.listening_reader_password or private_value("LISTENING_READER_PASSWORD", "reader-password")
    connection = pymysql.connect(host=cfg.listening_db_host, port=cfg.listening_db_port,
        user=cfg.listening_reader_user, password=password, database=cfg.listening_ops_database, charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor, connect_timeout=3, read_timeout=5, write_timeout=3)
    with connection:
        with connection.cursor() as cursor:
            cursor.execute("SET time_zone = '+08:00'")
            cursor.execute("SET SESSION MAX_EXECUTION_TIME=3000")
            cursor.execute("START TRANSACTION READ ONLY")
            cursor.execute(sql)
            rows = cursor.fetchmany(101)
        connection.rollback()
    if len(rows) > 100:
        raise UnsafeSQL("结果超过行数上限")
    return [{k: str(v) if isinstance(v, (Decimal, date, datetime)) else v for k, v in row.items()} for row in rows]


@app.get("/health")
def health():
    return {"ok": True, "mode": "readonly-nl2sql", "orchestrator": "langgraph",
            "views": len(CATALOG), "max_rows": 100, "max_repairs": 2}


@app.get("/catalog", dependencies=[Depends(require_service)])
def catalog():
    return CATALOG


@app.post("/query", dependencies=[Depends(require_service)])
async def query(req: Query):
    request_id = req.run_id or str(uuid.uuid4())
    registry = RUNTIME / "operations-runs.sqlite"
    claim(registry, request_id, req.actor_id, resume=bool(req.run_id))
    state = {}
    try:
        async def generate(system, user):
            return await model_json(cfg, system, user)

        async def execute(sql):
            return await asyncio.to_thread(execute_readonly, sql)

        async with AsyncSqliteSaver.from_conn_string(str(RUNTIME / "operations-checkpoints.sqlite")) as saver:
            from .metadata import recall_metadata
            async def retrieve(question):
                return await recall_metadata(question, cfg)
            graph = build_query_graph(generate, execute, saver, retrieve=retrieve if cfg.listening_es_enabled else None)
            config = {"configurable": {"thread_id": request_id}, "recursion_limit": 24}
            initial = Command(resume=req.question) if req.run_id else {
                "question": req.question, "actor_id": req.actor_id, "request_id": request_id,
                "repairs": 0, "clarifications": 0, "trace": []}
            state = await graph.ainvoke(initial, config)
        if state.get("__interrupt__"):
            mark(registry, request_id, "pending")
            return {"status": "clarification_required", "request_id": request_id,
                    "clarification": state["__interrupt__"][0].value["question"],
                    "trace": state.get("trace", []), "orchestrator": "langgraph"}
        sql = state.get("sql", "")
        if state.get("route") == "reject":
            audit(request_id, req.actor_id, state["question"], sql, "rejected", 0)
            mark(registry, request_id, "rejected")
            raise HTTPException(422, state["error"])
        rows, view = state["rows"], state["view"]
        audit(request_id, req.actor_id, state["question"], sql, "completed", len(rows))
        mark(registry, request_id, "completed")
        return {"request_id": request_id, "sql": sql, "view": view, "rows": rows,
                "columns": list(rows[0]) if rows else [], "row_count": len(rows),
                "definition": CATALOG[view]["description"], "labels": CATALOG[view]["columns"],
                "mode": "readonly-nl2sql", "status": "completed", "orchestrator": "langgraph",
                "repairs": state.get("repairs", 0), "trace": state.get("trace", []),
                "data_source": "平台初始化数据（排除本地演示账号）"}
    except BaseException:
        mark(registry, request_id, "failed")
        raise
