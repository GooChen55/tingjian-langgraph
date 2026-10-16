"""听见管理权限与用户端业务路由；不开放任意 Java 代理。"""
from pathlib import Path
import asyncio
import re
import httpx
from fastapi import Header, HTTPException, Query
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field
from model_settings import ModelStore, ModelConnection, ModelConfiguration, PROVIDERS, test_connection


class Credentials(BaseModel):
    username: str = Field(pattern=r"^[a-zA-Z0-9_]{4,40}$")
    password: str = Field(min_length=10, max_length=128)
    model_config = ConfigDict(extra="forbid", strict=True)


class Review(BaseModel):
    decision: str = Field(pattern=r"^(APPROVED|REJECTED)$")
    note: str = Field(min_length=5, max_length=500)
    model_config = ConfigDict(extra="forbid", strict=True)


class Progress(BaseModel):
    albumId: int = Field(gt=0)
    trackId: int = Field(gt=0)
    breakSecond: float = Field(ge=0, le=86400, allow_inf_nan=False)
    model_config = ConfigDict(extra="forbid")


class AlbumEdit(BaseModel):
    albumTitle: str = Field(min_length=2,max_length=200)
    published: bool
    requestId: str = Field(pattern=r"^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$")
    model_config = ConfigDict(extra="forbid",strict=True)

class Checkout(BaseModel):
    product: str = Field(min_length=1,max_length=40)
    idempotencyKey: str = Field(pattern=r"^[a-zA-Z0-9_-]{16,64}$")
    confirmed: bool
    model_config = ConfigDict(extra="forbid",strict=True)

class SimulatePayment(BaseModel):
    outcome: str = Field(pattern=r"^(SUCCESS|FAILED)$")
    confirmed: bool
    model_config = ConfigDict(extra="forbid",strict=True)

class SimulateRefund(BaseModel):
    scenario: str = Field(pattern=r"^(SUCCESS|FAIL_ONCE|TIMEOUT_ONCE|ALWAYS_FAIL)$")
    confirmed: bool
    model_config = ConfigDict(extra="forbid",strict=True)


def attach_routes(app, cfg, client, identify, business_api, service_headers, integration):
    store = ModelStore(cfg.listening_model_settings_file or None)
    async def java(url, path, method="GET", headers=None, payload=None, params=None):
        from service_discovery import resolve
        kind={cfg.listening_user_url:'user',cfg.listening_content_url:'album',cfg.listening_order_url:'order'}[url]
        url=await resolve(kind,url,cfg.listening_infrastructure)
        try:
            async with client() as http:
                result = await http.request(method, url.rstrip("/") + path, headers=headers or {},
                    **({"json": payload} if payload is not None else {}), params=params)
            if result.status_code in {400,401,403,404,409,410,422,429}:
                raise HTTPException(result.status_code, result.json().get("detail", "业务请求失败"))
            result.raise_for_status()
            body = result.json()
            if body.get("code") == 208:
                raise HTTPException(401,"登录已过期")
            if body.get("code") != 200:
                raise HTTPException(502,"Java 业务服务暂时不可用")
            return body.get("data")
        except (httpx.HTTPError, ValueError, KeyError):
            raise HTTPException(502,"无法连接 Java 业务服务") from None

    @app.get("/admin")
    async def admin_page():
        return FileResponse(integration / "web" / "admin.html")

    @app.post("/api/admin/login")
    async def admin_login(req: Credentials):
        return await java(cfg.listening_user_url,"/api/access/admin/login","POST",payload=req.model_dump())

    @app.get("/api/admin/me")
    async def admin_me(admin_token: str | None = Header(None)):
        return await java(cfg.listening_user_url,"/api/access/admin/me",headers={"admin-token":admin_token or ""})

    from .management import attach_management
    attach_management(app,cfg,admin_me)
    from .personal import attach_personal
    attach_personal(app,cfg,identify,java)

    @app.post("/api/admin/logout")
    async def admin_logout(admin_token: str | None = Header(None)):
        return await java(cfg.listening_user_url,"/api/access/admin/logout","POST",headers={"admin-token":admin_token or ""})

    async def content_admin(admin_token):
        actor=await admin_me(admin_token)
        if 'content:manage' not in actor['permissions']:
            raise HTTPException(403,'没有内容管理权限')
        if cfg.listening_infrastructure!='vm':
            raise HTTPException(503,'内容与索引管理需要虚拟机运行环境')
        return actor

    @app.patch('/api/admin/content/albums/{aid}')
    async def edit_album(aid:int,req:AlbumEdit,admin_token:str|None=Header(None)):
        await content_admin(admin_token)
        return await java(cfg.listening_content_url,'/api/admin/content/albums/'+str(aid),'PATCH',
            headers={'admin-token':admin_token or ''},payload=req.model_dump())

    @app.get('/api/admin/content/albums/{aid}')
    async def admin_album(aid:int,admin_token:str|None=Header(None)):
        await content_admin(admin_token)
        from search_sync import admin_album
        album=await asyncio.to_thread(admin_album,aid)
        if not album:raise HTTPException(404,'专辑不存在')
        return album

    @app.get('/admin/management.js')
    async def management_script():
        return FileResponse(integration/'web/admin-management.js',media_type='text/javascript')

    @app.get('/api/admin/content/index-jobs')
    async def index_jobs(admin_token:str|None=Header(None)):
        await content_admin(admin_token)
        from search_sync import outbox_rows
        return {'records':await asyncio.to_thread(outbox_rows)}

    async def model_admin(admin_token):
        actor = await admin_me(admin_token)
        if 'models:manage' not in actor['permissions']:
            raise HTTPException(403, '没有模型配置权限')
        return actor

    @app.get('/api/admin/models')
    async def models(admin_token: str | None = Header(None)):
        await model_admin(admin_token)
        return {'providers': PROVIDERS, 'configuration': store.public(cfg), 'llm_enabled': cfg.listening_use_llm}

    @app.post('/api/admin/models')
    async def save_models(req: ModelConfiguration, admin_token: str | None = Header(None)):
        await model_admin(admin_token)
        return {'configuration': store.save(cfg, req), 'message': '配置已保存，新请求立即生效'}

    @app.post('/api/admin/models/test/{kind}')
    async def probe_models(kind: str, req: ModelConnection, admin_token: str | None = Header(None)):
        await model_admin(admin_token)
        if kind not in {'chat', 'embedding'}:
            raise HTTPException(404, '未知模型类型')
        connection = store.candidate(cfg, kind, req)
        # Three small compatibility probes at most; no provider response or key is echoed.
        try:
            async with asyncio.timeout(65):
                return await test_connection(connection, kind, client)
        except TimeoutError:
            raise HTTPException(504, '模型兼容性测试超时，请检查地址与网络') from None

    @app.get("/api/admin/after-sales")
    async def admin_requests(page: int = Query(1,ge=1,le=10000), size: int = Query(10,ge=1,le=50),
            status: str | None = None, admin_token: str | None = Header(None)):
        return await java(cfg.listening_order_url,"/api/order/admin/after-sales",headers={"admin-token":admin_token or ""},
            params={"page":page,"size":size,**({"status":status} if status else {})})

    def request_id(value):
        if not isinstance(value,str) or not re.fullmatch(r"[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}",value):
            raise HTTPException(422,"申请编号不正确")
        return value

    @app.post("/api/admin/after-sales/{rid}/review")
    async def review(rid: str, req: Review, admin_token: str | None = Header(None)):
        return await java(cfg.listening_order_url,"/api/order/admin/after-sales/"+request_id(rid)+"/review","POST",
            headers={"admin-token":admin_token or ""},payload=req.model_dump())

    @app.get("/api/admin/after-sales/{rid}/events")
    async def events(rid: str, admin_token: str | None = Header(None)):
        return await java(cfg.listening_order_url,"/api/order/admin/after-sales/"+request_id(rid)+"/events",
            headers={"admin-token":admin_token or ""})

    @app.post("/api/admin/ops/query")
    async def operations(req: dict, admin_token: str | None = Header(None)):
        actor=await admin_me(admin_token)
        if "operations:read" not in actor["permissions"]:
            raise HTTPException(403,"没有运营问数权限")
        text=req.get("text")
        if not set(req).issubset({"text", "run_id"}) or not isinstance(text,str) or not 0<len(text)<=1000:
            raise HTTPException(422,"查询参数不正确")
        run_id=req.get("run_id")
        if run_id is not None:
            run_id=request_id(run_id)
        if not cfg.listening_operations_url:
            raise HTTPException(503,"运营服务未启用")
        try:
            async with client() as http:
                result=await http.post(cfg.listening_operations_url.rstrip("/")+"/query",headers=service_headers(),
                    json={"question":text,"actor_id":str(actor["id"]), **({"run_id":run_id} if run_id else {})})
            if result.status_code in {404,409,410}: raise HTTPException(result.status_code,result.json().get("detail","查询任务不可恢复"))
            if result.status_code==422: raise HTTPException(422,result.json().get("detail","问题不在统计口径内"))
            if result.status_code in {502,503,504}:
                detail = result.json().get('detail')
                if isinstance(detail, str): raise HTTPException(result.status_code, detail)
            result.raise_for_status();return result.json()
        except (httpx.HTTPError,ValueError):raise HTTPException(502,"运营查询失败") from None

    @app.post("/api/account/register")
    async def register(req: Credentials):
        return await java(cfg.listening_user_url,"/api/access/register","POST",payload=req.model_dump())

    @app.post("/api/account/login")
    async def login(req: Credentials):
        return await java(cfg.listening_user_url,"/api/access/login","POST",payload=req.model_dump())

    @app.post("/api/account/logout")
    async def logout(token: str | None = Header(None)):
        await identify(token)
        return await java(cfg.listening_user_url,"/api/access/logout","POST",headers={"token":token})

    @app.get("/api/business/orders/page")
    async def orders(page: int = Query(1,ge=1,le=10000),size: int = Query(10,ge=1,le=50),token: str | None = Header(None)):
        await identify(token);return await business_api(f"orders/page?page={page}&size={size}",token)

    @app.get('/api/business/local/products')
    async def products():
        return await java(cfg.listening_order_url,'/api/order/local/products')

    @app.post('/api/business/local/checkout')
    async def checkout(req: Checkout,token: str | None = Header(None)):
        await identify(token)
        return await java(cfg.listening_order_url,'/api/order/local/checkout','POST',headers={'token':token},payload=req.model_dump())

    @app.get('/api/business/local/orders/{oid}')
    async def local_order(oid: int,token: str | None = Header(None)):
        await identify(token)
        return await java(cfg.listening_order_url,f'/api/order/local/orders/{oid}',headers={'token':token})

    @app.get('/api/business/local/orders/{oid}/events')
    async def local_events(oid: int,token: str | None = Header(None)):
        await identify(token)
        return await java(cfg.listening_order_url,f'/api/order/local/orders/{oid}/events',headers={'token':token})

    @app.post('/api/business/local/orders/{oid}/cancel')
    async def cancel_order(oid: int,token: str | None = Header(None)):
        await identify(token)
        return await java(cfg.listening_order_url,f'/api/order/local/orders/{oid}/cancel','POST',headers={'token':token})

    @app.post('/api/business/local/orders/{oid}/simulate')
    async def simulate_order(oid: int,req: SimulatePayment,token: str | None = Header(None)):
        await identify(token)
        return await java(cfg.listening_order_url,f'/api/order/local/orders/{oid}/simulate','POST',headers={'token':token},payload=req.model_dump())

    @app.get('/api/admin/refunds')
    async def refund_jobs(admin_token: str | None = Header(None)):
        return await java(cfg.listening_order_url,'/api/order/local/admin/refunds',headers={'admin-token':admin_token or ''})

    @app.post('/api/admin/refunds/{rid}')
    async def refund(rid: str,req: SimulateRefund,admin_token: str | None = Header(None)):
        return await java(cfg.listening_order_url,'/api/order/local/admin/refunds/'+request_id(rid),'POST',headers={'admin-token':admin_token or ''},payload=req.model_dump())

    @app.get("/api/business/after-sales/page")
    async def after_sales(page: int = Query(1,ge=1,le=10000),size: int = Query(10,ge=1,le=50),token: str | None = Header(None)):
        await identify(token);return await business_api(f"after-sales/page?page={page}&size={size}",token)

    @app.get("/api/content/albums")
    async def albums(q: str = Query("",max_length=100),page: int = Query(1,ge=1,le=10000),size: int = Query(12,ge=1,le=50),category3: int | None = Query(None,ge=1),
                     sort: str = Query('relevance',pattern=r'^(relevance|popular|newest)$'),
                     payType: str = Query('',pattern=r'^(|0101|0102|0103)$')):
        if not cfg.listening_es_enabled and (sort!='relevance' or payType):
            raise HTTPException(503,'排序与付费类型筛选需要启用本项目的搜索服务')
        if cfg.listening_es_enabled and (q.strip() or sort!='relevance' or payType):
            if (page - 1) * size > 1000:
                raise HTTPException(422, "全文检索请缩小关键词范围")
            from scoped_elasticsearch import ScopedElasticsearch
            filters = ([{'term':{'category3Id':category3}}] if category3 else []) + ([{'term':{'payType':payType}}] if payType else [])
            query = {"bool": {"must": [{"multi_match": {"query": q.strip(),
                "fields": ["albumTitle^3", "albumIntro"], "type": "best_fields"}}] if q.strip() else [{'match_all':{}}],
                "filter": filters}}
            try:
                result = await ScopedElasticsearch(cfg.listening_es_url).search("albums", query,
                    size=size, offset=(page - 1) * size,
                    sort=[{'playCount':'desc'},{'id':'asc'}] if sort=='popular' else [{'createTime':'desc'},{'id':'desc'}] if sort=='newest' else None,
                    aggregations={'categories':{'terms':{'field':'categoryName.keyword','size':10}}},
                    highlight={'pre_tags':['[[['],'post_tags':[']]]'],'fields':{'albumTitle':{'number_of_fragments':0}}})
                ids = [int(hit["_source"]["id"]) for hit in result["hits"]["hits"]]
                # Re-read current publication status in Java before exposing records.
                records = await java(cfg.listening_content_url, "/api/content/albums/search-results",
                                     params={"ids": ",".join(map(str, ids))}) if ids else []
                snippets={int(hit['_source']['id']):hit.get('highlight',{}).get('albumTitle',[''])[0] for hit in result['hits']['hits']}
                for record in records:
                    snippet=snippets.get(record['id'],'')
                    if snippet.replace('[[[','').replace(']]]','')==record['albumTitle']:
                        record['titleParts']=[{'text':part[3:-3] if part.startswith('[[[') and part.endswith(']]]') else part,
                            'match':part.startswith('[[[') and part.endswith(']]]')} for part in re.split(r'(\[\[\[.*?\]\]\])',snippet) if part]
                return {"records": records, "total": result["hits"]["total"]["value"],
                        "page": page, "size": size, "searchBackend": "elasticsearch",
                        'facets':result.get('aggregations',{}).get('categories',{}).get('buckets',[])}
            except (httpx.HTTPError, KeyError, ValueError):
                raise HTTPException(503, "专辑全文检索暂时不可用，请检查本项目索引") from None
        return await java(cfg.listening_content_url,"/api/content/albums",params={"q":q,"page":page,"size":size,**({"category3":category3} if category3 else {})})

    @app.get('/api/content/suggest')
    async def suggestions(q:str=Query(min_length=1,max_length=60)):
        if not cfg.listening_es_enabled:
            return {'records':[]}
        from scoped_elasticsearch import ScopedElasticsearch
        try:
            result=await ScopedElasticsearch(cfg.listening_es_url).search('albums',{'bool':{'should':[
                {'prefix':{'albumTitle.keyword':q}}, {'match_phrase_prefix':{'albumTitle':q}}], 'minimum_should_match':1}},size=6)
            ids=[int(hit['_source']['id']) for hit in result['hits']['hits']]
            records=await java(cfg.listening_content_url,'/api/content/albums/search-results',params={'ids':','.join(map(str,ids))}) if ids else []
            return {'records':[{'id':r['id'],'title':r['albumTitle']} for r in records]}
        except (httpx.HTTPError,KeyError,ValueError):
            raise HTTPException(503,'搜索建议暂时不可用') from None

    @app.get("/api/content/albums/{aid}")
    async def album(aid: int):
        return await java(cfg.listening_content_url,f"/api/content/albums/{aid}")

    @app.get("/api/content/albums/{aid}/tracks")
    async def tracks(aid: int,page: int = Query(1,ge=1,le=10000),size: int = Query(20,ge=1,le=50)):
        return await java(cfg.listening_content_url,f"/api/content/albums/{aid}/tracks",params={"page":page,"size":size})

    @app.get("/api/content/tracks/{tid}")
    async def track(tid: int):
        return await java(cfg.listening_content_url,f"/api/content/tracks/{tid}")

    @app.get("/api/playback/progress/{tid}")
    async def read_progress(tid: int,token: str | None = Header(None)):
        await identify(token)
        return await java(cfg.listening_user_url,f"/api/user/listening/progress/{tid}",headers={"token":token})

    @app.post("/api/playback/progress")
    async def save_progress(req: Progress,token: str | None = Header(None)):
        await identify(token)
        return await java(cfg.listening_user_url,"/api/user/listening/progress","POST",headers={"token":token},payload=req.model_dump())

    @app.get("/api/media/{tid}")
    async def media(tid: int):
        names={900001:"音频声音 - 加肥猫.mp3",900002:"音频声音 - 小毛驴.mp3"}
        if tid not in names:raise HTTPException(404,"本地音频不存在")
        return FileResponse(integration/"data"/"audio"/names[tid],media_type="audio/mpeg")

    # 内容代理只开放这三个只读入口，不提供通配代理。
    @app.get("/api/album/category/getBaseCategoryList")
    async def categories():
        return {"code":200,"data":await java(cfg.listening_content_url,"/api/content/categories")}

    @app.get("/api/search/albumInfo/channel/{category}")
    async def channel(category: int):
        return {"code":200,"data":await java(cfg.listening_content_url,f"/api/content/channel/{category}")}

    @app.get("/api/album/category/findTopBaseCategory3/{category}")
    async def top(category: int):
        return {"code":200,"data":await java(cfg.listening_content_url,f"/api/content/top/{category}")}

    frontend=integration/"frontend"/"uniapp"/"dist"/"h5"
    if frontend.is_dir():
        @app.get("/listen")
        async def listen_redirect():return RedirectResponse("/listen/")
        app.mount("/listen",StaticFiles(directory=frontend,html=True),name="listening-h5")
