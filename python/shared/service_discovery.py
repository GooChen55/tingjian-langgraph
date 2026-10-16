"""Resolve only owned local Java instances from the project's Nacos namespace."""
import time
import httpx
from fastapi import HTTPException
from resource_scope import OWNER,SCOPE

PORTS={'user':19201,'album':19202,'order':19204}
CACHE={}


async def resolve(kind,fallback,infrastructure='local',transport=None):
    if infrastructure!='vm':return fallback
    if kind not in PORTS:raise ValueError('Unknown project service')
    key=(kind,id(transport));cached=CACHE.get(key)
    if cached and time.monotonic()-cached[0]<10:return cached[1]
    try:
        async with httpx.AsyncClient(base_url='http://192.168.6.100:8848',timeout=5,trust_env=False,transport=transport) as http:
            response=await http.get('/nacos/v1/ns/instance/list',params={'namespaceId':SCOPE.nacos_namespace,'groupName':SCOPE.nacos_group,'serviceName':'aillisten-dev-'+kind,'healthyOnly':'true'})
            response.raise_for_status();hosts=response.json()['hosts']
        valid=[h for h in hosts if h.get('healthy') and h.get('enabled',True) and h.get('ip')=='127.0.0.1' and h.get('port')==PORTS[kind] and h.get('metadata',{}).get('owner')==OWNER]
        if not valid:raise ValueError('No owned healthy instance')
        result='http://127.0.0.1:'+str(PORTS[kind]);CACHE[key]=(time.monotonic(),result);return result
    except (httpx.HTTPError,KeyError,ValueError):
        raise HTTPException(503,'本项目业务实例未在 Nacos 就绪，请检查服务注册与专属命名空间') from None
