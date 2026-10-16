"""Private external integration settings; credentials use Windows DPAPI."""
import hashlib
import json
from urllib.parse import urlsplit

import httpx
from fastapi import HTTPException

from project_paths import RUNTIME
from model_settings import protect_secret, active_connection, check_response


def external_settings():
    file = RUNTIME / "external-providers.json"
    if not file.exists():
        return {}
    value = json.loads(file.read_text(encoding="utf-8"))
    return {key.removesuffix('_encrypted'): protect_secret(item, decrypt=True)
            if key.endswith('_encrypted') else item for key, item in value.items()}


async def rerank(question, docs, cfg):
    if not docs:
        return []
    conn = active_connection(cfg, 'embedding')
    if urlsplit(conn['base_url']).hostname != 'dashscope.aliyuncs.com':
        raise HTTPException(503, "当前重排接口需要百炼模型连接，请配置对应供应商")
    async with httpx.AsyncClient(timeout=30, trust_env=False) as http:
        response = await http.post('https://dashscope.aliyuncs.com/api/v1/services/rerank/text-rerank/text-rerank',
            headers={'Authorization': 'Bearer ' + conn['api_key']}, json={
                'model': cfg.listening_rerank_model,
                'input': {'query': question, 'documents': [d['text'][:4000] for d in docs]},
                'parameters': {'top_n': min(5, len(docs)), 'return_documents': False}})
        check_response(response)
        values = response.json().get('output', {}).get('results', [])
        selected = []
        seen = set()
        for result in values:
            i, score = result.get('index'), result.get('relevance_score')
            if not isinstance(i, int) or i < 0 or i >= len(docs) or i in seen:
                raise ValueError("Invalid reranking index")
            if not isinstance(score, (int, float)) or not 0 <= score <= 1:
                raise ValueError("Invalid reranking score")
            seen.add(i)
            selected.append({**docs[i], 'rerank_score': score})
        return selected


async def web_search(question):
    settings = external_settings()
    from listening_common import ServiceSettings
    connection=active_connection(ServiceSettings(),'embedding')
    url=settings.get('mcp_url','https://dashscope.aliyuncs.com/api/v1/mcps/WebSearch/mcp')
    key=settings.get('mcp_key') or (connection['api_key'] if urlsplit(connection['base_url']).hostname=='dashscope.aliyuncs.com' else '')
    if not url or not key:
        raise HTTPException(503, "尚未配置本项目的联网搜索 MCP")
    # Only an operator-configured endpoint is used. Never follow page URLs.
    from mcp import ClientSession
    from mcp.client.sse import sse_client
    from mcp.client.streamable_http import streamablehttp_client
    def client_factory(headers=None, timeout=None, auth=None):
        return httpx.AsyncClient(headers=headers, timeout=timeout, auth=auth,
                                  trust_env=False, follow_redirects=False)
    try:
        connector=streamablehttp_client if url.endswith('/mcp') else sse_client
        authorization=key if key.startswith('Bearer ') else 'Bearer '+key
        async with connector(url, headers={'Authorization': authorization}, timeout=15,
            sse_read_timeout=30, httpx_client_factory=client_factory) as streams:
            async with ClientSession(*streams[:2]) as session:
                await session.initialize()
                available=await session.list_tools()
                tool=next((t for t in available.tools if t.name=='bailian_web_search'),None)
                if tool is None:raise ValueError('Web search tool not available')
                properties=tool.inputSchema.get('properties',{})
                arguments={'query':question}
                if 'count' in properties:arguments['count']=5
                result = await session.call_tool(tool.name, arguments)
                if result.isError:
                    raise ValueError('MCP tool failed')
                pages = []
                for content in result.content:
                    if getattr(content, 'type', '') == 'text':
                        payload=json.loads(content.text)
                        pages.extend(payload.get('pages',payload.get('data',{}).get('pages',[])))
        docs = []
        for page in pages[:5]:
            source = page.get('url', '')
            text = page.get('snippet', '')
            if urlsplit(source).scheme not in {'http', 'https'} or not isinstance(text, str) or len(text) < 8:
                continue
            docs.append({'chunk_id': 'web-' + hashlib.sha256((source + text).encode()).hexdigest()[:20],
                'title': str(page.get('title') or '网页搜索结果')[:200], 'source': source,
                'section': '联网搜索摘要', 'text': text[:4000], 'vector_score': 0., 'source_type': 'web'})
        return docs
    except HTTPException:
        raise
    except Exception:
        # SDK errors may contain the configured URL or credentials.
        raise HTTPException(502, '联网搜索 MCP 调用失败，请检查私有配置') from None
