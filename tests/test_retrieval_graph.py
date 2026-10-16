import asyncio
import json

from app.listening.retrieval_graph import build_retrieval_graph


def test_retrieval_joins_all_branches_once_and_never_cites_hypothesis():
    seen = []
    original = {'chunk_id':'source-1','title':'三体','text':'原始资料证据','source':'三体.md','vector_score':.8}
    async def model(system, user):
        if 'hypothesis' in system:
            return {'hypothesis':'虚构检索假设，不能当证据'}
        return {'query':'三体阅读门槛','clarification':''}
    async def search(question, limit=15):
        return [original]
    async def kg(question):
        await asyncio.sleep(.01)
        seen.append('kg-finished')
        return [original]
    async def rank(question, docs):
        assert seen == ['kg-finished']
        assert len(docs) == 1
        assert docs[0]['text'] == '原始资料证据'
        seen.append('rank')
        return docs
    async def answer(question, docs):
        seen.append('answer')
        return {'answer':docs[0]['text'],'grounded':True}
    graph = build_retrieval_graph(model,search,kg,rank,answer,['三体'])
    state = asyncio.run(graph.ainvoke({'question':'它难读吗','history':[], 'trace':[]}))
    assert seen == ['kg-finished','rank','answer']
    assert state['result']['grounded']
    assert {n['node'] for n in state['trace']} == {
        'rewrite','dense_bm25','hyde','knowledge_graph','web_search','rrf','rerank','evidence_answer'}


def test_ambiguous_reference_stops_before_retrieval():
    async def model(system,user):
        return {'query':'它难读吗','clarification':'你指的是哪本书？'}
    async def forbidden(*args,**kwargs):
        raise AssertionError('Clarification must not retrieve or answer')
    graph = build_retrieval_graph(model,forbidden,forbidden,forbidden,forbidden,['三体'])
    state = asyncio.run(graph.ainvoke({'question':'它难读吗','history':[], 'trace':[]}))
    assert state['result']['clarification_required']
    assert state['result']['sources'] == []


def test_sse_graph_events_include_actual_node_updates_and_final_value():
    async def model(system,user):
        return {'query':'问题','clarification':'请补充书名'}
    async def unused(*args,**kwargs):
        raise AssertionError('Should not be called')
    graph=build_retrieval_graph(model,unused,unused,unused,unused,[])
    async def run():
        return [event async for event in graph.astream({'question':'问题','trace':[]},stream_mode=['updates','values'])]
    events=asyncio.run(run())
    assert any(mode=='updates' and 'rewrite' in value for mode,value in events)
    assert events[-1][0]=='values'
    assert events[-1][1]['result']['answer']=='请补充书名'
