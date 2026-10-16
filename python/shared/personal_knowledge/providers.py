"""Replaceable object/vector ports. Cloud adapters must keep mandatory scope."""
import hashlib
import asyncio
import io
import json
import os
import re
from typing import Protocol

import httpx
import numpy as np
from fastapi import HTTPException
from knowledge_catalog import object_store,ensure_bucket,BUCKET
from model_settings import active_connection,embedding_payload,check_response
from listening_common import ServiceSettings
from vector_stores import vm_data_credentials
from .repository import owner_id


class ObjectPort(Protocol):
    def put(self,owner,space,key,content:bytes): ...
    def get(self,owner,space,key)->bytes: ...
    def remove(self,owner,space,key): ...


class VectorPort(Protocol):
    async def build(self,owner,space,chunks,vectors): ...
    async def search(self,owner,space,revisions,vector): ...


class ParserPort(Protocol):
    async def parse(self,content:bytes,suffix:str)->str: ...


class LocalParser:
    async def parse(self,content,suffix):
        from app.listening.ingestion import parse_document
        return await asyncio.to_thread(parse_document,content,suffix)


def parser()->ParserPort:
    if ServiceSettings().listening_personal_parser_backend!='pypdf':
        raise HTTPException(503,'尚未安装该个人资料解析适配器')
    return LocalParser()


def valid_space(space):
    if not re.fullmatch(r'[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}',str(space)):
        raise ValueError('Invalid space id')
    return str(space)


class MinioObjects:
    def key(self,owner,space,key):
        prefix=f'personal/{owner_id(owner)}/{valid_space(space)}/'
        if not key.startswith(prefix) or not re.fullmatch(r'[a-f0-9]{32}/[a-f0-9]{64}',key[len(prefix):]):
            raise ValueError('Foreign personal object')
        return key
    def put(self,owner,space,key,content):
        key=self.key(owner,space,key);store=object_store();ensure_bucket(store)
        store.put_object(BUCKET,key,io.BytesIO(content),len(content),content_type='application/octet-stream')
    def get(self,owner,space,key):
        response=object_store().get_object(BUCKET,self.key(owner,space,key))
        try:
            data=response.read(10*1024*1024+1)
            if len(data)>10*1024*1024:raise ValueError('PersonalObjectTooLarge')
            return data
        finally:response.close();response.release_conn()
    def remove(self,owner,space,key):object_store().remove_object(BUCKET,self.key(owner,space,key))


def embedding_connection():return active_connection(ServiceSettings(),'embedding')


def model_key(connection):
    return hashlib.sha256(json.dumps([connection['base_url'],connection['model'],connection['dimensions']]).encode()).hexdigest()


async def embed(texts,connection):
    if not connection['api_key']:raise HTTPException(503,'请先配置向量模型，或关闭空间的云模型处理')
    values=[]
    async with httpx.AsyncClient(timeout=45,trust_env=False) as http:
        for start in range(0,len(texts),10):
            batch=texts[start:start+10]
            response=await http.post(connection['base_url']+'/embeddings',headers={'Authorization':'Bearer '+connection['api_key']},json=embedding_payload(connection,batch))
            check_response(response)
            rows=sorted(response.json()['data'],key=lambda row:row['index'])
            matrix=np.array([row['embedding'] for row in rows],dtype=np.float32)
            if matrix.shape!=(len(batch),connection['dimensions']) or not np.isfinite(matrix).all():raise ValueError('InvalidPersonalEmbedding')
            norms=np.linalg.norm(matrix,axis=1,keepdims=True)
            if np.any(norms==0):raise ValueError('EmptyPersonalEmbedding')
            values.extend((matrix/norms).tolist())
    return values


def scoped_filter(owner,space,revisions):
    base='owner_id == '+json.dumps(str(owner_id(owner)))+' and space_id == '+json.dumps(valid_space(space))
    clauses=[]
    for identity,revision in revisions:
        if not str(identity).isdigit() or not re.fullmatch('[a-f0-9]{64}',revision):raise ValueError('Invalid active version')
        clauses.append('(item_id == '+json.dumps(str(identity))+' and revision == '+json.dumps(revision)+')')
    if not clauses:raise ValueError('No authorized versions')
    return base+' and ('+' or '.join(clauses)+')'


class MilvusVectors:
    def __init__(self,connection,transport=None):
        cfg=vm_data_credentials();self.url=f"http://{cfg['host']}:39530"
        self.token='root:'+cfg['milvus_password'];self.connection=connection;self.transport=transport
        self.collection='aillisten_dev_personal_'+model_key(connection)[:12]
    async def call(self,operation,payload=None):
        if not re.fullmatch('aillisten_dev_personal_[a-f0-9]{12}',self.collection):raise ValueError('Foreign personal collection')
        async with httpx.AsyncClient(base_url=self.url,timeout=45,trust_env=False,transport=self.transport,headers={'Authorization':'Bearer '+self.token}) as http:
            response=await http.post('/v2/vectordb/'+operation,json={'collectionName':self.collection,**(payload or {})})
            response.raise_for_status();result=response.json()
            if result.get('code')!=0:raise ValueError('PersonalVectorStoreError')
            return result.get('data',{})
    async def build(self,owner,space,chunks,vectors):
        if not chunks:return
        if any(c['owner_id']!=str(owner_id(owner)) or c['space_id']!=valid_space(space) for c in chunks):raise ValueError('Foreign private chunk')
        if not (await self.call('collections/has')).get('has'):
            try:
                await self.call('collections/create',{'dimension':self.connection['dimensions'],'primaryFieldName':'chunk_id','idType':'VarChar','autoID':False,'vectorFieldName':'vector','metricType':'COSINE','params':{'max_length':64,'enableDynamicField':True,'consistencyLevel':'Strong'}})
            except ValueError:
                if not (await self.call('collections/has')).get('has'):raise
        for start in range(0,len(chunks),20):
            await self.call('entities/upsert',{'data':[{**c,'vector':v} for c,v in zip(chunks[start:start+20],vectors[start:start+20])]})
        await self.call('collections/load')
    async def search(self,owner,space,revisions,vector):
        expression=scoped_filter(owner,space,revisions)
        if not (await self.call('collections/has')).get('has'):return []
        return await self.call('entities/search',{'data':[vector],'annsField':'vector','filter':expression,'limit':30,'outputFields':['chunk_id'],'consistencyLevel':'Strong'})


def objects()->ObjectPort:
    if ServiceSettings().listening_personal_object_backend!='minio':
        raise HTTPException(503,'尚未安装该个人知识库对象存储适配器')
    return MinioObjects()


def vectors(connection)->VectorPort:
    if ServiceSettings().listening_personal_vector_backend!='milvus':
        raise HTTPException(503,'尚未安装该个人知识库向量适配器')
    return MilvusVectors(connection)
