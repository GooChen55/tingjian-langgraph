import asyncio
from listening.metadata_graph import metadata_graph,filter_catalog


def test_parallel_metadata_join_and_catalog_boundary():
    seen=[]
    async def extract(text):return text
    async def columns(text):
        await asyncio.sleep(.01);seen.append('columns')
        return [{'view':'v_content_summary','kind':'column','column':'album_count','text':'专辑数量'}]
    async def metrics(text):
        seen.append('metrics');return [{'view':'foreign_users','kind':'view'}]
    async def values(text):seen.append('values');return []
    state=asyncio.run(metadata_graph(extract,columns,metrics,values).ainvoke({'question':'专辑数量','trace':[]}))
    assert len(seen)==3 and len(state['documents'])==1
    assert [t['node'] for t in state['trace']].count('merge_metadata')==1
    assert state['documents'][0]['column']=='album_count'
    assert filter_catalog([{'view':'v_content_summary','column':'password','kind':'column'}])==[]
