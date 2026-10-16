"""Owned document catalog and immutable object storage; no source-folder writes."""
import hashlib
import io
import json
import re
import uuid
from pathlib import Path

import pymysql
from fastapi import HTTPException
from minio import Minio
from minio.commonconfig import Tags
from urllib3 import PoolManager
from urllib3.util import Timeout

from project_paths import ROOT, RUNTIME
from resource_scope import OWNER
from search_sync import config, connection

BUCKET = 'aillisten-dev-knowledge'
MAX_UPLOAD = 10 * 1024 * 1024


def object_store():
    cfg = config()
    return Minio(cfg['host'] + ':39000', access_key='aillisten_minio',
        secret_key=cfg['minio_password'], secure=False,
        http_client=PoolManager(timeout=Timeout(connect=5, read=30), retries=False))


def ensure_bucket(store):
    if not store.bucket_exists(BUCKET):
        store.make_bucket(BUCKET)
        tags = Tags.new_bucket_tags()
        tags['aillisten-owner'] = OWNER
        store.set_bucket_tags(BUCKET, tags)
    tags = store.get_bucket_tags(BUCKET)
    if not tags or tags.get('aillisten-owner') != OWNER:
        raise ValueError('Knowledge bucket ownership mismatch')


def artifact_path(relative):
    base = (ROOT / '.runtime/vm/knowledge').resolve()
    target = (base / relative).resolve()
    if not target.is_relative_to(base):
        raise ValueError('Foreign document artifact path')
    return target


def documents():
    with connection(cursorclass=pymysql.cursors.DictCursor) as db:
        with db.cursor() as cur:
            cur.execute('SELECT id,title,filename,desired_revision,active_revision,active_path,deleted,status,error_code,trace_json,created_at,updated_at FROM knowledge_document ORDER BY id DESC LIMIT 500')
            return cur.fetchall()


def active_documents():
    return [{'path': str(artifact_path(row['active_path'])), 'title': row['title'],
             'source': f"uploaded:{row['id']}:{row['active_revision'][:12]}", 'document_id':row['id']}
            for row in documents() if not row['deleted'] and row['active_revision'] and row['active_path']]


def enqueue(title, filename, content, actor, document_id=None):
    title = title.strip()
    suffix = Path(filename).suffix.lower()
    if not 2 <= len(title) <= 120 or suffix not in {'.md','.txt','.pdf'}:
        raise HTTPException(422,'请填写 2–120 字标题，并上传 Markdown、TXT 或 PDF')
    if not content or len(content) > MAX_UPLOAD:
        raise HTTPException(422,'文件须为 1 字节至 10 MB')
    revision = hashlib.sha256(title.encode() + b'\x00' + content).hexdigest()
    key = 'documents/' + uuid.uuid4().hex + '/' + revision + suffix
    store = object_store()
    ensure_bucket(store)
    store.put_object(BUCKET,key,io.BytesIO(content),len(content),content_type='application/octet-stream')
    event = str(uuid.uuid4())
    with connection(autocommit=False,cursorclass=pymysql.cursors.DictCursor) as db:
        with db.cursor() as cur:
            if document_id:
                cur.execute('SELECT desired_revision,deleted FROM knowledge_document WHERE id=%s FOR UPDATE',(document_id,))
                previous = cur.fetchone()
                if not previous or previous['deleted']:
                    raise HTTPException(404,'资料不存在')
                if previous['desired_revision'] == revision:
                    db.rollback()
                    store.remove_object(BUCKET,key)
                    return {'id':document_id,'reused':True}
                cur.execute("UPDATE knowledge_document SET title=%s,filename=%s,desired_revision=%s,object_key=%s,status='QUEUED',error_code=NULL,actor_id=%s,updated_at=UTC_TIMESTAMP(6) WHERE id=%s",
                    (title,Path(filename).name[:240],revision,key,actor,document_id))
            else:
                cur.execute("INSERT INTO knowledge_document(title,filename,desired_revision,object_key,actor_id,created_at,updated_at) VALUES(%s,%s,%s,%s,%s,UTC_TIMESTAMP(6),UTC_TIMESTAMP(6))",
                    (title,Path(filename).name[:240],revision,key,actor))
                document_id = cur.lastrowid
            cur.execute("INSERT INTO search_outbox(id,kind,aggregate_id,actor_id,request_hash,next_attempt,created_at,updated_at) VALUES(%s,'KNOWLEDGE_CHANGED',%s,%s,%s,UTC_TIMESTAMP(6),UTC_TIMESTAMP(6),UTC_TIMESTAMP(6))",
                (event,document_id,actor,revision))
        db.commit()
    return {'id':document_id,'requestId':event,'status':'QUEUED','reused':False}


def remove(document_id, actor):
    with connection(autocommit=False) as db:
        with db.cursor() as cur:
            cur.execute('SELECT deleted FROM knowledge_document WHERE id=%s FOR UPDATE',(document_id,))
            previous=cur.fetchone()
            if not previous:
                raise HTTPException(404,'资料不存在')
            if previous[0]:
                return {'id':document_id,'reused':True}
            cur.execute("UPDATE knowledge_document SET deleted=1,status='DELETING',updated_at=UTC_TIMESTAMP(6) WHERE id=%s",(document_id,))
            event=str(uuid.uuid4())
            cur.execute("INSERT INTO search_outbox(id,kind,aggregate_id,actor_id,next_attempt,created_at,updated_at) VALUES(%s,'KNOWLEDGE_CHANGED',%s,%s,UTC_TIMESTAMP(6),UTC_TIMESTAMP(6),UTC_TIMESTAMP(6))",(event,document_id,actor))
        db.commit()
    return {'id':document_id,'requestId':event,'status':'DELETING'}


def retry(document_id, actor):
    with connection(autocommit=False) as db:
        with db.cursor() as cur:
            cur.execute('SELECT id FROM knowledge_document WHERE id=%s FOR UPDATE',(document_id,))
            if not cur.fetchone():
                raise HTTPException(404,'资料不存在')
            cur.execute("SELECT id FROM search_outbox WHERE aggregate_id=%s AND kind='KNOWLEDGE_CHANGED' AND status IN ('PENDING','PUBLISHED','RUNNING') LIMIT 1",(document_id,))
            if cur.fetchone():
                raise HTTPException(409,'导入任务仍在处理，请稍后刷新')
            event=str(uuid.uuid4())
            cur.execute("UPDATE knowledge_document SET status=IF(deleted=1,'DELETING','QUEUED'),error_code=NULL,updated_at=UTC_TIMESTAMP(6) WHERE id=%s",(document_id,))
            cur.execute("INSERT INTO search_outbox(id,kind,aggregate_id,actor_id,next_attempt,created_at,updated_at) VALUES(%s,'KNOWLEDGE_CHANGED',%s,%s,UTC_TIMESTAMP(6),UTC_TIMESTAMP(6),UTC_TIMESTAMP(6))",(event,document_id,actor))
        db.commit()
    return {'id':document_id,'requestId':event,'status':'QUEUED'}
