"""Config-driven, owner-bound customer tasks with durable LangGraph interrupts."""
import json
import re
import sqlite3
import time
import uuid
from typing import TypedDict,Literal

import yaml
from fastapi import Header,HTTPException
from pydantic import BaseModel,ConfigDict,Field
from langgraph.graph import StateGraph,START,END
from langgraph.types import interrupt,Command
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from project_paths import ROOT,RUNTIME

FLOW=yaml.safe_load((ROOT/'config/customer_flows.yaml').read_text(encoding='utf-8'))['after_sales']


class TaskRequest(BaseModel):
    action:Literal['start','reply','confirm','pause','resume','cancel']='start'
    task_id:str|None=Field(None,pattern=r'^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$')
    session_id:str|None=Field(None,pattern=r'^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$')
    text:str=Field('',max_length=300)
    draft_id:str|None=Field(None,pattern=r'^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$')
    confirmed:bool=False
    model_config=ConfigDict(extra='forbid',strict=True)


class TaskState(TypedDict,total=False):
    order_id:str
    reason:str
    draft:dict
    result:dict


def build_task_graph(business,checkpointer=None):
    async def order(state):
        choices=[row for row in await business('orders') if row['status']=='0902']
        if not choices:raise HTTPException(422,'暂无可申请售后的已支付订单')
        answer=interrupt({'field':'orderId','text':'请选择要办理售后的已支付订单。','choices':choices})
        if not isinstance(answer,dict) or answer.get('action')!='reply':raise HTTPException(422,'请先选择订单')
        identity=str(answer.get('text',''))
        if not re.fullmatch(FLOW['slots']['orderId']['pattern'],identity) or identity not in {row['id'] for row in choices}:
            raise HTTPException(422,'请从当前账号的已支付订单中选择')
        return {'order_id':identity}
    def reason(state):
        answer=interrupt({'field':'reason','text':'请填写 5–300 字申请原因。不会自动提交申请。'})
        text=answer.get('text','').strip() if isinstance(answer,dict) else ''
        rules=FLOW['slots']['reason']
        if not rules['min_length']<=len(text)<=rules['max_length']:raise HTTPException(422,'申请原因须为 5–300 字')
        return {'reason':text}
    async def prepare(state):
        draft=await business('after-sales/prepare','POST',{'orderId':state['order_id'],'reason':state['reason']})
        return {'draft':draft}
    async def confirm(state):
        draft=state['draft']
        answer=interrupt({'field':'confirmation','text':'请核对订单、金额和原因，点击确认后才会提交人工审核。','draft':draft})
        if not isinstance(answer,dict) or answer.get('action')!='confirm' or answer.get('confirmed') is not True or answer.get('draft_id')!=draft['id']:
            raise HTTPException(422,'须点击确认按钮并核对当前草稿')
        result=await business('after-sales/'+draft['id']+'/confirm','POST',{'confirmed':True})
        return {'result':result}
    graph=StateGraph(TaskState)
    steps=[('collect_order',order),('collect_reason',reason),('prepare_draft',prepare),('confirm_submission',confirm)]
    last=START
    for name,fn in steps:graph.add_node(name,fn);graph.add_edge(last,name);last=name
    graph.add_edge(last,END)
    return graph.compile(checkpointer=checkpointer)


class TaskEngine:
    def __init__(self,path=RUNTIME/'customer-tasks.sqlite'):
        self.path=path;path.parent.mkdir(parents=True,exist_ok=True)
        with self.db() as db:
            db.execute('CREATE TABLE IF NOT EXISTS tasks(id TEXT PRIMARY KEY,owner TEXT,session TEXT,status TEXT,created REAL,updated REAL,result TEXT)')
            db.execute('CREATE INDEX IF NOT EXISTS task_owner_session ON tasks(owner,session,status)')
    def db(self):return sqlite3.connect(self.path,timeout=5)
    def current(self,owner,sid):
        with self.db() as db:
            row=db.execute("SELECT id,result,status FROM tasks WHERE owner=? AND session=? AND status IN ('pending','paused') AND created>? ORDER BY created DESC LIMIT 1",(owner,sid,time.time()-600)).fetchone()
        if not row:return None
        return {**json.loads(row[1]),'paused':row[2]=='paused'}
    async def run(self,request,owner,sid,business):
        now=time.time();identity=request.task_id or str(uuid.uuid4())
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            if request.action=='start':
                previous=db.execute("SELECT result FROM tasks WHERE owner=? AND session=? AND status IN ('pending','paused','running') AND created>? ORDER BY created DESC LIMIT 1",(owner,sid,now-600)).fetchone()
                if previous:raise HTTPException(409,'当前对话已有待办任务，请先继续或取消')
                db.execute('INSERT INTO tasks VALUES(?,?,?,?,?,?,?)',(identity,owner,sid,'running',now,now,'{}'))
            else:
                row=db.execute('SELECT owner,session,status,created,updated,result FROM tasks WHERE id=?',(identity,)).fetchone()
                if not row or row[0]!=owner or row[1]!=sid:raise HTTPException(404,'办理任务不存在')
                if now-row[3]>FLOW['expires_seconds']:raise HTTPException(410,'办理任务已过期，请重新发起')
                if row[2]=='completed':return json.loads(row[5])
                if row[2]=='cancelled':raise HTTPException(409,'任务已取消')
                if row[2]=='running' and now-row[4]<120:raise HTTPException(409,'任务正在处理')
                if request.action in ('pause','resume','cancel'):
                    status={'pause':'paused','resume':'pending','cancel':'cancelled'}[request.action]
                    result=json.loads(row[5]);result['task']['paused']=status=='paused'
                    if status=='cancelled':result.update(text='已取消办理。未提交的草稿不会进入人工审核。',task=None)
                    db.execute('UPDATE tasks SET status=?,updated=?,result=? WHERE id=?',(status,now,json.dumps(result,ensure_ascii=False),identity))
                    return result
                if row[2]=='paused':raise HTTPException(409,'请先继续办理')
                pending=json.loads(row[5]).get('task') or {}
                if pending.get('field')=='confirmation':
                    if request.action!='confirm' or request.confirmed is not True or request.draft_id!=pending['draft']['id']:
                        raise HTTPException(422,'须点击确认按钮并核对当前草稿')
                elif pending.get('field')=='reason':
                    if request.action!='reply' or not 5<=len(request.text.strip())<=300:
                        raise HTTPException(422,'申请原因须为 5–300 字')
                elif pending.get('field')=='orderId':
                    if request.action!='reply' or request.text not in {r['id'] for r in pending['choices']}:
                        raise HTTPException(422,'请从当前账号的已支付订单中选择')
                db.execute("UPDATE tasks SET status='running',updated=? WHERE id=?",(now,identity))
        async with AsyncSqliteSaver.from_conn_string(str(self.path.with_name('customer-task-checkpoints.sqlite'))) as saver:
            graph=build_task_graph(business,saver)
            try:
                value={} if request.action=='start' else Command(resume=request.model_dump())
                state=await graph.ainvoke(value,{'configurable':{'thread_id':identity}})
                if state.get('__interrupt__'):
                    pending=state['__interrupt__'][0].value
                    result={'text':pending['text'],'task':{'id':identity,**pending,'paused':False},'graph_trace':['task_flow','interrupt'],'sources':[],'trace':[],'mode':'customer-task','orchestrator':'langgraph','session_id':sid}
                    status='pending'
                else:
                    result={'text':'售后申请已登记，等待人工审核；尚未退款。','task':None,'result':state['result'],'graph_trace':['task_flow','submitted'],'sources':[],'trace':[],'mode':'customer-task','orchestrator':'langgraph','session_id':sid}
                    status='completed'
                with self.db() as db:db.execute('UPDATE tasks SET status=?,updated=?,result=? WHERE id=?',(status,time.time(),json.dumps(result,ensure_ascii=False),identity))
                return result
            except BaseException:
                with self.db() as db:db.execute("UPDATE tasks SET status=?,updated=? WHERE id=?",('failed' if request.action=='start' else 'pending',time.time(),identity))
                raise


def attach_tasks(app,identify,history,business_api):
    engine=TaskEngine()
    @app.post('/api/assistant/tasks')
    async def task(request:TaskRequest,token:str|None=Header(None)):
        owner,_=await identify(token);sid=history.session(request.session_id,owner)
        history.bind_scope(sid,'platform')
        async def business(path,method='GET',payload=None):return await business_api(path,token,method,payload)
        result=await engine.run(request,owner,sid,business)
        history.save(sid,'assistant',{'text':result['text'],'task':result.get('task'),'sources':[],'trace':[]})
        return result
    @app.get('/api/assistant/tasks/current/{sid}')
    async def current(sid:str,token:str|None=Header(None)):
        owner,_=await identify(token);history.session(sid,owner)
        return {'task':engine.current(owner,sid)}
    return engine
