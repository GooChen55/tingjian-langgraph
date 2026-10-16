"""听见服务共享配置、认证与项目资源定位。"""
import hmac
import os
from pathlib import Path

import httpx
from fastapi import Header, HTTPException
from pydantic_settings import BaseSettings, SettingsConfigDict
from model_settings import active_connection, check_response, chat_payload
from request_trace import forward_trace

from project_paths import ROOT, RUNTIME


class ServiceSettings(BaseSettings):
    llm_api_key: str = ""
    llm_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    llm_model: str = "qwen-plus"
    listening_model_settings_file: str = ""
    listening_embedding_model: str = "text-embedding-v3"
    listening_embedding_dimensions: int = 1024
    listening_docs: str = str(ROOT / "data" / "knowledge")
    listening_index_db: str = str(RUNTIME / "knowledge.sqlite")
    listening_service_key: str = ""
    listening_reader_password: str = ""
    listening_db_host: str = "127.0.0.1"
    listening_db_port: int = 24316
    listening_reader_user: str = "listening_reader"
    listening_ops_database: str = "listening_ops"
    listening_infrastructure: str = "local"
    listening_es_url: str = ""
    listening_es_enabled: bool = False
    listening_vector_backend: str = "numpy"
    listening_qdrant_enabled: bool = False
    listening_kg_enabled: bool = False
    listening_advanced_rag: bool = False
    listening_rerank_model: str = "gte-rerank-v2"
    listening_mongo_uri: str = ""
    listening_personal_object_backend: str = 'minio'
    listening_personal_vector_backend: str = 'milvus'
    listening_personal_parser_backend: str = 'pypdf'
    model_config = SettingsConfigDict(
        env_file=ROOT / ".env", extra="ignore")


def private_value(name: str, file_name: str) -> str:
    value = os.environ.get(name)
    if value:
        return value
    path = RUNTIME / file_name
    return path.read_text(encoding="utf-8-sig").strip() if path.exists() else ""


def require_service(x_listening_key: str | None = Header(None)):
    expected = private_value("LISTENING_SERVICE_KEY", "service-key")
    if not expected or not x_listening_key or not hmac.compare_digest(expected, x_listening_key):
        raise HTTPException(401, "仅限听书服务访问")


async def model_json(cfg: ServiceSettings, system: str, user: str) -> dict:
    connection = active_connection(cfg)
    if not connection['api_key']:
        raise HTTPException(503, "尚未配置模型密钥")
    try:
        async with httpx.AsyncClient(timeout=45, trust_env=False,event_hooks={'request':[forward_trace]}) as http:
            response = await http.post(connection['base_url'] + "/chat/completions",
                headers={"Authorization": "Bearer " + connection['api_key']},
                json=chat_payload(connection, temperature=0,
                      response_format={"type": "json_object"},
                      messages=[{"role": "system", "content": system},
                                {"role": "user", "content": user}]))
            ensure_model_available(response)
            import json
            value = json.loads(response.json()["choices"][0]["message"]["content"])
            if not isinstance(value, dict):
                raise ValueError("not an object")
            return value
    except (httpx.HTTPError, ValueError, KeyError, TypeError):
        raise HTTPException(502, "模型服务未返回有效结果") from None


def ensure_model_available(response: httpx.Response):
    check_response(response)
