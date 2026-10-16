"""Owner-bound, one-use clarification handles with persistent expiry and leases."""
import sqlite3
import time
from fastapi import HTTPException


def claim(path, run_id, actor, resume=False):
    path.parent.mkdir(parents=True, exist_ok=True)
    now = time.time()
    with sqlite3.connect(path, timeout=5) as db:
        db.execute('CREATE TABLE IF NOT EXISTS runs(id TEXT PRIMARY KEY, actor TEXT, status TEXT, updated REAL)')
        db.execute('BEGIN IMMEDIATE')
        if not resume:
            db.execute('INSERT INTO runs VALUES(?,?,?,?)', (run_id, actor, 'running', now))
            return
        row = db.execute('SELECT actor,status,updated FROM runs WHERE id=?', (run_id,)).fetchone()
        if not row or row[0] != actor:
            raise HTTPException(404, '查询任务不存在')
        if now - row[2] > 600:
            raise HTTPException(410, '查询任务已过期，请重新提问')
        if row[1] != 'pending':
            raise HTTPException(409, '任务已完成或正在处理，请勿重复提交')
        db.execute('UPDATE runs SET status=?,updated=? WHERE id=?', ('running', now, run_id))


def mark(path, run_id, status):
    with sqlite3.connect(path, timeout=5) as db:
        db.execute('UPDATE runs SET status=?,updated=? WHERE id=?', (status, time.time(), run_id))
