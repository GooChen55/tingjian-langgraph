import asyncio
import httpx
import pytest
from fastapi import HTTPException
from service_discovery import resolve,CACHE
from resource_scope import OWNER


def test_nacos_only_selects_owned_loopback_instance():
    CACHE.clear();seen=[]
    def response(request):
        seen.append(dict(request.url.params))
        return httpx.Response(200,json={'hosts':[{'healthy':True,'ip':'127.0.0.1','port':19201,'metadata':{'owner':OWNER}}]})
    url=asyncio.run(resolve('user','unused','vm',httpx.MockTransport(response)))
    assert url=='http://127.0.0.1:19201'
    assert seen[0]['namespaceId']=='aillisten-dev' and seen[0]['groupName']=='AILLISTEN_DEV'


def test_foreign_registry_entry_is_never_adopted():
    CACHE.clear()
    transport=httpx.MockTransport(lambda r:httpx.Response(200,json={'hosts':[{'healthy':True,'ip':'192.168.6.100','port':19201,'metadata':{'owner':'other'}}]}))
    with pytest.raises(HTTPException) as rejected:asyncio.run(resolve('user','unused','vm',transport))
    assert rejected.value.status_code==503
