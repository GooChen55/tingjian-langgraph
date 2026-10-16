"""Copy legacy progress into the owned unified collection; keep originals."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _bootstrap import ROOT

import json
import re
from datetime import datetime, timezone
from urllib.parse import quote

from pymongo import MongoClient, ASCENDING, DESCENDING
from resource_scope import OWNER


def main():
    cfg=json.loads((ROOT/'.runtime/vm-app-private.json').read_text(encoding='utf-8'))
    assert cfg['owner']==OWNER and cfg['host']=='192.168.6.100'
    uri='mongodb://aillisten_admin:'+quote(cfg['mongo_password'],safe='')+'@'+cfg['host']+':37017/aillisten_dev?authSource=admin'
    with MongoClient(uri,serverSelectionTimeoutMS=5000,tz_aware=True) as client:
        db=client['aillisten_dev'];target=db['user_listen_progress']
        sources=sorted(name for name in db.list_collection_names() if re.fullmatch(r'userListenProcess_[1-9][0-9]*',name))
        copied=0
        for name in sources:
            owner=int(name.removeprefix('userListenProcess_'))
            for document in db[name].find():
                if document.get('userId') != owner or not isinstance(document.get('trackId'),int):
                    raise ValueError('Legacy progress ownership or shape is invalid')
                identity=f"{owner}:{document['trackId']}"
                previous=target.find_one({'_id':identity})
                minimum=datetime.min.replace(tzinfo=timezone.utc)
                if previous and previous.get('updateTime',minimum)>document.get('updateTime',minimum):
                    continue
                document['_id']=identity
                target.replace_one({'_id':identity},document,upsert=True)
                copied+=1
        target.create_index([('userId',ASCENDING),('trackId',ASCENDING)],unique=True,name='user_track_unique')
        target.create_index([('userId',ASCENDING),('isShow',ASCENDING),('updateTime',DESCENDING)],name='recent_visible_progress')
        target.create_index([('userId',ASCENDING),('updateTime',DESCENDING)],name='recent_progress')
        expected={(doc['userId'],doc['trackId']) for name in sources for doc in db[name].find({}, {'userId':1,'trackId':1})}
        assert all(target.count_documents({'userId':user,'trackId':track})==1 for user,track in expected)
        report={'owner':OWNER,'source_collections':len(sources),'source_pairs':len(expected),'copied':copied,
                'unified_count':target.count_documents({}),'old_collections_retained':True}
    (ROOT/'.runtime/vm-mongo-progress-migration.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report,indent=2))


if __name__=='__main__':
    main()
