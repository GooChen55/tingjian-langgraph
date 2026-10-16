"""固定问题集评估真实向量召回；不把小样本结果当作通用模型精度。"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _bootstrap import ROOT
import asyncio
import json

from app.listening.index import VectorIndex
from listening_common import ServiceSettings

CASES = [
    ("《三体》的用户评论有哪些阅读门槛提醒？", {"三体"}),
    ("我想理解自己的情绪，寻找心理成长方面的故事。", {"蛤蟆先生去看心理医生"}),
    ("想学习减少争吵、表达感受和需要的沟通方法。", {"非暴力沟通"}),
    ("想听中国明代历史和历史人物故事。", {"明朝那些事儿"}),
    ("有没有介绍人类从古至今如何发展、文明如何变化的书？", {"人类简史"}),
    ("想听沙漠中的生活、异乡旅行见闻。", {"撒哈拉的故事"}),
    ("想听关于苦难、生存与生命韧性的中文小说。", {"活着"}),
    ("童话里关于爱、陪伴、孤独和成长的故事适合听哪本？", {"小王子"}),
    ("《不存在的测试书籍》讲什么？", set()),
    ("如何使用Docker部署一个Kubernetes集群？", set()),
    ("想听关于阿富汗友谊、背叛与救赎的故事。", {"追风筝的人"}),
    ("有没有通过书信帮助别人解决烦恼的小说？", {"解忧杂货店"}),
    ("《平台订单与本地支付说明》本地购买会扣真实钱吗？", {"平台订单与本地支付说明"}),
    ("《平台订单与本地支付说明》未支付多久自动取消？", {"平台订单与本地支付说明"}),
    ("《售后与账号安全说明》审核通过就是银行到账吗？", {"售后与账号安全说明"}),
    ("《售后与账号安全说明》渠道受理后响应丢失怎么重试？", {"售后与账号安全说明"}),
]


async def main():
    index = VectorIndex(ServiceSettings())
    await index.build()
    results = []
    for query, expected in CASES:
        docs = await index.search(query)
        recalled = {d["title"] for d in docs}
        passed = bool(recalled & expected) if expected else not docs
        results.append({"query": query, "expected": sorted(expected), "recalled": sorted(recalled),
                        "passed": passed, "chunks": [{"title": d["title"], "section": d["section"], "score": d["vector_score"]} for d in docs]})
    report = {"model": index.connection['model'], "chunks": len(index.chunks),
              "passed": sum(r["passed"] for r in results), "total": len(results), "cases": results}
    ROOT.joinpath(".runtime", "retrieval-evaluation.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return report["passed"] == report["total"]


sys.exit(0 if asyncio.run(main()) else 1)
