"""Bounded NL2SQL workflow. Only validated reads can reach the executor."""
from typing import TypedDict, Annotated
from operator import add
from datetime import datetime, timedelta, timezone
import json

from fastapi import HTTPException
import pymysql
from langgraph.graph import StateGraph, START, END
from langgraph.types import interrupt

from .catalog import CATALOG, SYSTEM
from .guard import UnsafeSQL, validate_sql, operations_database


class QueryState(TypedDict, total=False):
    question: str
    actor_id: str
    request_id: str
    plan: dict
    sql: str
    view: str
    rows: list
    repairs: int
    clarifications: int
    error: str
    route: str
    trace: Annotated[list[dict], add]
    metadata: list[dict]


def build_query_graph(generate, execute, checkpointer=None, retrieve=None):
    async def recall(state):
        documents = await retrieve(state['question'])
        nodes=[]
        if isinstance(documents,dict):nodes=documents['trace'];documents=documents['documents']
        return {'metadata': documents, 'trace': nodes+[{'node': 'recall_metadata', 'count': len(documents)}]}

    async def plan(state):
        prompt = SYSTEM.replace('MySQL 8.4', 'MySQL 8').replace('数据库 listening_ops', '数据库 ' + operations_database()) + '\n当指标或口径确实无法确定时，输出 {"clarification":"需要用户补充的问题"}。'
        context = {'question': state['question'], 'catalog': CATALOG,
                   'today': datetime.now(timezone(timedelta(hours=8))).date().isoformat()}
        if state.get('metadata'):
            context['retrieved_metadata'] = state['metadata']
        if state.get('repairs'):
            context.update(previous_sql=state.get('sql', ''), validation_error=state['error'])
            prompt += '\n修正上述SQL错误，仍须遵守全部安全边界，不能扩大查询范围。'
        result = await generate(prompt, json.dumps(context, ensure_ascii=False))
        route = 'validate'
        error = ''
        if 'unsupported' in result:
            route, error = 'reject', str(result['unsupported'])[:200]
        elif 'clarification' in result:
            route = 'clarify'
            if state.get('clarifications', 0) >= 1:
                route, error = 'reject', '口径仍不明确，请重新提出完整的问题'
        return {'plan': result, 'route': route, 'error': error,
                'trace': [{'node': 'generate_sql', 'repair': state.get('repairs', 0)}]}

    def clarify(state):
        answer = interrupt({'question': str(state['plan']['clarification'])[:300],
                            'request_id': state['request_id']})
        if not isinstance(answer, str) or not 0 < len(answer.strip()) <= 1000:
            raise HTTPException(422, '请提供有效的口径补充')
        return {'question': state['question'] + '\n用户补充：' + answer.strip(),
                'clarifications': state.get('clarifications', 0) + 1,
                'trace': [{'node': 'clarify', 'status': 'answered'}]}

    def validate(state):
        sql = state['plan'].get('sql', '')
        try:
            sql, view = validate_sql(sql)
            return {'sql': sql, 'view': view, 'route': 'execute', 'error': '',
                    'trace': [{'node': 'validate_sql', 'status': 'passed', 'sql': sql}]}
        except UnsafeSQL as exc:
            # Only syntax / column mistakes are repairable. Policy violations end here.
            repairable = str(exc) in {'SQL 语法不合法', '字段不在指标目录中'}
            route = 'repair' if repairable and state.get('repairs', 0) < 2 else 'reject'
            return {'sql': sql, 'route': route, 'error': str(exc),
                    'trace': [{'node': 'validate_sql', 'status': 'rejected', 'reason': str(exc)}]}

    async def run_sql(state):
        try:
            rows = await execute(state['sql'])
            return {'rows': rows, 'route': 'finish', 'trace': [{'node': 'execute', 'rows': len(rows)}]}
        except pymysql.MySQLError as exc:
            code = exc.args[0] if exc.args else None
            if code in {1054, 1064} and state.get('repairs', 0) < 2:
                # Do not send connection information or raw database errors to the model.
                return {'route': 'repair', 'error': '数据库拒绝字段或语法，请依据指标目录修正',
                        'trace': [{'node': 'execute', 'status': 'sql-error', 'code': code}]}
            raise HTTPException(502, '只读数据查询失败，请检查数据库连接或指标视图') from None

    def repair(state):
        return {'repairs': state.get('repairs', 0) + 1,
                'trace': [{'node': 'repair', 'attempt': state.get('repairs', 0) + 1}]}

    graph = StateGraph(QueryState)
    for name, node in [('plan', plan), ('clarify', clarify), ('validate', validate),
                       ('execute', run_sql), ('repair', repair)]:
        graph.add_node(name, node)
    if retrieve:
        graph.add_node('recall_metadata', recall)
        graph.add_edge(START, 'recall_metadata')
        graph.add_edge('recall_metadata', 'plan')
    else:
        graph.add_edge(START, 'plan')
    graph.add_conditional_edges('plan', lambda s: s['route'],
                                {'validate': 'validate', 'clarify': 'clarify', 'reject': END})
    graph.add_edge('clarify', 'plan')
    graph.add_conditional_edges('validate', lambda s: s['route'],
                                {'execute': 'execute', 'repair': 'repair', 'reject': END})
    graph.add_conditional_edges('execute', lambda s: s['route'],
                                {'finish': END, 'repair': 'repair'})
    graph.add_edge('repair', 'plan')
    return graph.compile(checkpointer=checkpointer)
