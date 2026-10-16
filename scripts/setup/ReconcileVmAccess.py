"""Restore only the project Redis ACL after a shared Redis restart."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from _bootstrap import ROOT
import json
import redis
from resource_scope import SCOPE,OWNER
from ProvisionVm import provision_redis

if __name__=='__main__':
    cfg=json.loads((ROOT/'.runtime/vm-app-private.json').read_text(encoding='utf-8'))
    assert cfg['owner']==OWNER and cfg['host']=='192.168.6.100'
    client=redis.Redis(host=cfg['host'],username=SCOPE.redis_user,password=cfg['redis_password'],socket_timeout=5)
    try:client.ping()
    except redis.AuthenticationError:
        provision_redis(cfg)
        print('Restored only aillisten-dev Redis ACL; shared server configuration unchanged')
