"""Exercise concurrent progress upserts in the project's owned VM database."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _bootstrap import ROOT
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import quote
import json
import secrets
import uuid

import httpx
from pymongo import MongoClient
from resource_scope import OWNER


def index_names(value):
    if isinstance(value, dict):
        return ([value['indexName']] if 'indexName' in value else []) + [name for child in value.values() for name in index_names(child)]
    if isinstance(value, list):
        return [name for child in value for name in index_names(child)]
    return []


def main():
    cfg = json.loads((ROOT/'.runtime/vm-app-private.json').read_text(encoding='utf-8'))
    assert cfg['owner'] == OWNER and cfg['host'] == '192.168.6.100'
    base = 'http://127.0.0.1:29183'
    tokens = []
    checks = []
    with httpx.Client(base_url=base, timeout=30, trust_env=False) as client:
        try:
            for _ in range(2):
                account = {'username': 'mongotest_'+uuid.uuid4().hex[:12], 'password': secrets.token_urlsafe(24)}
                client.post('/api/account/register', json=account).raise_for_status()
                tokens.append(client.post('/api/account/login', json=account).raise_for_status().json()['token'])
            header = {'token': tokens[0]}
            owner = int(client.get('/api/me', headers=header).raise_for_status().json()['id'])
            def save(index):
                return client.post('/api/playback/progress', headers=header,
                    json={'albumId': 900001, 'trackId': 900001, 'breakSecond': index+1})
            with ThreadPoolExecutor(max_workers=8) as pool:
                replies = list(pool.map(save, range(20)))
            assert all(r.status_code == 200 for r in replies)
            checks.append('20 concurrent saves accepted')
            assert float(client.get('/api/playback/progress/900001', headers={'token': tokens[1]}).raise_for_status().json()['breakSecond']) == 0
            checks.append('another account cannot read the progress')
            uri = 'mongodb://aillisten_admin:'+quote(cfg['mongo_password'], safe='')+'@'+cfg['host']+':37017/aillisten_dev?authSource=admin'
            with MongoClient(uri, serverSelectionTimeoutMS=5000) as mongo:
                collection = mongo.aillisten_dev.user_listen_progress
                query = {'userId': owner, 'trackId': 900001}
                assert collection.count_documents(query) == 1
                row = collection.find_one(query)
                assert row['_id'] == f'{owner}:900001' and 1 <= float(str(row['breakSecond'])) <= 20
                checks.append('one stable document remains after concurrent upserts')
                indexes = collection.index_information()
                assert indexes['user_track_unique']['unique']
                assert 'recent_visible_progress' in indexes and 'recent_progress' in indexes
                assert all('expireAfterSeconds' not in index for index in indexes.values())
                checks.append('unique and recent indexes exist without progress TTL')
                point_plan = collection.find(query).explain()
                chosen = set(index_names(point_plan['queryPlanner']['winningPlan']))
                assert 'user_track_unique' in chosen
                checks.append('point lookup actually uses compound index')
                recent_plan = collection.find({'userId': owner, 'isShow': 1}).sort('updateTime', -1).limit(20).hint('recent_visible_progress').explain()
                assert 'recent_visible_progress' in index_names(recent_plan['queryPlanner']['winningPlan'])
                checks.append('recent query supports ordered compound index (explicit hint)')
            report = {'passed': len(checks), 'checks': checks, 'owner': OWNER,
                      'point_index': sorted(chosen), 'recent_index_test_used_hint': True,
                      'scope': '20 saves of one sample track; not a throughput benchmark'}
            (ROOT/'.runtime/fusion-mongo-progress.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
            print(json.dumps(report, indent=2))
        finally:
            for token in tokens:
                client.post('/api/account/logout', headers={'token': token})


if __name__ == '__main__':
    main()
