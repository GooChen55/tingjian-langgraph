"""Explicit administration routes; every mutation checks current Java RBAC."""
import asyncio
from fastapi import Header,HTTPException,UploadFile,File,Form


def attach_management(app,cfg,admin_me):
    async def authorized(token):
        actor=await admin_me(token)
        if 'knowledge:manage' not in actor['permissions']:
            raise HTTPException(403,'没有知识库管理权限')
        if cfg.listening_infrastructure!='vm':
            raise HTTPException(503,'知识库管理需要项目专属虚拟机环境')
        return actor

    @app.get('/api/admin/knowledge/documents')
    async def documents(admin_token:str|None=Header(None)):
        await authorized(admin_token)
        from knowledge_catalog import documents
        return {'records':await asyncio.to_thread(documents)}

    @app.post('/api/admin/knowledge/documents')
    async def upload(title:str=Form(...,min_length=2,max_length=120),
                     file:UploadFile=File(...),document_id:int|None=Form(None,ge=1),
                     admin_token:str|None=Header(None)):
        actor=await authorized(admin_token)
        from knowledge_catalog import MAX_UPLOAD,enqueue
        content=await file.read(MAX_UPLOAD+1)
        await file.close()
        if len(content)>MAX_UPLOAD:raise HTTPException(413,'文件超过 10 MB')
        return await asyncio.to_thread(enqueue,title,file.filename or '',content,actor['id'],document_id)

    @app.delete('/api/admin/knowledge/documents/{identity}')
    async def remove(identity:int,admin_token:str|None=Header(None)):
        actor=await authorized(admin_token)
        from knowledge_catalog import remove
        return await asyncio.to_thread(remove,identity,actor['id'])

    @app.post('/api/admin/knowledge/documents/{identity}/retry')
    async def retry(identity:int,admin_token:str|None=Header(None)):
        actor=await authorized(admin_token)
        from knowledge_catalog import retry
        return await asyncio.to_thread(retry,identity,actor['id'])
