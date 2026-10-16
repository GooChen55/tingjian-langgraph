"""LangGraph import: parse -> normalize -> split -> label -> embed -> publish."""
import asyncio
import io
import json
import os
import re
from typing import TypedDict

import pymysql
from langgraph.graph import StateGraph, START, END
from pypdf import PdfReader

from knowledge_catalog import object_store,BUCKET,artifact_path
from search_sync import connection
from listening_common import ServiceSettings
from .index import VectorIndex,split_documents


def parse_document(content, suffix):
    if suffix == '.pdf':
        if not content.startswith(b'%PDF-'):
            raise ValueError('InvalidPdf')
        reader=PdfReader(io.BytesIO(content))
        if reader.is_encrypted or len(reader.pages)>40:
            raise ValueError('PdfEncryptedOrOver40Pages')
        text='\n\n'.join(page.extract_text() or '' for page in reader.pages)
        if len(text.strip())<20:
            raise ValueError('ScannedPdfNeedsOcr')
    else:
        text=content.decode('utf-8-sig')
    if not text.strip() or len(text)>60000:
        raise ValueError('DocumentEmptyOrOver60000Characters')
    return text.replace('\r\n','\n').replace('\x00','')


class ImportState(TypedDict,total=False):
    document:dict
    content:bytes
    text:str
    path:str
    chunks:int
    sections:list


async def process_document(identity):
    # Serializes only this project's catalog publication; never takes a global lock.
    with connection(autocommit=True,cursorclass=pymysql.cursors.DictCursor) as lockdb:
        with lockdb.cursor() as cur:
            cur.execute("SELECT GET_LOCK('aillisten.dev.knowledge-publication',5) AS acquired")
            if cur.fetchone()['acquired']!=1:
                raise RuntimeError('KnowledgePublicationBusy')
        try:
            with lockdb.cursor() as cur:
                cur.execute('SELECT * FROM knowledge_document WHERE id=%s',(identity,))
                document=cur.fetchone()
            if not document:
                raise ValueError('UnknownKnowledgeDocument')
            if document['deleted']:
                with lockdb.cursor() as cur:
                    cur.execute("UPDATE knowledge_document SET status='DELETED',active_revision=NULL,active_path=NULL,error_code=NULL,updated_at=UTC_TIMESTAMP(6) WHERE id=%s AND deleted=1",(identity,))
                return
            trace=[]
            def record(node,details=None):
                trace.append({'node':node,**(details or {})})
                with lockdb.cursor() as cur:
                    cur.execute("UPDATE knowledge_document SET status='PROCESSING',trace_json=%s,updated_at=UTC_TIMESTAMP(6) WHERE id=%s AND desired_revision=%s AND deleted=0",(json.dumps(trace),identity,document['desired_revision']))
            async def entry(state):
                def read():
                    response=object_store().get_object(BUCKET,document['object_key'])
                    try:return response.read(10*1024*1024+1)
                    finally:response.close();response.release_conn()
                content=await asyncio.to_thread(read)
                record('load_original')
                return {'content':content}
            def parse(state):
                suffix='.'+document['object_key'].rsplit('.',1)[-1]
                text=parse_document(state['content'],suffix)
                record('parse_document',{'parser':'pypdf' if suffix=='.pdf' else 'utf8'})
                return {'text':text}
            def normalize(state):
                # Preserve captions but never fetch untrusted links or execute embedded HTML.
                text=re.sub(r'!\[([^\]]*)\]\([^)]*\)',r'[图片说明：\1]',state['text'])
                record('normalize_markdown')
                path=artifact_path(str(identity)+'/'+document['desired_revision']+'.md')
                path.parent.mkdir(parents=True,exist_ok=True)
                temp=path.with_suffix('.tmp')
                temp.write_text(text,encoding='utf-8');os.replace(temp,path)
                return {'text':text,'path':str(path)}
            def split(state):
                chunks=split_documents('',entries=[{'path':state['path'],'title':document['title'],'source':f"uploaded:{identity}:{document['desired_revision'][:12]}"}])
                if not chunks:raise ValueError('NoDocumentChunks')
                record('split_sections',{'chunks':len(chunks)})
                return {'chunks':len(chunks),'sections':sorted({c['section'] for c in chunks})}
            def label(state):
                record('grounded_labels',{'title':document['title'],'sections':state['sections'][:30]})
                return {}
            async def embed(state):
                cfg=ServiceSettings()
                extra={'path':state['path'],'title':document['title'],'source':f"uploaded:{identity}:{document['desired_revision'][:12]}",'document_id':identity}
                candidate=await asyncio.to_thread(VectorIndex,cfg,extra_documents=[extra],exclude_document_id=identity)
                await candidate.build()
                record('embedding_and_index',{'backend':cfg.listening_vector_backend,'chunks':state['chunks']})
                return {}
            def publish(state):
                content=state['text'].encode()
                object_store().put_object(BUCKET,document['object_key']+'.parsed.md',io.BytesIO(content),len(content),content_type='text/markdown')
                relative=str(identity)+'/'+document['desired_revision']+'.md'
                trace.append({'node':'publish','status':'active'})
                with lockdb.cursor() as cur:
                    cur.execute("UPDATE knowledge_document SET active_revision=desired_revision,active_path=%s,status='ACTIVE',error_code=NULL,trace_json=%s,updated_at=UTC_TIMESTAMP(6) WHERE id=%s AND desired_revision=%s AND deleted=0",(relative,json.dumps(trace),identity,document['desired_revision']))
                return {}
            graph=StateGraph(ImportState)
            steps=[('load',entry),('parse',parse),('normalize',normalize),('split',split),('labels',label),('embed',embed),('publish',publish)]
            last=START
            for name,fn in steps:graph.add_node(name,fn);graph.add_edge(last,name);last=name
            graph.add_edge(last,END)
            try:await graph.compile().ainvoke({'document':document})
            except Exception as exc:
                with lockdb.cursor() as cur:
                    cur.execute("UPDATE knowledge_document SET status='FAILED',error_code=%s,trace_json=%s,updated_at=UTC_TIMESTAMP(6) WHERE id=%s AND desired_revision=%s AND deleted=0",(type(exc).__name__+':'+str(exc)[:70] if isinstance(exc,ValueError) else type(exc).__name__,json.dumps(trace),identity,document['desired_revision']))
                raise
        finally:
            with lockdb.cursor() as cur:cur.execute("SELECT RELEASE_LOCK('aillisten.dev.knowledge-publication')")
