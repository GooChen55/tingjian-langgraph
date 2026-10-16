"""使用现有模型配置和本地演示记录，验证一次真实工具调用，不输出密钥。"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _bootstrap import ROOT
import json

from fastapi.testclient import TestClient

from atguigu.listening.app import Settings, create_app

cfg = Settings(listening_use_llm=True, listening_demo_login=True,
               listening_history_db=":memory:")
report = {"passed": False, "model": cfg.llm_model}
with TestClient(create_app(cfg)) as client:
    login = client.post("/api/local/login")
    if login.status_code != 200:
        report.update(status=login.status_code, detail="本地用户服务尚未就绪")
    else:
        response = client.post("/api/assistant/chat",
                               headers={"token": login.json()["token"]},
                               json={"text": "请查询我上次听到哪里，告诉我准确的分和秒。"})
        body = response.json()
        report.update(status=response.status_code, response=body)
        report["passed"] = response.status_code == 200 and any(
            step["tool"] == "get_progress" for step in body.get("trace", []))
ROOT.joinpath(".runtime").mkdir(exist_ok=True)
ROOT.joinpath(".runtime", "llm-smoke.json").write_text(
    json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps(report, ensure_ascii=False, indent=2))
sys.exit(0 if report["passed"] else 1)
