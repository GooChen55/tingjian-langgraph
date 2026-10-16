"""Task / knowledge / chitchat routing; routing never grants permissions."""
import re
from typing import TypedDict
from langgraph.graph import StateGraph,START,END


class DialogueState(TypedDict,total=False):
    text:str
    route:str
    result:dict
    handlers:dict


def wants_after_sales(text):
    return any(word in text for word in ('申请售后','办理售后','申请退款')) and not any(word in text for word in ('《','如何','怎么','条件','规则','流程','说明'))


def build_dialogue_graph(task=None,knowledge=None,chitchat=None):
    def classify(state):
        text=re.sub(r'[\s，,。.!！?？]','',state['text']).lower()
        route='chitchat' if text in {'你好','您好','hi','hello','谢谢','谢谢你','你能做什么','帮助'} else 'task' if wants_after_sales(text) or any(w in text for w in ('我的订单','我的会员','收听进度','售后记录','会员状态')) else 'knowledge'
        return {'route':route}
    async def task_node(state):return {'result':await (task or state['handlers']['task'])(state['text'])}
    async def knowledge_node(state):return {'result':await (knowledge or state['handlers']['knowledge'])(state['text'])}
    async def chitchat_node(state):return {'result':await (chitchat or state['handlers']['chitchat'])(state['text'])}
    graph=StateGraph(DialogueState)
    graph.add_node('classify',classify)
    for name,node in [('task',task_node),('knowledge',knowledge_node),('chitchat',chitchat_node)]:graph.add_node(name,node);graph.add_edge(name,END)
    graph.add_edge(START,'classify');graph.add_conditional_edges('classify',lambda state:state['route'],{name:name for name in ('task','knowledge','chitchat')})
    return graph.compile()
