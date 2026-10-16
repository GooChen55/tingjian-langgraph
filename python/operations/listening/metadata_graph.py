"""Parallel recall with an explicit barrier and catalog-bound filtering."""
from operator import add
from typing import TypedDict,Annotated
from langgraph.graph import StateGraph,START,END
from .catalog import CATALOG


class MetadataState(TypedDict,total=False):
    question:str
    query:str
    columns:list
    metrics:list
    values:list
    merged:list
    documents:list
    trace:Annotated[list,add]


def filter_catalog(documents):
    result=[]
    for doc in documents:
        view=doc.get('view');column=doc.get('column')
        if view not in CATALOG or doc.get('kind') not in {'view','column','value'}:continue
        if column and column not in CATALOG[view]['columns']:continue
        result.append({k:v for k,v in doc.items() if k in {'kind','view','column','text','value'}})
    return result


def metadata_graph(extract,recall_columns,recall_metrics,recall_values):
    async def keywords(state):
        query=await extract(state['question'])
        return {'query':query,'trace':[{'node':'extract_keywords'}]}
    async def columns(state):
        docs=await recall_columns(state['query'])
        return {'columns':docs,'trace':[{'node':'recall_columns','count':len(docs)}]}
    async def metrics(state):
        docs=await recall_metrics(state['query'])
        return {'metrics':docs,'trace':[{'node':'recall_metrics','count':len(docs)}]}
    async def values(state):
        docs=await recall_values(state['query'])
        return {'values':docs,'trace':[{'node':'recall_values','count':len(docs)}]}
    def merge(state):
        scores,by_key={},{}
        for docs in (state['columns'],state['metrics'],state['values']):
            for rank,doc in enumerate(docs,1):
                key=(doc.get('view'),doc.get('column'),doc.get('value'),doc.get('kind'))
                by_key[key]=doc;scores[key]=scores.get(key,0)+1/(60+rank)
        selected=[by_key[k] for k in sorted(scores,key=scores.get,reverse=True)[:25]]
        return {'merged':selected,'trace':[{'node':'merge_metadata','count':len(selected)}]}
    def validate(state):
        docs=filter_catalog(state['merged'])
        return {'documents':docs,'trace':[{'node':'filter_tables_and_metrics','count':len(docs)}]}
    graph=StateGraph(MetadataState)
    for name,node in [('keywords',keywords),('columns',columns),('metrics',metrics),('values',values),('merge',merge),('filter',validate)]:graph.add_node(name,node)
    graph.add_edge(START,'keywords')
    for name in ('columns','metrics','values'):graph.add_edge('keywords',name)
    graph.add_edge(['columns','metrics','values'],'merge');graph.add_edge('merge','filter');graph.add_edge('filter',END)
    return graph.compile()
