"""Verify real shared-VM resource boundaries, without touching foreign data."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _bootstrap import ROOT

import json
import secrets
import httpx
import pika
import pymysql
import redis

from resource_scope import OWNER, SCOPE, SCHEMAS


def main():
    cfg = json.loads((ROOT / ".runtime/vm-app-private.json").read_text(encoding="utf-8"))
    assert cfg["owner"] == OWNER
    results = {}
    with pymysql.connect(host=cfg["host"], user=SCOPE.mysql_user, password=cfg["mysql_password"],
                         connect_timeout=5, charset="utf8mb4") as db:
        with db.cursor() as cur:
            for schema in SCHEMAS.values():
                cur.execute(f"SELECT owner FROM `{schema}`._aillisten_owner")
                assert cur.fetchall() == ((OWNER,),)
            try:
                cur.execute("SELECT id FROM tingshu_user.user_info LIMIT 0")
            except pymysql.err.OperationalError as exc:
                assert exc.args[0] == 1142
            else:
                raise AssertionError("App account can read foreign business schema")
    results["mysql_app_isolation"] = True
    with pymysql.connect(host=cfg["host"], user=SCOPE.mysql_reader, password=cfg["reader_password"],
                         database=SCOPE.schema("listening_ops"), connect_timeout=5) as db:
        with db.cursor() as cur:
            cur.execute("SELECT album_count,track_count FROM v_content_summary")
            results["readonly_query"] = list(cur.fetchone())
            try:
                cur.execute("SELECT id FROM aillisten_dev_user.user_info LIMIT 0")
            except pymysql.err.OperationalError as exc:
                assert exc.args[0] == 1142
            else:
                raise AssertionError("Reader can access personal data")
    results["mysql_reader_isolation"] = True
    client = redis.Redis(host=cfg["host"], username=SCOPE.redis_user, password=cfg["redis_password"],
                         decode_responses=True, socket_timeout=5)
    key = SCOPE.redis_prefix + "verify:" + secrets.token_hex(8)
    client.set(key, OWNER, ex=30)
    assert client.get(key) == OWNER
    client.delete(key)
    for command in [("GET", "foreign_project:probe"), ("CONFIG", "GET", "port"), ("ACL", "USERS")]:
        try:
            client.execute_command(*command)
        except redis.exceptions.NoPermissionError:
            pass
        else:
            raise AssertionError("Redis scope allows a forbidden operation")
    results["redis_isolation"] = True
    connection = pika.BlockingConnection(pika.ConnectionParameters(host=cfg["host"],
        virtual_host=SCOPE.rabbit_vhost, credentials=pika.PlainCredentials(SCOPE.rabbit_user, cfg["rabbit_password"]),
        socket_timeout=5, blocked_connection_timeout=5))
    channel = connection.channel()
    name = "aillisten.dev.verify." + secrets.token_hex(8)
    channel.queue_declare(queue=name, exclusive=True, auto_delete=True)
    channel.exchange_declare(exchange=name, exchange_type="direct", auto_delete=True)
    channel.queue_bind(queue=name, exchange=name, routing_key="check")
    channel.confirm_delivery()
    assert channel.basic_publish(exchange=name, routing_key="check", body=b"scope-check", mandatory=True) is not False
    method, _, body = channel.basic_get(queue=name, auto_ack=False)
    assert body == b"scope-check"
    channel.basic_ack(method.delivery_tag)
    connection.close()
    results["rabbit_confirm_and_ack"] = True
    with httpx.Client(timeout=8, trust_env=False) as http:
        response = http.get(f"http://{cfg['host']}:8848/nacos/v1/cs/configs", params={
            "tenant": SCOPE.nacos_namespace, "group": SCOPE.nacos_group, "dataId": "aillisten-common.yaml"})
        response.raise_for_status()
        assert OWNER in response.text
        results["nacos_namespace_config"] = True
        response = http.get(f"http://{cfg['host']}:9200/")
        response.raise_for_status()
        results["elasticsearch_version"] = response.json()["version"]["number"]
    (ROOT / ".runtime/vm-infrastructure-acceptance.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
