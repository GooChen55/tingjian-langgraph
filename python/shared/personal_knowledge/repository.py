"""Owner-scoped metadata and transactional outbox, on owned project schemas."""
import hashlib
import json
import uuid
from contextlib import contextmanager

import pymysql
from fastapi import HTTPException
from search_sync import connection


def owner_id(owner):
    value=str(owner)
    if not value.isascii() or not value.isdecimal() or int(value)<=0:
        raise ValueError('Invalid authenticated owner')
    return int(value)


@contextmanager
def transaction():
    with connection(autocommit=False,cursorclass=pymysql.cursors.DictCursor) as db:
        try:
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise


def owned_space(cur,owner,space,lock=False):
    cur.execute('SELECT * FROM personal_space WHERE id=%s AND owner_id=%s'+(' FOR UPDATE' if lock else ''),(space,owner_id(owner)))
    row=cur.fetchone()
    if not row:raise HTTPException(404,'知识空间不存在')
    return row


def spaces(owner):
    with transaction() as db,db.cursor() as cur:
        cur.execute('SELECT id,name,ai_enabled,created_at FROM personal_space WHERE owner_id=%s ORDER BY created_at',(owner_id(owner),))
        return cur.fetchall()


def create_space(owner,name):
    name=name.strip()
    if not 2<=len(name)<=80:raise HTTPException(422,'空间名称须为 2–80 字')
    with transaction() as db,db.cursor() as cur:
        # A single project user row serializes quota checks across concurrent creates.
        from resource_scope import SCOPE
        cur.execute('SELECT id FROM `'+SCOPE.schema('tingshu_user')+'`.user_info WHERE id=%s FOR UPDATE',(owner_id(owner),))
        if not cur.fetchone():raise HTTPException(401,'账号不存在')
        cur.execute('SELECT id FROM personal_space WHERE owner_id=%s AND name=%s',(owner_id(owner),name))
        previous=cur.fetchone()
        if previous:return {'id':previous['id'],'reused':True}
        cur.execute('SELECT COUNT(*) AS n FROM personal_space WHERE owner_id=%s',(owner_id(owner),))
        if cur.fetchone()['n']>=5:raise HTTPException(422,'每个账号最多创建5个空间')
        identity=str(uuid.uuid4())
        cur.execute('INSERT INTO personal_space(id,owner_id,name) VALUES(%s,%s,%s)',(identity,owner_id(owner),name))
        return {'id':identity,'reused':False}


def event(cur,item,owner):
    identity=str(uuid.uuid4())
    cur.execute("INSERT INTO search_outbox(id,kind,aggregate_id,actor_id) VALUES(%s,'PERSONAL_CHANGED',%s,%s)",(identity,item,owner_id(owner)))
    return identity


def settings(owner,space,enabled):
    with transaction() as db,db.cursor() as cur:
        owned_space(cur,owner,space,True)
        cur.execute('UPDATE personal_space SET ai_enabled=%s WHERE id=%s AND owner_id=%s',(int(enabled),space,owner_id(owner)))
        cur.execute("UPDATE personal_item SET status='QUEUED',error_code=NULL WHERE owner_id=%s AND space_id=%s AND deleted=0",(owner_id(owner),space))
        cur.execute('SELECT id FROM personal_item WHERE owner_id=%s AND space_id=%s AND deleted=0',(owner_id(owner),space))
        rows=cur.fetchall()
        for row in rows:event(cur,row['id'],owner)
        return {'ai_enabled':enabled,'queued':len(rows)}


def items(owner,space,active=False):
    with transaction() as db,db.cursor() as cur:
        scope=owned_space(cur,owner,space)
        cur.execute('SELECT * FROM personal_item WHERE owner_id=%s AND space_id=%s AND deleted=0'+(' AND active_revision IS NOT NULL' if active else '')+' ORDER BY updated_at DESC,id DESC LIMIT 100',(owner_id(owner),space))
        return scope,cur.fetchall()


def get_item(owner,space,identity):
    with transaction() as db,db.cursor() as cur:
        owned_space(cur,owner,space)
        cur.execute('SELECT * FROM personal_item WHERE id=%s AND owner_id=%s AND space_id=%s AND deleted=0',(identity,owner_id(owner),space))
        row=cur.fetchone()
        if not row:raise HTTPException(404,'私人资料不存在')
        return row


def save(owner,space,data,identity=None,blob=None):
    from .providers import objects
    key=None
    try:
        with transaction() as db,db.cursor() as cur:
            owned_space(cur,owner,space,True)
            if identity:
                cur.execute('SELECT * FROM personal_item WHERE id=%s AND owner_id=%s AND space_id=%s AND deleted=0 FOR UPDATE',(identity,owner_id(owner),space))
                previous=cur.fetchone()
                if not previous:raise HTTPException(404,'私人资料不存在')
                if previous['kind']=='DOCUMENT' and blob is None:raise HTTPException(422,'更新文件请重新上传')
                if previous['kind']!=data['kind']:raise HTTPException(422,'不能改变资料类型')
            else:
                cur.execute('SELECT COUNT(*) AS n FROM personal_item WHERE owner_id=%s AND space_id=%s AND deleted=0',(owner_id(owner),space))
                if cur.fetchone()['n']>=100:raise HTTPException(422,'每个空间最多100条笔记、书签及资料，请先整理')
            canonical=json.dumps(data,ensure_ascii=False,sort_keys=True).encode()+(blob or b'')
            revision=hashlib.sha256(canonical).hexdigest()
            if identity and previous['revision']==revision:return {'id':identity,'reused':True}
            if blob is not None:
                key=f'personal/{owner_id(owner)}/{space}/{uuid.uuid4().hex}/{revision}'
                objects().put(owner,space,key,blob)
            values=(data['title'],data.get('content',''),data.get('filename'),key,data.get('album_id'),data.get('track_id'),data.get('anchor_second'),revision)
            if identity:
                cur.execute("UPDATE personal_item SET title=%s,content=%s,filename=%s,object_key=%s,album_id=%s,track_id=%s,anchor_second=%s,revision=%s,status='QUEUED',error_code=NULL,updated_at=UTC_TIMESTAMP(6) WHERE id=%s AND owner_id=%s AND space_id=%s",(*values,identity,owner_id(owner),space))
            else:
                cur.execute('INSERT INTO personal_item(title,content,filename,object_key,album_id,track_id,anchor_second,revision,owner_id,space_id,kind) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)',(*values,owner_id(owner),space,data['kind']))
                identity=cur.lastrowid
            request=event(cur,identity,owner)
        return {'id':identity,'request_id':request,'status':'QUEUED','reused':False}
    except BaseException:
        # A lost MySQL commit acknowledgement is ambiguous: deleting the blob
        # could remove an already committed item's source. Retain immutable
        # originals until reconciliation/retention cleanup can prove them unused.
        raise


def delete(owner,space,identity):
    with transaction() as db,db.cursor() as cur:
        owned_space(cur,owner,space,True)
        cur.execute('SELECT id FROM personal_item WHERE id=%s AND owner_id=%s AND space_id=%s AND deleted=0 FOR UPDATE',(identity,owner_id(owner),space))
        if not cur.fetchone():raise HTTPException(404,'私人资料不存在')
        cur.execute("UPDATE personal_item SET deleted=1,status='DELETING',updated_at=UTC_TIMESTAMP(6) WHERE id=%s AND owner_id=%s AND space_id=%s",(identity,owner_id(owner),space))
        return {'request_id':event(cur,identity,owner),'deleted':True}


def retry(owner,space,identity):
    with transaction() as db,db.cursor() as cur:
        owned_space(cur,owner,space,True)
        cur.execute('SELECT status FROM personal_item WHERE id=%s AND owner_id=%s AND space_id=%s AND deleted=0 FOR UPDATE',(identity,owner_id(owner),space))
        row=cur.fetchone()
        if not row:raise HTTPException(404,'私人资料不存在')
        cur.execute("SELECT id FROM search_outbox WHERE kind='PERSONAL_CHANGED' AND aggregate_id=%s AND status IN ('PENDING','RUNNING','PUBLISHED') LIMIT 1",(identity,))
        if cur.fetchone():raise HTTPException(409,'任务仍在处理')
        cur.execute("UPDATE personal_item SET status='QUEUED',error_code=NULL WHERE id=%s",(identity,))
        return {'request_id':event(cur,identity,owner),'status':'QUEUED'}
