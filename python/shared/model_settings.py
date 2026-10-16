"""Administrator-owned OpenAI-compatible providers. Secrets use Windows user DPAPI."""
import base64
import ctypes
import ipaddress
import json
import os
import tempfile
import threading
from pathlib import Path
from urllib.parse import urlsplit
from project_paths import RUNTIME

import httpx
from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator

PROVIDERS = [
    {"id": "aliyun", "name": "阿里云百炼", "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1", "chat_model": "qwen-plus", "embedding_model": "text-embedding-v3", "dimensions": 1024, "send_dimensions": True},
    {"id": "deepseek", "name": "DeepSeek", "base_url": "https://api.deepseek.com/v1", "chat_model": "deepseek-flash", "embedding_model": None},
    {"id": "siliconflow", "name": "硅基流动", "base_url": "https://api.siliconflow.cn/v1", "chat_model": "deepseek-ai/DeepSeek-V3", "embedding_model": "BAAI/bge-m3", "dimensions": 1024, "send_dimensions": False},
    {"id": "openai", "name": "OpenAI", "base_url": "https://api.openai.com/v1", "chat_model": "gpt-4o-mini", "embedding_model": "text-embedding-3-small", "dimensions": 1536, "send_dimensions": True},
    {"id": "custom", "name": "自定义兼容接口", "base_url": "", "chat_model": "", "embedding_model": "", "dimensions": 1024, "send_dimensions": False},
]


class ModelConnection(BaseModel):
    provider: str
    base_url: str = Field(min_length=8, max_length=500)
    model: str = Field(min_length=1, max_length=150, pattern=r"^[a-zA-Z0-9_./:\-]+$")
    api_key: SecretStr = Field(default=SecretStr(""), max_length=4096)
    dimensions: int = Field(default=1024, ge=1, le=8192)
    send_dimensions: bool = True
    model_config = ConfigDict(extra="forbid", strict=True)

    @field_validator("provider")
    @classmethod
    def provider_known(cls, value):
        if value not in {p["id"] for p in PROVIDERS}:
            raise ValueError("未知供应商")
        return value

    @field_validator("base_url")
    @classmethod
    def valid_url(cls, value):
        value = value.strip().rstrip("/")
        try:
            parsed = urlsplit(value)
            port = parsed.port
            hostname = parsed.hostname
            local = hostname in {"localhost", "127.0.0.1", "::1"}
            if not local:
                try:
                    local = ipaddress.ip_address(hostname).is_loopback
                except ValueError:
                    pass
            if not hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
                raise ValueError()
            if parsed.scheme != "https" and not (parsed.scheme == "http" and local):
                raise ValueError()
            if parsed.path.endswith(("/chat/completions", "/embeddings", "/responses")):
                raise ValueError()
            if port is not None and not 1 <= port <= 65535:
                raise ValueError()
        except (ValueError, TypeError):
            raise ValueError("请填写 HTTPS API 根地址；本地服务可用 HTTP，勿添加 chat/completions 或 embeddings") from None
        return value


class ModelConfiguration(BaseModel):
    chat: ModelConnection
    embedding: ModelConnection
    model_config = ConfigDict(extra="forbid", strict=True)


def protect_secret(value: str, decrypt=False) -> str:
    if os.name != "nt":
        raise HTTPException(503, "本地密钥存储需要 Windows DPAPI；其他系统请使用环境变量")
    from ctypes import wintypes
    class Blob(ctypes.Structure):
        _fields_ = [("size", wintypes.DWORD), ("data", ctypes.POINTER(ctypes.c_ubyte))]
    data = base64.b64decode(value, validate=True) if decrypt else value.encode("utf-8")
    buffer = ctypes.create_string_buffer(data)
    source = Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
    output = Blob()
    crypt = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    function = crypt.CryptUnprotectData if decrypt else crypt.CryptProtectData
    function.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
    function.restype = wintypes.BOOL
    if not function(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(output)):
        raise HTTPException(503, "无法读取或保护模型密钥，请在当前 Windows 账号下重新配置")
    try:
        result = ctypes.string_at(output.data, output.size)
        return result.decode("utf-8") if decrypt else base64.b64encode(result).decode("ascii")
    finally:
        kernel.LocalFree(ctypes.cast(output.data, ctypes.c_void_p))


class ModelStore:
    def __init__(self, path=None):
        self.path = Path(path or os.environ.get("LISTENING_MODEL_SETTINGS_FILE") or RUNTIME / "model-settings.json")
        self.lock = threading.RLock()

    def read(self):
        with self.lock:
            if not self.path.exists():
                return {}
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
                for kind in ("chat", "embedding"):
                    data[kind]["api_key"] = protect_secret(data[kind].pop("protected_key"), decrypt=True)
                return data
            except HTTPException:
                raise
            except (OSError, ValueError, KeyError, TypeError):
                raise HTTPException(503, "模型配置文件损坏，请重新配置") from None

    def effective(self, cfg, kind):
        saved = self.read()
        if kind in saved:
            return saved[kind]
        base = cfg.llm_base_url.rstrip("/")
        provider = next((p["id"] for p in PROVIDERS if p["base_url"] == base), "custom")
        return {"provider": provider, "base_url": base,
                "model": cfg.llm_model if kind == "chat" else getattr(cfg, "listening_embedding_model", "text-embedding-v3"),
                "api_key": cfg.llm_api_key,
                "dimensions": getattr(cfg, "listening_embedding_dimensions", 1024), "send_dimensions": True}

    def public(self, cfg):
        result = {}
        with self.lock:
            for kind in ('chat', 'embedding'):
                connection = self.effective(cfg, kind)
                result[kind] = {**{k: v for k, v in connection.items() if k != 'api_key'},
                                'has_api_key': bool(connection['api_key'])}
        return result

    def candidate(self, cfg, kind, request):
        result = request.model_dump(exclude={"api_key"})
        key = request.api_key.get_secret_value().strip()
        if not key:
            old = self.effective(cfg, kind)
            if (old["provider"], old["base_url"]) == (result["provider"], result["base_url"]):
                key = old["api_key"]
        if not key or any(c.isspace() for c in key):
            raise HTTPException(422, "请填写该供应商的 API Key；切换供应商或接口地址时不能沿用旧密钥")
        if kind == "embedding" and result["provider"] == "deepseek":
            raise HTTPException(422, "请为知识库选择支持 embeddings 的向量供应商")
        return {**result, "api_key": key}

    def save(self, cfg, request):
        with self.lock:
            data = {kind: self.candidate(cfg, kind, getattr(request, kind)) for kind in ("chat", "embedding")}
            for connection in data.values():
                connection["protected_key"] = protect_secret(connection.pop("api_key"))
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = None
            try:
                with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=self.path.parent, delete=False) as file:
                    temporary = Path(file.name)
                    json.dump(data, file, ensure_ascii=False)
                    file.flush()
                    os.fsync(file.fileno())
                os.replace(temporary, self.path)
            finally:
                if temporary and temporary.exists():
                    temporary.unlink()
        return self.public(cfg)


def active_connection(cfg, kind="chat"):
    return ModelStore(getattr(cfg, 'listening_model_settings_file', '') or None).effective(cfg, kind)


def embedding_payload(connection, texts):
    payload = {"model": connection["model"], "input": texts, "encoding_format": "float"}
    if connection["send_dimensions"]:
        payload["dimensions"] = connection["dimensions"]
    return payload


def chat_payload(connection, **parameters):
    """Use the same mode for probes, JSON tasks and the assistant tool loop."""
    payload = {"model": connection["model"], **parameters}
    if urlsplit(connection["base_url"]).hostname == "api.deepseek.com":
        # Official DeepSeek defaults to thinking, which disallows required tools.
        payload["thinking"] = {"type": "disabled"}
    return payload


def check_response(response):
    if response.status_code < 400:
        response.raise_for_status()
        return
    code = None
    try:
        error = response.json().get("error", {})
        code = error.get("code") if isinstance(error, dict) else None
    except (ValueError, AttributeError):
        pass
    if code in {"Arrearage", "insufficient_quota", "insufficient_balance"} or response.status_code == 402:
        raise HTTPException(503, "模型账户余额不足或额度耗尽，请到当前供应商平台检查")
    if response.status_code in {401, 403}:
        raise HTTPException(502, "模型 API Key 无效，或没有模型访问权限")
    if response.status_code == 429:
        raise HTTPException(503, "模型服务限流，请稍后重试或检查供应商额度")
    if response.status_code in {400, 404, 422}:
        raise HTTPException(502, "模型名称、API 地址或请求能力不兼容，请检查配置")
    raise HTTPException(502, "模型供应商服务异常，请稍后重试")


async def test_connection(connection, kind, client):
    stage = "向量响应" if kind == "embedding" else "普通对话"
    async with client() as http:
        async def send(payload, suffix="/chat/completions"):
            response = await http.post(connection["base_url"] + suffix,
                headers={"Authorization": "Bearer " + connection["api_key"]}, json=payload)
            check_response(response)
            return response.json()
        try:
            if kind == "embedding":
                result = await send(embedding_payload(connection, ["听书连接测试"]), "/embeddings")
                vector = result["data"][0]["embedding"]
                import math
                if not isinstance(vector, list):
                    raise ValueError()
                if len(vector) != connection["dimensions"]:
                    raise HTTPException(502, f"向量维度不匹配：配置 {connection['dimensions']} 维，接口实际返回 {len(vector)} 维；请调整维度和 dimensions 参数")
                if not all(type(v) in (int, float) and math.isfinite(v) for v in vector) or not any(vector):
                    raise ValueError()
                return {"ok": True, "message": "向量连接成功，维度匹配", "dimensions": len(vector)}
            async def chat(**parameters):
                result = await send(chat_payload(connection, max_tokens=1024, temperature=0, **parameters))
                if result["choices"][0].get("finish_reason") == "length":
                    raise HTTPException(502, f"{stage}测试输出被截断：达到生成 token 上限，请使用非思考模式或提高输出上限")
                return result
            normal = await chat(messages=[{"role": "user", "content": "只回复 OK"}])
            if not normal["choices"][0]["message"].get("content"):
                raise ValueError()
            stage = "JSON 输出"
            structured = await chat(messages=[{"role": "system", "content": "Output a valid JSON object only."}, {"role": "user", "content": 'Output exactly this JSON object with no additional fields: {"ok": true}'}], response_format={"type": "json_object"})
            if json.loads(structured["choices"][0]["message"]["content"]).get("ok") is not True:
                raise ValueError()
            stage = "工具调用"
            tools = await chat(messages=[{"role": "user", "content": "Call connection_check with ok=true."}], tools=[{"type": "function", "function": {"name": "connection_check", "description": "Test connection", "parameters": {"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"]}}}], tool_choice="required")
            call = tools["choices"][0]["message"]["tool_calls"][0]["function"]
            if call["name"] != "connection_check" or json.loads(call["arguments"]).get("ok") is not True:
                raise ValueError()
            return {"ok": True, "message": "对话、JSON 和工具调用测试均通过"}
        except httpx.TimeoutException:
            raise HTTPException(504, "连接模型服务超时，请检查地址与网络") from None
        except httpx.HTTPError:
            raise HTTPException(502, "无法连接模型服务，请检查地址与网络") from None
        except (ValueError, KeyError, TypeError, IndexError, AttributeError):
            raise HTTPException(502, f"{stage}测试失败：接口未返回预期格式，请检查模型是否支持该能力") from None
