"""Model/tool loop with explicit nodes and bounded execution."""
from typing import TypedDict, Annotated
from operator import add
from langgraph.graph import StateGraph, START, END
from fastapi import HTTPException


class AssistantState(TypedDict, total=False):
    messages: list[dict]
    calls: list[dict]
    round_index: int
    answer: str | None
    node_trace: Annotated[list[str], add]


def build_assistant_graph(call_model, execute_calls):
    async def model(state):
        index = state['round_index']
        message = await call_model(state['messages'], index)
        calls = message.get('tool_calls') or []
        if not isinstance(calls, list) or len(calls) > 3:
            raise HTTPException(502, '模型工具调用过多或格式错误，请简化问题')
        if not calls and index == 0:
            raise HTTPException(502, '模型未执行查询工具，请重试')
        return {'messages': state['messages'] + [message], 'calls': calls,
                'answer': None if calls else message.get('content') or '暂时无法回答这个问题。',
                'node_trace': ['model']}

    async def tools(state):
        results = await execute_calls(state['calls'])
        return {'messages': state['messages'] + results,
                'round_index': state['round_index'] + 1, 'node_trace': ['tools']}

    def guard(state):
        if state['round_index'] >= 4:
            raise HTTPException(502, '达到工具调用上限，请简化问题')
        return {'node_trace': ['guard']}

    graph = StateGraph(AssistantState)
    graph.add_node('model', model)
    graph.add_node('tools', tools)
    graph.add_node('guard', guard)
    graph.add_edge(START, 'model')
    graph.add_conditional_edges('model', lambda s: 'tools' if s['calls'] else 'finish',
                                {'tools': 'tools', 'finish': END})
    graph.add_edge('tools', 'guard')
    graph.add_edge('guard', 'model')
    return graph.compile()
