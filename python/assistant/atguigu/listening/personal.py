"""Personal API: Java authenticates; every repository/provider call is scoped."""
import asyncio
import hashlib
import re
from pathlib import Path
from typing import Literal
from urllib.parse import quote
from uuid import UUID

from fastapi import Header,HTTPException,UploadFile,File,Form,Response
from pydantic import BaseModel,ConfigDict,Field,model_validator

from personal_knowledge import repository as repo


class SpaceCreate(BaseModel):
    name:str=Field(min_length=2,max_length=80)
    model_config=ConfigDict(extra='forbid')


class SpaceSettings(BaseModel):
    ai_enabled:bool=Field(strict=True)
    model_config=ConfigDict(extra='forbid')


class Item(BaseModel):
    kind:Literal['NOTE','BOOKMARK']='NOTE'
    title:str=Field(min_length=2,max_length=120)
    content:str=Field(default='',max_length=10000)
    album_id:int|None=Field(default=None,gt=0)
    track_id:int|None=Field(default=None,gt=0)
    anchor_second:float|None=Field(default=None,ge=0,le=86400,allow_inf_nan=False)
    model_config=ConfigDict(extra='forbid')
    @model_validator(mode='after')
    def shape(self):
        if not self.title.strip():raise ValueError('标题不能为空')
        if self.kind=='NOTE' and not self.content.strip():raise ValueError('笔记内容不能为空')
        if self.kind=='BOOKMARK' and self.track_id is None:raise ValueError('书签需要关联声音')
        if self.track_id is None and (self.album_id is not None or self.anchor_second is not None):raise ValueError('时间点需要关联声音')
        return self


class Question(BaseModel):
    question:str=Field(min_length=1,max_length=2000)
    model_config=ConfigDict(extra='forbid')


class Segment(BaseModel):
    session_id:UUID
    sequence:int=Field(ge=0,le=100000)
    album_id:int=Field(gt=0)
    track_id:int=Field(gt=0)
    start:float=Field(ge=0,le=86400,allow_inf_nan=False)
    end:float=Field(gt=0,le=86400,allow_inf_nan=False)
    elapsed:float=Field(gt=0,le=60,allow_inf_nan=False)
    model_config=ConfigDict(extra='forbid')
    @model_validator(mode='after')
    def interval(self):
        if self.end<=self.start or self.end-self.start>30 or self.end-self.start>self.elapsed+1:
            raise ValueError('只上报连续播放的区间，拖动或大跨度跳转不能当作已听')
        return self


def attach_personal(app,cfg,identify,java):
    async def actor(token):
        owner,_=await identify(token)
        if cfg.listening_infrastructure!='vm':raise HTTPException(503,'个人知识空间需要项目专属虚拟机环境')
        return owner
    async def linked(data):
        if data.get('track_id') is not None:
            track=await java(cfg.listening_content_url,'/api/content/tracks/'+str(data['track_id']))
            if data.get('album_id') is not None and int(track['albumId'])!=data['album_id']:raise HTTPException(422,'声音与专辑不匹配')
            data['album_id']=int(track['albumId'])
            duration=float(track.get('mediaDuration') or 0)
            if duration>0 and data.get('anchor_second') is not None and data['anchor_second']>duration:raise HTTPException(422,'时间点超出声音时长')
        return data
    @app.get('/api/personal/spaces')
    async def spaces(token:str|None=Header(None)):
        owner=await actor(token)
        return {'records':await asyncio.to_thread(repo.spaces,owner),'object_backend':'minio','vector_backend':'milvus','ai_default':False}
    @app.post('/api/personal/spaces')
    async def create(req:SpaceCreate,token:str|None=Header(None)):
        return await asyncio.to_thread(repo.create_space,await actor(token),req.name)
    @app.patch('/api/personal/spaces/{space}')
    async def settings(space:UUID,req:SpaceSettings,token:str|None=Header(None)):
        return await asyncio.to_thread(repo.settings,await actor(token),str(space),req.ai_enabled)
    @app.get('/api/personal/spaces/{space}/items')
    async def items(space:UUID,token:str|None=Header(None)):
        scope,rows=await asyncio.to_thread(repo.items,await actor(token),str(space))
        allowed=['id','kind','title','content','filename','album_id','track_id','anchor_second','revision','active_revision','status','error_code','updated_at']
        return {'space':scope,'records':[{key:row[key] for key in allowed} for row in rows]}
    @app.post('/api/personal/spaces/{space}/items')
    async def save(space:UUID,req:Item,token:str|None=Header(None)):
        owner=await actor(token)
        await asyncio.to_thread(repo.items,owner,str(space))
        return await asyncio.to_thread(repo.save,owner,str(space),await linked(req.model_dump()))
    @app.patch('/api/personal/spaces/{space}/items/{identity}')
    async def update(space:UUID,identity:int,req:Item,token:str|None=Header(None)):
        owner=await actor(token)
        await asyncio.to_thread(repo.get_item,owner,str(space),identity)
        return await asyncio.to_thread(repo.save,owner,str(space),await linked(req.model_dump()),identity)
    @app.delete('/api/personal/spaces/{space}/items/{identity}')
    async def remove(space:UUID,identity:int,token:str|None=Header(None)):
        return await asyncio.to_thread(repo.delete,await actor(token),str(space),identity)
    @app.post('/api/personal/spaces/{space}/items/{identity}/retry')
    async def retry(space:UUID,identity:int,token:str|None=Header(None)):
        return await asyncio.to_thread(repo.retry,await actor(token),str(space),identity)
    @app.post('/api/personal/spaces/{space}/documents')
    async def upload(space:UUID,title:str=Form(...,min_length=2,max_length=120),file:UploadFile=File(...),identity:int|None=Form(None,ge=1),token:str|None=Header(None)):
        owner=await actor(token)
        try:
            await asyncio.to_thread(repo.items,owner,str(space))
            if identity:await asyncio.to_thread(repo.get_item,owner,str(space),identity)
            suffix=Path(file.filename or '').suffix.lower()
            if suffix not in {'.md','.txt','.pdf'}:raise HTTPException(422,'支持 MD、TXT 和文字 PDF')
            content=await file.read(10*1024*1024+1)
            if not content or len(content)>10*1024*1024:raise HTTPException(413,'文件须为1字节至10 MB')
            if not 2<=len(title.strip())<=120:raise HTTPException(422,'标题须为2–120字')
            return await asyncio.to_thread(repo.save,owner,str(space),{'kind':'DOCUMENT','title':title.strip(),'filename':Path(file.filename).name[:240]},identity,content)
        finally:await file.close()
    @app.get('/api/personal/spaces/{space}/documents/{identity}/download')
    async def download(space:UUID,identity:int,token:str|None=Header(None)):
        owner=await actor(token);row=await asyncio.to_thread(repo.get_item,owner,str(space),identity)
        if row['kind']!='DOCUMENT':raise HTTPException(404,'文件不存在')
        from personal_knowledge.providers import objects
        raw=await asyncio.to_thread(objects().get,owner,str(space),row['object_key'])
        return Response(raw,media_type='application/octet-stream',headers={'Content-Disposition':"attachment; filename*=UTF-8''"+quote(row['filename'],safe=''),'Cache-Control':'no-store'})
    async def personal_answer(owner,space,question):
        if re.search(r'听书(?:记录|回顾|复习)|(?:我|最近).{0,8}(?:听过|听了|收听了)',question):
            result=await review_data(owner,space)
            lines=[];sources=[]
            for i,track in enumerate(result['records'],1):
                quote_text=f"上报播放区间覆盖 {track['covered_seconds']} 秒，最近保存位置 {track.get('resume_second',0)} 秒。"
                lines.append(f"[L{i}] {track['title']}：{quote_text}")
                sources.append({'citation':'L'+str(i),'title':track['title'],'source':'personal-listening:'+str(track['track_id']),
                    'chunk_id':hashlib.sha256((str(owner)+str(track['track_id'])+quote_text).encode()).hexdigest()[:32],
                    'quote':quote_text,'kind':'LISTENING','space_id':space,'item_id':None,
                    'link':{'track_id':track['track_id'],'album_id':track['album_id'],'anchor_second':track.get('resume_second',0)}})
            if result['review_questions']:
                lines.append('\n可复习的个人笔记：')
                for note in result['review_questions']:lines.append(note['title']+'：'+note['question']+'\n原文：'+note['evidence'])
            text=('你的听书回顾：\n\n'+'\n'.join(lines) if lines else '你目前还没有可回顾的播放记录或笔记。')+'\n\n'+result['basis']+'\n'+result['content_boundary']
            return {'text':text,'sources':sources,'mode':'private-listening','graph_trace':['personal_route','listening_review','grounded_review'],'scope':'personal','space_id':space,'web_enabled':False,'grounded':bool(lines)}
        from personal_knowledge.engine import query
        return await query(owner,space,question)
    app.state.personal_answer=personal_answer

    @app.post('/api/personal/spaces/{space}/query')
    async def query(space:UUID,req:Question,token:str|None=Header(None)):
        return await personal_answer(await actor(token),str(space),req.question)
    @app.post('/api/personal/listening/segments')
    async def segment(req:Segment,token:str|None=Header(None)):
        owner=await actor(token)
        # Validate using Java's playable content endpoint. An asynchronously
        # received old segment must never overwrite the current resume position.
        await linked({'album_id':req.album_id,'track_id':req.track_id,'anchor_second':req.end})
        from personal_knowledge.listening import save_segment
        return await asyncio.to_thread(save_segment,owner,req.model_dump(mode='json'))
    async def review_data(owner,space):
        _,rows=await asyncio.to_thread(repo.items,owner,str(space),True)
        from personal_knowledge.listening import review
        result=await asyncio.to_thread(review,owner)
        for track in result['records']:
            try:
                detail=await java(cfg.listening_content_url,'/api/content/tracks/'+str(track['track_id']))
                track['title']=detail['trackTitle']
            except HTTPException:track['title']='声音 '+str(track['track_id'])+'（当前不可浏览）'
            track['notes']=[{'id':r['id'],'title':r['active_title'],'excerpt':r['active_text'][:300]} for r in rows if r['track_id']==track['track_id'] and r['kind']=='NOTE'][:5]
        result['review_questions']=[{'item_id':r['id'],'title':r['active_title'],'question':'回看这条笔记，尝试用自己的话解释其中的观点。','evidence':r['active_text'][:300]} for r in rows if r['kind']=='NOTE'][:5]
        result['content_boundary']='播放记录不包含书籍正文。当前回顾依据播放区间与个人笔记，不生成无文字依据的章节总结。'
        return result
    @app.get('/api/personal/spaces/{space}/review')
    async def review(space:UUID,token:str|None=Header(None)):
        return await review_data(await actor(token),str(space))
