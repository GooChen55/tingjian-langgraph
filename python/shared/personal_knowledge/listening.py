"""Client-reported listening intervals, distinct from resume position."""
import hashlib
import json
import os
from datetime import datetime,timedelta,timezone

from fastapi import HTTPException
from pymongo import MongoClient,ASCENDING,DESCENDING
from pymongo.errors import DuplicateKeyError
from listening_common import ServiceSettings
from .repository import owner_id


def merged_intervals(rows):
    merged=[]
    for start,end in sorted((float(r['start']),float(r['end'])) for r in rows):
        if end<=start:continue
        if merged and start<=merged[-1][1]+.05:merged[-1][1]=max(merged[-1][1],end)
        else:merged.append([start,end])
    return merged


def mongo():
    uri=ServiceSettings().listening_mongo_uri
    if not uri:raise HTTPException(503,'尚未配置项目专属 MongoDB')
    return MongoClient(uri,serverSelectionTimeoutMS=5000,tz_aware=True)


def save_segment(owner,data):
    owner=owner_id(owner)
    # This is a playback observation, never evidence of payment or proof of comprehension.
    identity=f"{owner}:{data['session_id']}:{data['sequence']}"
    digest=hashlib.sha256(json.dumps(data,sort_keys=True).encode()).hexdigest()
    with mongo() as client:
        db=client['aillisten_dev'];collection=db['personal_listen_segments']
        collection.create_index([('owner_id',ASCENDING),('received_at',DESCENDING)],name='personal_recent_listening')
        inserted=False
        try:
            result=collection.update_one({'_id':identity},{'$setOnInsert':{**data,'owner_id':owner,'payload_hash':digest,'received_at':datetime.now(timezone.utc)}},upsert=True)
            inserted=bool(result.upserted_id)
        except DuplicateKeyError:pass
        if not inserted:
            previous=collection.find_one({'_id':identity,'owner_id':owner})
            if not previous or previous['payload_hash']!=digest:raise HTTPException(409,'播放区间序号已被用于其他数据')
    return {'saved':True,'replayed':not inserted}


def review(owner,days=14):
    owner=owner_id(owner);cutoff=datetime.now(timezone.utc)-timedelta(days=days)
    with mongo() as client:
        db=client['aillisten_dev']
        rows=list(db.personal_listen_segments.find({'owner_id':owner,'received_at':{'$gte':cutoff}}).sort('received_at',-1).limit(5001))
        truncated=len(rows)>5000;rows=rows[:5000]
        positions=list(db.user_listen_progress.find({'userId':owner}).sort('updateTime',-1).limit(20))
    grouped={}
    for row in rows:
        key=str(row['track_id'])
        if key not in grouped and len(grouped)>=20:continue
        item=grouped.setdefault(key,{'track_id':row['track_id'],'album_id':row['album_id'],'intervals':[],'reported_seconds':0,'last_seen':row['received_at']})
        item['intervals'].append(row);item['reported_seconds']+=row['end']-row['start']
    for p in positions:
        key=str(p['trackId'])
        if key not in grouped and len(grouped)>=20:continue
        item=grouped.setdefault(key,{'track_id':p['trackId'],'album_id':p['albumId'],'intervals':[],'reported_seconds':0,'last_seen':p.get('updateTime')})
        item['resume_second']=float(str(p.get('breakSecond',0)))
    result=[]
    for item in grouped.values():
        item['intervals']=merged_intervals(item['intervals'])
        item['covered_seconds']=round(sum(end-start for start,end in item['intervals']),2)
        item['reported_seconds']=round(item['reported_seconds'],2);result.append(item)
    return {'days':days,'records':result,'truncated':truncated,'basis':'客户端上报的播放区间；不等同于完整听完或理解。保存位置和拖动进度不会生成已听区间。'}
