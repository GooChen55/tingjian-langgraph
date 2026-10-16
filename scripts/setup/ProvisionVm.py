"""Provision only aillisten-dev resources on the shared VM.

Administrative credentials are read from the ignored runtime directory. Old SQL
files are rendered into isolated schemas, never changed in place. This script
does not install, stop, reconfigure or delete any existing shared service.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _bootstrap import ROOT

import argparse
import base64
import hashlib
import json
import re
import secrets

import httpx
import pymysql
import redis

from resource_scope import OWNER, SCOPE, SCHEMAS, remap_schemas, sql_statements

RUNTIME = ROOT / ".runtime"
PRIVATE = RUNTIME / "vm-app-private.json"


def app_config(host):
    if PRIVATE.exists():
        value = json.loads(PRIVATE.read_text(encoding="utf-8"))
        if value.get("owner") != OWNER or value.get("host") != host:
            raise ValueError("Existing VM credentials belong to another resource scope")
        for key in ("service_key", "payment_callback_secret"):
            if key not in value:
                value[key] = secrets.token_urlsafe(32)
        PRIVATE.write_text(json.dumps(value, indent=2), encoding="utf-8")
        return value
    value = {"owner": OWNER, "host": host,
             **{key: secrets.token_urlsafe(32) for key in
                ("mysql_password", "reader_password", "redis_password", "rabbit_password", "service_key", "payment_callback_secret")}}
    PRIVATE.write_text(json.dumps(value, indent=2), encoding="utf-8")
    return value


def provision_mysql(admin, cfg):
    with pymysql.connect(host=cfg["host"], user="root", password=admin["mysql_password"],
                         charset="utf8mb4", autocommit=True, connect_timeout=8) as db:
        with db.cursor() as cur:
            cur.execute("SHOW DATABASES")
            existing = {row[0] for row in cur.fetchall()}
            # Check every collision before the first mutation.
            for name in SCHEMAS.values():
                if name in existing:
                    cur.execute("SELECT COUNT(*) FROM information_schema.tables WHERE table_schema=%s AND table_name='_aillisten_owner'", (name,))
                    if cur.fetchone()[0] != 1:
                        raise RuntimeError("Refusing to adopt an existing unowned database: " + name)
                    cur.execute(f"SELECT owner FROM `{name}`._aillisten_owner")
                    if cur.fetchall() != ((OWNER,),):
                        raise RuntimeError("Database ownership mismatch: " + name)
            for user in (SCOPE.mysql_user, SCOPE.mysql_reader):
                cur.execute("SELECT COUNT(*) FROM mysql.user WHERE user=%s", (user,))
                if cur.fetchone()[0] and not set(SCHEMAS.values()).issubset(existing):
                    raise RuntimeError("Dedicated user name already exists without owned databases")
            for name in SCHEMAS.values():
                cur.execute(f"CREATE DATABASE IF NOT EXISTS `{name}` CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci")
                cur.execute(f"CREATE TABLE IF NOT EXISTS `{name}`._aillisten_owner(owner varchar(80) PRIMARY KEY)")
                cur.execute(f"INSERT IGNORE INTO `{name}`._aillisten_owner VALUES(%s)", (OWNER,))
            ops = SCOPE.schema("listening_ops")
            cur.execute(f"CREATE TABLE IF NOT EXISTS `{ops}`.schema_migration(filename varchar(100) PRIMARY KEY, checksum char(64) NOT NULL, applied_at timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP)")
            for file in sorted((ROOT / "sql").glob("*.sql")):
                original = file.read_text(encoding="utf-8-sig")
                checksum = hashlib.sha256((OWNER + "\n" + original).encode()).hexdigest()
                cur.execute(f"SELECT checksum FROM `{ops}`.schema_migration WHERE filename=%s", (file.name,))
                row = cur.fetchone()
                if row:
                    if row[0] != checksum:
                        raise RuntimeError("Applied migration changed: " + file.name)
                    continue
                count = 0
                for sql in sql_statements(remap_schemas(original)):
                    # Reader creation is handled below, with a unique username.
                    if re.match(r"^(CREATE USER|ALTER USER|REVOKE|GRANT)\b", sql, re.I):
                        continue
                    cur.execute(sql)
                    count += 1
                cur.execute(f"INSERT INTO `{ops}`.schema_migration(filename,checksum) VALUES(%s,%s)", (file.name, checksum))
                print(f"Installed isolated migration {file.name}: {count} statements", flush=True)
            order = SCOPE.schema("tingshu_order")
            for column, definition in {"review_note": "varchar(500) NULL", "reviewer_id": "bigint NULL", "reviewed_at": "datetime(6) NULL"}.items():
                cur.execute("SELECT COUNT(*) FROM information_schema.columns WHERE table_schema=%s AND table_name='after_sales_request' AND column_name=%s", (order, column))
                if not cur.fetchone()[0]:
                    cur.execute(f"ALTER TABLE `{order}`.after_sales_request ADD COLUMN {column} {definition}")
            cur.execute("SELECT COUNT(*) FROM information_schema.columns WHERE table_schema=%s AND table_name='after_sales_event' AND column_name='actor_id'", (order,))
            if not cur.fetchone()[0]:
                cur.execute(f"ALTER TABLE `{order}`.after_sales_event ADD COLUMN actor_id bigint NULL")
            userdb = SCOPE.schema("tingshu_user")
            password_file = RUNTIME / "admin-password"
            if not password_file.exists():
                password_file.write_text(secrets.token_urlsafe(32), encoding="utf-8")
            salt = secrets.token_bytes(16)
            encoded = "pbkdf2-sha256$600000$" + base64.b64encode(salt).decode() + "$" + base64.b64encode(hashlib.pbkdf2_hmac("sha256", password_file.read_text(encoding="utf-8-sig").strip().encode(), salt, 600000)).decode()
            cur.execute(f"INSERT IGNORE INTO `{userdb}`.user_info(id,wx_open_id,nickname,status) VALUES(900010,'local-demo-admin-900010','本地管理员','1')")
            cur.execute(f"INSERT IGNORE INTO `{userdb}`.access_account(username,user_id,password_hash) VALUES('admin',900010,%s)", (encoded,))
            if cur.rowcount:
                cur.execute(f"INSERT IGNORE INTO `{userdb}`.access_user_role VALUES(900010,'administrator')")
            for user, password in ((SCOPE.mysql_user, cfg["mysql_password"]), (SCOPE.mysql_reader, cfg["reader_password"])):
                cur.execute("CREATE USER IF NOT EXISTS %s@'%%' IDENTIFIED BY %s", (user, password))
                # Reconcile only these owned accounts. Never touch listening_reader.
                cur.execute("ALTER USER %s@'%%' IDENTIFIED BY %s", (user, password))
                cur.execute("REVOKE ALL PRIVILEGES, GRANT OPTION FROM %s@'%%'", (user,))
            for name in SCHEMAS.values():
                cur.execute(f"GRANT SELECT,INSERT,UPDATE,DELETE,CREATE,ALTER,INDEX,REFERENCES ON `{name}`.* TO %s@'%%'", (SCOPE.mysql_user,))
            from listening.catalog import CATALOG
            for view in CATALOG:
                cur.execute(f"GRANT SELECT ON `{ops}`.`{view}` TO %s@'%%'", (SCOPE.mysql_reader,))


def provision_redis(cfg):
    client = redis.Redis(host=cfg["host"], port=6379, socket_timeout=8, decode_responses=True)
    # Explicit commands: no FLUSH, CONFIG, ACL, KEYS, SCAN or arbitrary key access.
    commands = "ping select hello get mget set mset setnx setex psetex del unlink exists expire pexpire expireat pexpireat ttl pttl incr incrby decr decrby hget hgetall hset hdel hexists hincrby lpush rpush lrange lpop rpop llen sadd srem smembers sismember zadd zrem zrange zscore zcard multi exec discard watch unwatch eval evalsha script|load client|setname client|setinfo"
    client.execute_command("ACL", "SETUSER", SCOPE.redis_user, "reset", "on",
        ">" + cfg["redis_password"], "~" + SCOPE.redis_prefix + "*",
        "&" + SCOPE.redis_prefix + "*", "-@all", *["+" + v for v in commands.split()])
    limited = redis.Redis(host=cfg["host"], username=SCOPE.redis_user,
        password=cfg["redis_password"], socket_timeout=5, decode_responses=True)
    limited.set(SCOPE.redis_prefix + "provision-check", OWNER, ex=60)
    try:
        limited.get("aillisten-foreign-probe:no-read")
    except redis.exceptions.NoPermissionError:
        pass
    else:
        raise RuntimeError("Redis key boundary is not enforced")
    limited.delete(SCOPE.redis_prefix + "provision-check")
    # Shared Redis has no configured ACL file. Do not reconfigure it globally.
    acl_file = client.config_get("aclfile").get("aclfile")
    if acl_file:
        client.acl_save()
    return {"acl_persistent": bool(acl_file), "key_prefix": SCOPE.redis_prefix}


def provision_rabbit(admin, cfg):
    from urllib.parse import quote
    with httpx.Client(base_url=f"http://{cfg['host']}:15672", timeout=10, trust_env=False,
                      auth=(admin["rabbit_user"], admin["rabbit_password"])) as client:
        path = "/api/vhosts/" + quote(SCOPE.rabbit_vhost, safe="")
        response = client.get(path)
        if response.status_code == 404:
            response = client.put(path, json={"description": OWNER, "tags": ["aillisten"]})
            response.raise_for_status()
        else:
            response.raise_for_status()
            if response.json().get("description") != OWNER:
                raise RuntimeError("Rabbit vhost exists without project ownership")
        response = client.put("/api/users/" + SCOPE.rabbit_user,
                              json={"password": cfg["rabbit_password"], "tags": ""})
        response.raise_for_status()
        response = client.put("/api/permissions/" + quote(SCOPE.rabbit_vhost, safe="") + "/" + SCOPE.rabbit_user,
            json={"configure": r"^aillisten\.dev\..*$", "write": r"^(aillisten\.dev\..*|)$", "read": r"^aillisten\.dev\..*$"})
        response.raise_for_status()


def provision_nacos(cfg):
    with httpx.Client(base_url=f"http://{cfg['host']}:8848/nacos", timeout=10, trust_env=False) as client:
        response = client.get("/v1/console/namespaces")
        response.raise_for_status()
        matches = [v for v in response.json()["data"] if v["namespace"] == SCOPE.nacos_namespace]
        if matches:
            if matches[0].get("namespaceDesc") != OWNER:
                raise RuntimeError("Nacos namespace ownership mismatch")
        else:
            response = client.post("/v1/console/namespaces", data={
                "customNamespaceId": SCOPE.nacos_namespace, "namespaceName": SCOPE.nacos_namespace,
                "namespaceDesc": OWNER})
            response.raise_for_status()
            if response.json() is not True:
                raise RuntimeError("Nacos namespace creation failed")
        content = "listening:\n  infrastructure: vm\n  resource-owner: '" + OWNER + "'\n"
        response = client.post("/v1/cs/configs", data={"tenant": SCOPE.nacos_namespace,
            "group": SCOPE.nacos_group, "dataId": "aillisten-common.yaml", "type": "yaml", "content": content})
        response.raise_for_status()
        if response.json() is not True:
            raise RuntimeError("Nacos project configuration failed")
        # Publish only audited, project-specific profiles. Secrets remain process
        # environment placeholders, not plaintext Nacos configuration values.
        for module in ("user", "album", "order"):
            source = (ROOT / f"backend/java/tingshu-parent/service/service-{module}/src/main/resources/application-vm.yml").read_text(encoding="utf-8")
            response = client.post("/v1/cs/configs", data={"tenant": SCOPE.nacos_namespace,
                "group": SCOPE.nacos_group, "dataId": f"aillisten-dev-{module}-vm.yaml",
                "type": "yaml", "content": "# owner: " + OWNER + "\n" + source})
            response.raise_for_status()
            if response.json() is not True:
                raise RuntimeError("Nacos service configuration failed")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Create only resources in the fixed project manifest")
    args = parser.parse_args()
    if not args.apply:
        print(json.dumps({"owner": OWNER, "schemas": SCHEMAS, "rabbit_vhost": SCOPE.rabbit_vhost,
                          "redis_prefix": SCOPE.redis_prefix, "nacos_namespace": SCOPE.nacos_namespace}, indent=2))
        return
    admin = json.loads((RUNTIME / "vm-bootstrap-private.json").read_text(encoding="utf-8"))
    cfg = app_config(admin["host"])
    provision_mysql(admin, cfg)
    print("Owned MySQL schemas and application/reader accounts ready", flush=True)
    redis_status = provision_redis(cfg)
    print("Redis project ACL verified", flush=True)
    provision_rabbit(admin, cfg)
    print("RabbitMQ project vhost and account ready", flush=True)
    provision_nacos(cfg)
    print("Nacos project namespace ready", flush=True)
    (RUNTIME / "vm-provision-report.json").write_text(json.dumps({"owner": OWNER,
        "host": cfg["host"], "mysql": list(SCHEMAS.values()), "redis": redis_status,
        "rabbit_vhost": SCOPE.rabbit_vhost, "nacos_namespace": SCOPE.nacos_namespace}, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
