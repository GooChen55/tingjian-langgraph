import asyncio
import json
from types import SimpleNamespace

import httpx
import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from atguigu.listening.app import History
from atguigu.listening.personal import Item,Segment
from personal_knowledge.providers import scoped_filter,MinioObjects,MilvusVectors
from personal_knowledge.listening import merged_intervals
from personal_knowledge import engine


SPACE='12345678-1234-4234-8234-123456789abc'
REVISION='a'*64


def test_owner_filter_cannot_be_broadened():
    expression=scoped_filter('42',SPACE,[(7,REVISION)])
    assert 'owner_id == "42"' in expression and 'space_id == "'+SPACE+'"' in expression
    assert 'item_id == "7"' in expression and 'revision == "'+REVISION+'"' in expression
    for owner,space,versions in [('42 or true',SPACE,[(7,REVISION)]),('42','x" or true',[(7,REVISION)]),('42',SPACE,[])]:
        with pytest.raises(ValueError):scoped_filter(owner,space,versions)


def test_object_access_cannot_cross_owner_or_space():
    adapter=MinioObjects();key=f'personal/42/{SPACE}/'+('b'*32)+'/'+REVISION
    assert adapter.key(42,SPACE,key)==key
    with pytest.raises(ValueError):adapter.key(43,SPACE,key)
    with pytest.raises(ValueError):adapter.key(42,SPACE,key+'/../other')


def test_private_session_cannot_be_reused_for_public_prompt():
    history=History(':memory:');sid=history.session(None,'42')
    history.bind_scope(sid,'personal:'+SPACE)
    with pytest.raises(HTTPException) as error:history.bind_scope(sid,'platform')
    assert error.value.status_code==409
    with pytest.raises(HTTPException):history.session(sid,'43')


def test_jumps_and_forged_owner_are_not_playback_intervals():
    body={'session_id':SPACE,'sequence':1,'album_id':1,'track_id':2,'start':3,'end':8,'elapsed':5}
    Segment(**body)
    for change in [{'end':60},{'elapsed':1},{'owner_id':43},{'start':float('nan')}]:
        with pytest.raises(ValidationError):Segment(**{**body,**change})
    assert merged_intervals([{'start':0,'end':8},{'start':6,'end':12},{'start':50,'end':52}])==[[0.,12.],[50.,52.]]


def test_note_requires_text_and_bookmark_requires_track():
    with pytest.raises(ValidationError):Item(kind='NOTE',title='空笔记',content=' ')
    with pytest.raises(ValidationError):Item(kind='BOOKMARK',title='空书签')
    with pytest.raises(ValidationError):Item(kind='NOTE',title='笔记',content='正文',owner_id=42)


def test_disabled_ai_never_calls_external_model_and_deleted_evidence_is_removed(monkeypatch):
    row={'id':7,'owner_id':42,'space_id':SPACE,'kind':'NOTE','active_revision':REVISION,'active_text':'我记下了水杉森林和青色湖泊的观点。','active_title':'水杉森林笔记','title':'水杉森林笔记','active_link':{},'vector_model':None}
    calls=[]
    def items(*args):
        calls.append(args)
        return {'ai_enabled':False},([row] if len(calls)==1 else [])
    monkeypatch.setattr(engine.repo,'items',items)
    async def forbidden(*args,**kwargs):raise AssertionError('Private text sent to a model without consent')
    monkeypatch.setattr(engine,'embed',forbidden);monkeypatch.setattr(engine,'model_json',forbidden)
    result=asyncio.run(engine.query('42',SPACE,'水杉森林'))
    assert result['sources']==[] and result['mode']=='private-keyword'
    assert all(call[:2]==('42',SPACE) for call in calls)


def test_vector_http_request_filters_before_top_k(monkeypatch):
    import personal_knowledge.providers as module
    monkeypatch.setattr(module,'vm_data_credentials',lambda:{'host':'192.168.6.100','milvus_password':'not-a-real-key'})
    captured=[]
    def handler(request):
        payload=json.loads(request.content);captured.append(payload)
        return httpx.Response(200,json={'code':0,'data':{'has':True} if request.url.path.endswith('/has') else []})
    adapter=MilvusVectors({'base_url':'https://example.test','model':'test','dimensions':2},httpx.MockTransport(handler))
    asyncio.run(adapter.search('42',SPACE,[(7,REVISION)],[1.,0.]))
    assert captured[-1]['filter']==scoped_filter('42',SPACE,[(7,REVISION)])
    assert captured[-1]['collectionName'].startswith('aillisten_dev_personal_')


def test_unconfigured_cloud_adapters_fail_closed(monkeypatch):
    import personal_knowledge.providers as module
    monkeypatch.setenv('LISTENING_PERSONAL_OBJECT_BACKEND','future-cloud')
    monkeypatch.setenv('LISTENING_PERSONAL_VECTOR_BACKEND','future-cloud')
    monkeypatch.setenv('LISTENING_PERSONAL_PARSER_BACKEND','future-cloud')
    for call in [module.objects,module.parser,lambda:module.vectors({})]:
        with pytest.raises(HTTPException) as error:call()
        assert error.value.status_code==503


def test_lost_commit_ack_does_not_delete_a_possibly_committed_original(monkeypatch):
    from contextlib import contextmanager
    from unittest.mock import MagicMock
    from personal_knowledge import repository,providers
    cursor=MagicMock();cursor.fetchone.return_value={'n':0};cursor.lastrowid=7
    db=MagicMock();db.cursor.return_value.__enter__.return_value=cursor
    @contextmanager
    def ambiguous_commit():
        yield db
        raise OSError('commit acknowledgement lost')
    store=MagicMock()
    monkeypatch.setattr(repository,'transaction',ambiguous_commit)
    monkeypatch.setattr(repository,'owned_space',lambda *args:None)
    monkeypatch.setattr(repository,'event',lambda *args:'event')
    monkeypatch.setattr(providers,'objects',lambda:store)
    with pytest.raises(OSError):repository.save('42',SPACE,{'kind':'DOCUMENT','title':'个人文件','filename':'note.md'},blob=b'private original')
    store.put.assert_called_once()
    store.remove.assert_not_called()
