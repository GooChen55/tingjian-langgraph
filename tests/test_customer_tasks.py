import asyncio
import uuid
import pytest
from fastapi import HTTPException
from atguigu.listening.tasks import TaskEngine,TaskRequest


def test_task_restart_owner_and_explicit_confirmation(tmp_path):
    calls=[];draft=str(uuid.uuid4());sid=str(uuid.uuid4())
    async def business(path,method='GET',payload=None):
        calls.append((path,method,payload))
        if path=='orders':return [{'id':'42','status':'0902','title':'示例订单','amount':'9.90','orderNo':'TEST-42'}]
        if path=='after-sales/prepare':return {'id':draft,'orderId':'42','amount':'9.90','reason':payload['reason']}
        return {'id':draft,'status':'SUBMITTED'}
    async def run():
        path=tmp_path/'tasks.db';engine=TaskEngine(path)
        first=await engine.run(TaskRequest(), 'alice',sid,business)
        identity=first['task']['id']
        async def send(action='reply',**values):
            return await TaskEngine(path).run(TaskRequest(action=action,task_id=identity,**values),'alice',sid,business)
        await send(text='42')
        pending=await send(text='误购，请按流程处理售后')
        assert pending['task']['field']=='confirmation'
        assert not any('/confirm' in c[0] for c in calls)
        with pytest.raises(HTTPException) as denied:
            await engine.run(TaskRequest(action='confirm',task_id=identity,draft_id=draft,confirmed=True),'bob',sid,business)
        assert denied.value.status_code==404
        with pytest.raises(HTTPException) as missing:
            await send(text='确认提交')
        assert missing.value.status_code==422
        completed=await send('confirm',draft_id=draft,confirmed=True)
        repeated=await send('confirm',draft_id=draft,confirmed=True)
        assert completed==repeated and completed['task'] is None
        assert len([c for c in calls if '/confirm' in c[0]])==1
    asyncio.run(run())


def test_pause_cancel_and_expiry_do_not_submit(tmp_path):
    calls=[];sid=str(uuid.uuid4())
    async def business(path,*args):
        calls.append(path);return [{'id':'42','status':'0902'}]
    async def run():
        engine=TaskEngine(tmp_path/'tasks.db')
        first=await engine.run(TaskRequest(),'a',sid,business);identity=first['task']['id']
        paused=await engine.run(TaskRequest(action='pause',task_id=identity),'a',sid,business)
        assert paused['task']['paused']
        assert engine.current('other',sid) is None
        cancelled=await engine.run(TaskRequest(action='cancel',task_id=identity),'a',sid,business)
        assert cancelled['task'] is None and calls==['orders']
    asyncio.run(run())
