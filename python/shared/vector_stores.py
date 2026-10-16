"""Small HTTP adapters for the project's dedicated vector/graph containers."""
import hashlib
import json
import re
import uuid

import httpx

from project_paths import ROOT
from resource_scope import OWNER


def vm_data_credentials():
    value = json.loads((ROOT / ".runtime/vm-app-private.json").read_text(encoding="utf-8"))
    if value.get("owner") != OWNER or value.get("host") != "192.168.6.100":
        raise ValueError("AI store credentials belong to a different project")
    return value


class MilvusChunks:
    def __init__(self, connection, transport=None,generation=None):
        cfg = vm_data_credentials()
        self.url = f"http://{cfg['host']}:39530"
        self.token = "root:" + cfg["milvus_password"]
        fingerprint = hashlib.sha256(json.dumps([connection['base_url'], connection['model'],
            connection['dimensions']]).encode()).hexdigest()[:12]
        self.collection = f"aillisten_dev_chunks_{fingerprint}"
        if generation:
            if not re.fullmatch(r'[a-f0-9]{12}',generation):raise ValueError('Invalid corpus generation')
            self.collection += '_' + generation
        self.dimension = connection['dimensions']
        self.transport = transport

    async def call(self, operation, payload=None):
        if not re.fullmatch(r"aillisten_dev_chunks_[a-f0-9]{12}(?:_[a-f0-9]{12})?", self.collection):
            raise ValueError("Foreign Milvus collection")
        async with httpx.AsyncClient(base_url=self.url, timeout=45, trust_env=False,
            transport=self.transport, headers={"Authorization": "Bearer " + self.token}) as http:
            response = await http.post("/v2/vectordb/" + operation,
                json={"collectionName": self.collection, **(payload or {})})
            response.raise_for_status()
            result = response.json()
            if result.get("code") != 0:
                raise ValueError("Project Milvus operation failed: " + str(result.get("code")))
            return result.get("data", {})

    async def build(self, chunks, vectors):
        result = await self.call("collections/has")
        if not result.get("has"):
            await self.call("collections/create", {"dimension": self.dimension,
                "primaryFieldName": "chunk_id", "idType": "VarChar", "autoID": False,
                "vectorFieldName": "vector", "metricType": "COSINE", "params": {
                    "max_length": 64, "enableDynamicField": True, "consistencyLevel": "Strong"}})
        for start in range(0, len(chunks), 40):
            await self.call("entities/upsert", {"data": [{**c, "owner": OWNER, "vector": v.tolist()}
                for c, v in zip(chunks[start:start + 40], vectors[start:start + 40])]})
        await self.call("collections/load")

    async def search(self, vector, names=None, limit=30):
        expression = 'owner == ' + json.dumps(OWNER)
        if names:
            expression += ' and title in ' + json.dumps(names, ensure_ascii=False)
        return await self.call("entities/search", {"data": [vector.tolist()],
            "annsField": "vector", "filter": expression, "limit": min(limit, 100),
            "outputFields": ["chunk_id"], "consistencyLevel": "Strong"})


class MetadataVectors:
    def __init__(self, connection):
        cfg = vm_data_credentials()
        self.url = f"http://{cfg['host']}:36333"
        self.headers = {"api-key": cfg["qdrant_key"]}
        self.dimensions = connection['dimensions']
        fingerprint = hashlib.sha256(json.dumps([connection['base_url'], connection['model'],
            connection['dimensions']]).encode()).hexdigest()[:12]
        self.collection = "aillisten_dev_metadata_" + fingerprint

    async def build(self, docs, vectors):
        async with httpx.AsyncClient(base_url=self.url, timeout=30, trust_env=False, headers=self.headers) as http:
            response = await http.get("/collections/" + self.collection)
            if response.status_code == 404:
                response = await http.put("/collections/" + self.collection, json={
                    "vectors": {"size": self.dimensions, "distance": "Cosine"}})
                response.raise_for_status()
            else:
                response.raise_for_status()
                if response.json()["result"]["config"]["params"]["vectors"]["size"] != self.dimensions:
                    raise ValueError("Qdrant metadata dimensions changed; create a new versioned collection")
            for start in range(0, len(docs), 50):
                points = [{"id": str(uuid.uuid5(uuid.NAMESPACE_URL, OWNER + ":" + identity)),
                    "vector": vector.tolist(), "payload": {**doc, "owner": OWNER, "identity": identity}}
                    for (identity, doc), vector in zip(docs[start:start + 50], vectors[start:start + 50])]
                response = await http.put(f"/collections/{self.collection}/points", params={"wait": "true"}, json={"points": points})
                response.raise_for_status()

    async def search(self, vector, limit=20,kind=None):
        async with httpx.AsyncClient(base_url=self.url, timeout=15, trust_env=False, headers=self.headers) as http:
            response = await http.post(f"/collections/{self.collection}/points/query", json={
                "query": vector.tolist(), "limit": limit, "with_payload": True,
                "filter": {"must": [{"key": "owner", "match": {"value": OWNER}}]+([{'key':'kind','match':{'value':kind}}] if kind else [])}})
            response.raise_for_status()
            return response.json()["result"]["points"]


class KnowledgeGraph:
    def __init__(self):
        cfg = vm_data_credentials()
        self.url = f"http://{cfg['host']}:47474"
        self.auth = ("neo4j", cfg["neo4j_password"])

    async def query(self, statement, parameters):
        async with httpx.AsyncClient(base_url=self.url, auth=self.auth, timeout=20, trust_env=False) as http:
            response = await http.post("/db/neo4j/tx/commit", json={"statements": [{
                "statement": statement, "parameters": {"owner": OWNER, **parameters}}]})
            response.raise_for_status()
            body = response.json()
            if body.get("errors"):
                raise ValueError("Project knowledge graph operation failed")
            return body["results"][0].get("data", [])

    async def build(self, chunks):
        # Relationships are grounded in source metadata, never model-generated facts.
        await self.query("""UNWIND $chunks AS row
            MERGE (b:AillistenBook {owner:$owner,title:row.title})
            MERGE (c:AillistenChunk {owner:$owner,id:row.chunk_id})
            SET c.source=row.source,c.section=row.section
            MERGE (s:AillistenSection {owner:$owner,book:row.title,title:row.section})
            MERGE (b)-[:HAS_SECTION]->(s) MERGE (s)-[:HAS_CHUNK]->(c)
            MERGE (b)-[:HAS_CHUNK]->(c)""", {"chunks": chunks})

    async def search(self, question, limit=10):
        rows = await self.query("""MATCH (b:AillistenBook {owner:$owner})-[:HAS_CHUNK]->(c:AillistenChunk {owner:$owner})
            WHERE $question CONTAINS b.title OR $question CONTAINS c.section
            RETURN DISTINCT c.id ORDER BY c.id LIMIT $limit""", {"question": question, "limit": limit})
        return [row["row"][0] for row in rows]
