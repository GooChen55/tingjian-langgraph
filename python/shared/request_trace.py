"""Bounded local AI admission and trace IDs; never log prompts, bodies or credentials."""
import asyncio
import hashlib
import json
import logging
import re
import time
import uuid
from collections import deque
from contextvars import ContextVar

from starlette.responses import JSONResponse

trace_id = ContextVar('listening_trace_id', default='')


async def forward_trace(request):
    value = trace_id.get()
    if value:
        request.headers['x-request-id'] = value


class RequestTraceMiddleware:
    def __init__(self, app, service, rate_limit=30, capacity=4, timeout=120, window=60):
        self.app, self.service = app, service
        self.rate_limit, self.capacity, self.timeout, self.window = rate_limit, capacity, timeout, window
        self.active = 0
        self.buckets = {}
        self.last_prune = 0

    def guarded(self, path):
        return path in {'/api/assistant/chat','/api/assistant/chat/stream', '/api/assistant/tasks', '/api/admin/ops/query', '/query'} or path.startswith('/api/admin/models/test/') or (path.startswith('/api/personal/spaces/') and path.endswith('/query'))

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            return await self.app(scope, receive, send)
        headers = dict(scope.get('headers', []))
        submitted = headers.get(b'x-request-id', b'').decode('ascii', errors='ignore')
        rid = submitted if re.fullmatch(r'[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}', submitted) else str(uuid.uuid4())
        context = trace_id.set(rid)
        started, status, response_started, admitted = time.monotonic(), 500, False, False
        async def traced_send(message):
            nonlocal status, response_started
            if message['type'] == 'http.response.start':
                response_started = True
                status = message['status']
                message['headers'] = list(message.get('headers', [])) + [(b'x-request-id', rid.encode())]
            await send(message)
        async def reject(code, detail):
            response = JSONResponse({'detail': detail, 'request_id': rid}, status_code=code,
                headers={'Retry-After': '5'} if code == 429 else {})
            await response(scope, receive, traced_send)
        try:
            protected = self.guarded(scope['path']) and scope['method'] == 'POST'
            if protected:
                current = time.monotonic()
                if current - self.last_prune > 1:
                    self.buckets = {k: v for k, v in self.buckets.items() if v and current-v[-1] < self.window}
                    self.last_prune = current
                credential = headers.get(b'admin-token') or headers.get(b'token') or headers.get(b'x-listening-key') or str(scope.get('client')).encode()
                bucket_key = hashlib.sha256(credential).digest()
                if bucket_key not in self.buckets and len(self.buckets) >= 4096:
                    return await reject(429, '请求过多，请稍后重试')
                bucket = self.buckets.setdefault(bucket_key, deque())
                while bucket and current-bucket[0] >= self.window:
                    bucket.popleft()
                if len(bucket) >= self.rate_limit or self.active >= self.capacity:
                    return await reject(429, 'AI 请求过于频繁或服务繁忙，请稍后重试')
                bucket.append(current)
                self.active += 1
                admitted = True
                try:
                    async with asyncio.timeout(self.timeout):
                        await self.app(scope, receive, traced_send)
                except TimeoutError:
                    if response_started:
                        raise
                    await reject(504, 'AI 请求处理超时，请重试；失败请求不会写入对话历史')
            else:
                await self.app(scope, receive, traced_send)
        finally:
            if admitted:
                self.active -= 1
            route = scope.get('route')
            logging.getLogger('uvicorn.error').info(json.dumps({'service': self.service,
                'request_id': rid, 'method': scope['method'], 'route': getattr(route, 'path', 'unmatched'),
                'status': status, 'duration_ms': round((time.monotonic()-started)*1000)}, ensure_ascii=False))
            trace_id.reset(context)
