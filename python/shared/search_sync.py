"""Idempotent search projection: always read current business visibility."""
import json
import re

import pymysql

from project_paths import ROOT
from resource_scope import OWNER,SCOPE
from scoped_elasticsearch import ScopedElasticsearch


def config():
    cfg=json.loads((ROOT/'.runtime/vm-app-private.json').read_text(encoding='utf-8'))
    if cfg.get('owner')!=OWNER or cfg.get('host')!='192.168.6.100':
        raise ValueError('Search projection ownership mismatch')
    return cfg


def connection(database='listening_ops',**kwargs):
    cfg=config()
    return pymysql.connect(host=cfg['host'],user=SCOPE.mysql_user,password=cfg['mysql_password'],
        database=SCOPE.schema(database),charset='utf8mb4',connect_timeout=5,read_timeout=10,write_timeout=10,**kwargs)


def public_albums(album_id=None):
    with connection('tingshu_album',cursorclass=pymysql.cursors.DictCursor) as db:
        with db.cursor() as cur:
            cur.execute("""SELECT a.id,a.album_title,a.album_intro,a.category3_id,a.pay_type,a.create_time,
                v.category1_id,v.category2_id,v.category3_name,
                COALESCE((SELECT SUM(s.stat_num) FROM album_stat s WHERE s.album_id=a.id AND s.stat_type='0401' AND s.is_deleted=0),0) AS play_count
                FROM album_info a LEFT JOIN base_category_view v ON v.category3_id=a.category3_id
                WHERE a.is_deleted=0 AND a.is_open='1' AND a.status='0301'"""+
                (' AND a.id=%s' if album_id is not None else ''),(album_id,) if album_id is not None else ())
            return [(str(row['id']),{'id':row['id'],'albumTitle':row['album_title'],
                'albumIntro':re.sub(r'<[^>]+>',' ',row['album_intro'] or '')[:12000],
                'category3Id':row['category3_id'],'category1Id':row['category1_id'],
                'category2Id':row['category2_id'],'categoryName':row['category3_name'],
                'payType':row['pay_type'],'playCount':int(row['play_count']),
                'createTime':row['create_time'].isoformat() if row['create_time'] else None}) for row in cur.fetchall()]


async def sync_album(album_id):
    if not isinstance(album_id,int) or album_id<1:
        raise ValueError('Invalid album projection id')
    cfg=config();es=ScopedElasticsearch(f"http://{cfg['host']}:9200")
    rows=public_albums(album_id)
    if rows:
        await es.upsert('albums',rows)
    else:
        await es.delete_document('albums',str(album_id))


def outbox_rows(limit=30):
    with connection(cursorclass=pymysql.cursors.DictCursor) as db:
        with db.cursor() as cur:
            cur.execute('SELECT id,kind,aggregate_id,status,attempts,error_code,created_at,updated_at FROM search_outbox ORDER BY created_at DESC LIMIT %s',(limit,))
            return cur.fetchall()


def admin_album(identity):
    with connection('tingshu_album',cursorclass=pymysql.cursors.DictCursor) as db:
        with db.cursor() as cur:
            cur.execute('SELECT id,album_title AS albumTitle,is_open,status FROM album_info WHERE id=%s AND is_deleted=0',(identity,))
            row=cur.fetchone()
            if row:row['published']=row.pop('is_open')=='1'
            return row
