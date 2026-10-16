"""仅在本项目独立 MySQL 中安装统计视图与专用只读账号。"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _bootstrap import ROOT
import os
import secrets
import hashlib
import base64

import pymysql

runtime = ROOT / ".runtime"
runtime.mkdir(exist_ok=True)
for filename in ["reader-password", "service-key", "admin-password", "payment-callback-key"]:
    path = runtime / filename
    if not path.exists():
        path.write_text(secrets.token_urlsafe(32), encoding="utf-8")
password = (runtime / "reader-password").read_text(encoding="utf-8").strip()
files = ["03-operations.sql", "04-after-sales.sql", "06-access.sql", "08-local-payments.sql"]
if os.environ.get("LISTENING_DEMO_LOGIN", "false").lower() == "true":
    files.extend(["05-demo-orders.sql", "07-demo-content.sql"])
connection = pymysql.connect(host="127.0.0.1", port=int(os.environ.get("LISTENING_DB_PORT", "24316")), user="root",
    password=os.environ.get("LISTENING_DB_PASSWORD", "listening_local_only"),
    charset="utf8mb4", autocommit=True, connect_timeout=5)
with connection:
    with connection.cursor() as cursor:
        cursor.execute('CREATE DATABASE IF NOT EXISTS listening_ops CHARACTER SET utf8mb4')
        cursor.execute('CREATE TABLE IF NOT EXISTS listening_ops.schema_migration(filename varchar(100) PRIMARY KEY, checksum char(64) NOT NULL, applied_at timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP)')
        for filename in files:
            source = (ROOT / "sql" / filename).read_text(encoding="utf-8")
            checksum = hashlib.sha256(source.encode()).hexdigest()
            cursor.execute('SELECT checksum FROM listening_ops.schema_migration WHERE filename=%s',(filename,))
            previous = cursor.fetchone()
            if previous:
                if previous[0] != checksum:
                    raise RuntimeError(f'已执行的迁移 {filename} 被修改，请保留原文件并新增迁移')
                continue
            sql = source.replace("__READER_PASSWORD__", password)
            for statement in sql.split(";"):
                if statement.strip():
                    cursor.execute(statement)
            cursor.execute('INSERT INTO listening_ops.schema_migration(filename,checksum) VALUES(%s,%s)',(filename,checksum))
        for column, definition in {"review_note": "varchar(500) NULL", "reviewer_id": "bigint NULL", "reviewed_at": "datetime(6) NULL"}.items():
            cursor.execute("SELECT COUNT(*) FROM information_schema.columns WHERE table_schema='tingshu_order' AND table_name='after_sales_request' AND column_name=%s", (column,))
            if cursor.fetchone()[0] == 0:
                cursor.execute(f"ALTER TABLE tingshu_order.after_sales_request ADD COLUMN {column} {definition}")
        cursor.execute("SELECT COUNT(*) FROM information_schema.columns WHERE table_schema='tingshu_order' AND table_name='after_sales_event' AND column_name='actor_id'")
        if cursor.fetchone()[0] == 0:
            cursor.execute("ALTER TABLE tingshu_order.after_sales_event ADD COLUMN actor_id bigint NULL")
        # 本地初始管理员只创建一次；后续启动不恢复被撤销的用户角色或重置密码。
        if os.environ.get("LISTENING_DEMO_LOGIN", "false").lower() == "true":
            cursor.execute("INSERT IGNORE INTO tingshu_user.user_info(id,wx_open_id,nickname,status) VALUES(900010,'local-demo-admin-900010','本地管理员','1')")
            salt = secrets.token_bytes(16)
            encoded = "pbkdf2-sha256$600000$" + base64.b64encode(salt).decode() + "$" + base64.b64encode(hashlib.pbkdf2_hmac("sha256", (runtime / "admin-password").read_text(encoding="utf-8").strip().encode(), salt, 600000)).decode()
            cursor.execute("INSERT IGNORE INTO tingshu_user.access_account(username,user_id,password_hash) VALUES('admin',900010,%s)", (encoded,))
            if cursor.rowcount == 1:
                cursor.execute("INSERT IGNORE INTO tingshu_user.access_user_role VALUES(900010,'administrator')")
print("已安装统计视图、只读账号与售后表；演示订单仅在本地演示开关开启时补充，课程记录保留。")
print("本地管理账号：admin；初始密码位于 .runtime/admin-password，不在日志中显示。")
