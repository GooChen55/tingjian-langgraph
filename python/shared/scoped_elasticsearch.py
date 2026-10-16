"""Elasticsearch access restricted to exact project-owned indexes.

On a cluster without security this is an application boundary, not a substitute
for Elasticsearch authorization. Never enable cluster security globally here.
"""
import json
import re

import httpx

from resource_scope import OWNER, SCOPE


class ScopedElasticsearch:
    def __init__(self, url: str, transport=None):
        self.url = url.rstrip("/")
        self.transport = transport

    def client(self):
        return httpx.AsyncClient(base_url=self.url, timeout=15, trust_env=False,
                                 transport=self.transport)

    async def ensure(self, kind: str, properties: dict):
        name = SCOPE.es_index(kind)
        async with self.client() as client:
            response = await client.get(f"/{name}/_mapping")
            if response.status_code == 404:
                response = await client.put(f"/{name}", json={
                    "settings": {"number_of_shards": 1, "number_of_replicas": 0},
                    "mappings": {"_meta": {"owner": OWNER}, "properties": properties},
                })
                # Another process may have created it. Still verify ownership.
                if response.status_code not in (200, 201, 400):
                    response.raise_for_status()
                response = await client.get(f"/{name}/_mapping")
            response.raise_for_status()
            if response.json().get(name, {}).get("mappings", {}).get("_meta", {}).get("owner") != OWNER:
                raise ValueError("Index exists without this project's ownership marker")
            response = await client.put(f'/{name}/_mapping', json={'properties':properties,'_meta':{'owner':OWNER}})
            response.raise_for_status()

    async def upsert(self, kind: str, documents: list[tuple[str, dict]]):
        name = SCOPE.es_index(kind)
        # Check the marker before each write, including after provisioning.
        async with self.client() as client:
            mapping = await client.get(f"/{name}/_mapping")
            mapping.raise_for_status()
            if mapping.json().get(name, {}).get("mappings", {}).get("_meta", {}).get("owner") != OWNER:
                raise ValueError("Refusing to write an unowned index")
            for start in range(0, len(documents), 200):
                lines = []
                for identity, source in documents[start:start + 200]:
                    if not re.fullmatch(r"[A-Za-z0-9_.:-]{1,160}", identity):
                        raise ValueError("Invalid project document id")
                    lines.extend((json.dumps({"index": {"_index": name, "_id": identity}}),
                                  json.dumps(source, ensure_ascii=False)))
                response = await client.post(f"/{name}/_bulk", content="\n".join(lines) + "\n",
                    headers={"Content-Type": "application/x-ndjson"})
                response.raise_for_status()
                if response.json().get("errors"):
                    raise ValueError("Some project search documents failed to index")
            response = await client.post(f"/{name}/_refresh")
            response.raise_for_status()

    async def search(self, kind: str, query: dict, *, size=10, offset=0, sort=None, aggregations=None, highlight=None):
        name = SCOPE.es_index(kind)
        if not 1 <= size <= 100 or not 0 <= offset <= 1000:
            raise ValueError("Search pagination is out of bounds")
        async with self.client() as client:
            response = await client.post(f"/{name}/_search", json={
                "query": query, "size": size, "from": offset, "track_total_hits": True,
                **({'sort':sort} if sort else {}), **({'aggs':aggregations} if aggregations else {}),
                **({'highlight':highlight} if highlight else {}),
            })
            response.raise_for_status()
            return response.json()

    async def delete_document(self, kind, identity):
        if not re.fullmatch(r'[A-Za-z0-9_.:-]{1,160}',identity):
            raise ValueError('Invalid project document id')
        name=SCOPE.es_index(kind)
        async with self.client() as client:
            mapping=await client.get(f'/{name}/_mapping')
            mapping.raise_for_status()
            if mapping.json().get(name,{}).get('mappings',{}).get('_meta',{}).get('owner')!=OWNER:
                raise ValueError('Refusing to delete an unowned index document')
            response=await client.delete(f'/{name}/_doc/{identity}',params={'refresh':'wait_for'})
            if response.status_code!=404:
                response.raise_for_status()

    async def prune(self,kind,identities):
        name=SCOPE.es_index(kind)
        if any(not re.fullmatch(r'[A-Za-z0-9_.:-]{1,160}',identity) for identity in identities):
            raise ValueError('Invalid project document ids')
        async with self.client() as client:
            mapping=await client.get(f'/{name}/_mapping');mapping.raise_for_status()
            if mapping.json().get(name,{}).get('mappings',{}).get('_meta',{}).get('owner')!=OWNER:
                raise ValueError('Refusing to prune an unowned index')
            response=await client.post(f'/{name}/_delete_by_query',params={'refresh':'true','conflicts':'proceed'},
                json={'query':{'bool':{'must_not':[{'ids':{'values':identities}}]}}})
            response.raise_for_status()
