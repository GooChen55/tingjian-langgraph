"""Business fixture connections follow the active project's resource manifest.

VM verification never uses root or the original tingshu_* schemas. SQL rendering
also covers older acceptance scripts so they cannot seed another project's DB.
"""
import json
import os

import pymysql
from _bootstrap import ROOT
from resource_scope import OWNER, SCOPE, remap_schemas, SCHEMAS


def business_connection(*, readonly=False, **kwargs):
    manifest = ROOT / ".runtime/environment.json"
    active = json.loads(manifest.read_text(encoding="utf-8-sig")) if manifest.exists() else {}
    vm = active.get("infrastructure") == "vm"
    if vm:
        if active.get("owner") != OWNER:
            raise ValueError("Runtime resource ownership mismatch")
        cfg = json.loads((ROOT / ".runtime/vm-app-private.json").read_text(encoding="utf-8"))
        if cfg["owner"] != OWNER or cfg["host"] != "192.168.6.100":
            raise ValueError("VM connection does not match the resource manifest")
        database = kwargs.pop("database", None)
        if database is not None:
            kwargs["database"] = SCOPE.schema(database)
        cursor_type = kwargs.pop("cursorclass", pymysql.cursors.Cursor)
        class ScopedCursor(cursor_type):
            def execute(self, query, args=None):
                return super().execute(remap_schemas(query), args)
        kwargs["cursorclass"] = ScopedCursor
        return pymysql.connect(host=cfg["host"], port=3306,
            user=SCOPE.mysql_reader if readonly else SCOPE.mysql_user,
            password=cfg["reader_password"] if readonly else cfg["mysql_password"], connect_timeout=8, **kwargs)
    if os.environ.get("LISTENING_INFRASTRUCTURE") == "vm":
        raise ValueError("VM mode requested without an active owned manifest")
    return pymysql.connect(host="127.0.0.1", port=24316, user="listening_reader" if readonly else "root",
        password=(ROOT / ".runtime/reader-password").read_text(encoding="utf-8-sig").strip() if readonly else os.environ.get("LISTENING_DB_PASSWORD", "listening_local_only"),
        connect_timeout=8, **kwargs)
