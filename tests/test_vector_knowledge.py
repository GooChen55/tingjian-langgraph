import asyncio
import json

import httpx

from app.listening.index import VectorIndex, split_documents
from app.listening.service import validate_evidence
from listening_common import ServiceSettings


def test_sections_code_fence_and_stable_ids(tmp_path):
    (tmp_path / "三体简介.md").write_text("## 内容正文\n科幻文明故事。\n```text\n## 代码不是章节\n```\n## 用户评论摘要\n读者喜欢宏大设定。", encoding="utf-8")
    first = split_documents(str(tmp_path))
    assert [c["section"] for c in first] == ["内容正文", "用户评论摘要"]
    assert first == split_documents(str(tmp_path))
    assert "读者喜欢" in first[-1]["text"]


def test_embedding_cache_and_document_changes(tmp_path):
    docs = tmp_path / "docs"
    docs.mkdir()
    file = docs / "三体简介.md"
    file.write_text("## 内容正文\n科幻文明故事。", encoding="utf-8")
    calls = []
    def embedding(request):
        texts = json.loads(request.content)["input"]
        calls.extend(texts)
        return httpx.Response(200, json={"data": [{"index": i, "embedding": [1, 0, 0]} for i, _ in enumerate(texts)]})
    cfg = ServiceSettings(_env_file=None, listening_docs=str(docs), listening_index_db=str(tmp_path / "index.db"), listening_embedding_dimensions=3)
    index = VectorIndex(cfg, httpx.MockTransport(embedding))
    asyncio.run(index.build())
    assert len(calls) == 1
    asyncio.run(VectorIndex(cfg, httpx.MockTransport(embedding)).build())
    assert len(calls) == 1
    file.write_text("## 内容正文\n新的科幻文明故事。", encoding="utf-8")
    asyncio.run(VectorIndex(cfg, httpx.MockTransport(embedding)).build())
    assert len(calls) == 2


def test_unknown_explicit_book_returns_no_results(tmp_path):
    (tmp_path / "三体简介.md").write_text("## 内容正文\n科幻文明故事。", encoding="utf-8")
    cfg = ServiceSettings(_env_file=None, listening_docs=str(tmp_path))
    index = VectorIndex(cfg)
    import numpy as np
    index.vectors = np.ones((1, cfg.listening_embedding_dimensions))
    assert asyncio.run(index.search("《不存在的书》讲什么")) == []


def test_evidence_must_be_an_exact_quote_from_the_named_chunk():
    doc = {"chunk_id": "known", "text": "这里是资料中的完整原文依据，不可以编造。"}
    valid = {"chunk_id": "known", "quote": "资料中的完整原文依据"}
    forged = {"chunk_id": "known", "quote": "作者获得了未提到的奖项"}
    wrong = {"chunk_id": "other", "quote": valid["quote"]}
    assert len(validate_evidence({"evidence": [valid, forged, wrong]}, [doc])) == 1
