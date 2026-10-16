from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from pathlib import Path

import httpx
import numpy as np
from rank_bm25 import BM25Okapi

from listening_common import ServiceSettings
from model_settings import active_connection, embedding_payload, check_response
from request_trace import forward_trace


def tokenize(text: str) -> list[str]:
    # 中文二元词覆盖书名与章节主题，英文词完整保留。
    words = re.findall(r"[a-z0-9]+|[\u4e00-\u9fff]+", text.lower())
    return [token for word in words for token in
            ([word] if not re.fullmatch(r"[\u4e00-\u9fff]+", word) or len(word) == 1
             else [word[i:i + 2] for i in range(len(word) - 1)])]


def split_documents(folder: str, entries=None) -> list[dict]:
    """沿用智库按 Markdown 标题切分的方式，保留文件、章节与稳定片段 ID。"""
    chunks = []
    files = [{'path':str(path)} for path in sorted(Path(folder).glob('*.md'))] if folder else []
    for entry in files + (entries or []):
        path = Path(entry['path'])
        text = path.read_text(encoding="utf-8-sig").replace("\r\n", "\n")
        title = entry.get('title',path.stem.removesuffix("简介"))
        source = entry.get('source',path.name)
        heading, lines, code = "简介", [], False

        def flush():
            content = "\n".join(lines).strip()
            if not content:
                return
            # 长章节分块并重叠，避免截掉位于资料后半部分的评论和听书笔记。
            for start in range(0, len(content), 650):
                part = content[start:start + 750]
                digest = hashlib.sha256((source + heading + str(start) + part).encode()).hexdigest()[:20]
                chunks.append({"chunk_id": digest, "title": title, "source": source,
                               "section": heading, "text": part})
                if start + 750 >= len(content):
                    break

        for line in text.splitlines():
            if line.strip().startswith(("```", "~~~")):
                code = not code
            match = re.match(r"^#{1,6}\s+(.+)$", line) if not code else None
            if match:
                flush()
                heading, lines = match[1].strip(), []
            else:
                lines.append(line)
        flush()
    return chunks


class VectorIndex:
    def __init__(self, cfg: ServiceSettings, transport=None, connection=None,extra_documents=None,exclude_document_id=None):
        self.cfg, self.transport = cfg, transport
        self.connection = connection or active_connection(cfg, 'embedding')
        entries=[]
        if cfg.listening_infrastructure=='vm':
            from knowledge_catalog import active_documents
            entries=[entry for entry in active_documents() if entry['document_id']!=exclude_document_id]
        self.chunks = split_documents(cfg.listening_docs,entries=entries+(extra_documents or []))
        self.generation=hashlib.sha256(json.dumps([c['chunk_id'] for c in self.chunks]).encode()).hexdigest()[:12]
        self.vectors = None
        self.remote = None
        if cfg.listening_vector_backend == "milvus":
            from vector_stores import MilvusChunks
            self.remote = MilvusChunks(self.connection,generation=self.generation)
        self.bm25 = BM25Okapi([tokenize(c["title"] + " " + c["section"] + " " + c["text"]) for c in self.chunks]) if self.chunks else None

    async def embed(self, texts: list[str]) -> np.ndarray:
        async with httpx.AsyncClient(timeout=45, trust_env=False, transport=self.transport,event_hooks={'request':[forward_trace]}) as http:
            response = await http.post(self.connection['base_url'] + "/embeddings",
                headers={"Authorization": "Bearer " + self.connection['api_key']},
                json=embedding_payload(self.connection, texts))
            check_response(response)
            entries = sorted(response.json()["data"], key=lambda entry: entry["index"])
        matrix = np.array([entry["embedding"] for entry in entries], dtype=np.float32)
        if matrix.shape != (len(texts), self.connection['dimensions']) or not np.isfinite(matrix).all():
            raise ValueError("向量形状或数值不合法")
        norms = np.linalg.norm(matrix, axis=1, keepdims=True)
        if np.any(norms == 0):
            raise ValueError("空向量")
        return matrix / norms

    async def build(self):
        if not self.chunks:
            raise ValueError("未发现听书 Markdown 资料")
        path = Path(self.cfg.listening_index_db)
        path.parent.mkdir(parents=True, exist_ok=True)
        namespace = json.dumps([self.connection['base_url'], self.connection['model'], self.connection['dimensions']])
        with sqlite3.connect(path) as db:
            db.execute("CREATE TABLE IF NOT EXISTS embeddings(namespace TEXT, chunk TEXT, vector BLOB, PRIMARY KEY(namespace,chunk))")
            cached = {chunk: np.frombuffer(vector, dtype=np.float32).copy()
                      for chunk, vector in db.execute("SELECT chunk,vector FROM embeddings WHERE namespace=?", (namespace,))}
            missing = [c for c in self.chunks if c["chunk_id"] not in cached
                       or cached[c["chunk_id"]].shape != (self.connection['dimensions'],)
                       or not np.isfinite(cached[c["chunk_id"]]).all()]
            for start in range(0, len(missing), 10):
                batch = missing[start:start + 10]
                vectors = await self.embed([f"《{c['title']}》 {c['section']}\n{c['text']}" for c in batch])
                for chunk, vector in zip(batch, vectors):
                    cached[chunk["chunk_id"]] = vector
                    db.execute("INSERT OR REPLACE INTO embeddings VALUES(?,?,?)", (namespace, chunk["chunk_id"], vector.tobytes()))
                db.commit()
        self.vectors = np.stack([cached[c["chunk_id"]] for c in self.chunks])
        if self.remote:
            await self.remote.build(self.chunks, self.vectors)
        if self.cfg.listening_kg_enabled:
            from vector_stores import KnowledgeGraph
            await KnowledgeGraph().build(self.chunks)

    async def search(self, query: str, limit=5) -> list[dict]:
        if self.vectors is None:
            raise ValueError("索引尚未就绪")
        titles = {c["title"] for c in self.chunks}
        named = [title for title in titles if title in query]
        explicit = re.findall(r"《([^》]+)》", query)
        if explicit and any(title not in titles for title in explicit):
            return []
        candidates = [i for i, c in enumerate(self.chunks) if not named or c["title"] in named]
        vector = (await self.embed([query]))[0]
        if self.remote:
            matches = await self.remote.search(vector, named)
            scores = {str(item.get("chunk_id", item.get("id"))): float(item["distance"]) for item in matches}
            dense = np.array([scores.get(c["chunk_id"], -1.) for c in self.chunks])
        else:
            dense = self.vectors @ vector
        sparse = self.bm25.get_scores(tokenize(query))
        # 相关性门槛后再融合，避免把全库最不相关的条目也作为引用。
        eligible = [i for i in candidates if dense[i] >= .38]
        if not eligible:
            return []
        dense_order = sorted(eligible, key=lambda i: float(dense[i]), reverse=True)[:15]
        sparse_order = sorted((i for i in eligible if sparse[i] > 0), key=lambda i: float(sparse[i]), reverse=True)[:15]
        fused = {}
        for ordering, weight in [(dense_order, 1.0), (sparse_order, 1.0)]:
            for rank, i in enumerate(ordering, 1):
                fused[i] = fused.get(i, 0) + weight / (60 + rank)
        ordering = sorted(fused, key=fused.get, reverse=True)[:limit]
        return [dict(self.chunks[i], vector_score=round(float(dense[i]), 4),
                     fusion_score=round(fused[i], 6)) for i in ordering]
