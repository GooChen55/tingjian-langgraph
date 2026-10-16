import asyncio
from atguigu.listening.dialogue import build_dialogue_graph,wants_after_sales


def test_router_keeps_policy_questions_separate_from_applications():
    assert wants_after_sales('我想申请退款')
    assert not wants_after_sales('如何申请退款，需要满足什么条件？')
    async def handler(text):return {'text':text}
    graph=build_dialogue_graph(handler,handler,handler)
    async def run():
        assert (await graph.ainvoke({'text':'你好！'}))['route']=='chitchat'
        assert (await graph.ainvoke({'text':'我想申请退款'}))['route']=='task'
        assert (await graph.ainvoke({'text':'《三体》如何申请退款？'}))['route']=='knowledge'
    asyncio.run(run())
