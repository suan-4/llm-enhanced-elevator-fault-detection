#!/usr/bin/env python3
"""用假模型验证 T3/T4 接入流程（不依赖真实 RKLLM）。"""
from __future__ import annotations
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app.services.kg_v2 import kg_v2  # noqa: E402
from app.services.report_workflow import _run_kg_prompt_flow  # noqa: E402


async def fake_model(prompt: str) -> str:
    payload = json.loads(prompt)
    data = payload["data"]
    task = data.get("task")
    if task == "kg_item_summary":
        paths = data["paths"]
        p = paths[0]
        return json.dumps({
            "item_no": data["item_no"],
            "path_ids": [p["path_id"]],
            "fault_chain": p["states"][:4],
            "trigger": p.get("trigger_condition", ""),
            "barrier": p.get("barrier_condition", ""),
            "risk": p.get("risk", ""),
            "inspection": p.get("inspection", ""),
            "action": p.get("action", ""),
            "verification": p.get("verification", ""),
            "evidence_note": "候选证据，未签核",
        }, ensure_ascii=False)
    if task == "report_overview":
        facts = data["overview_facts"]
        finding = str(facts.get("finding") or "本次评估发现不符合项。")
        score = str(facts.get("score") or "得分由程序计算。")
        items = data.get("items") or []
        no = items[0]["item_no"] if items else "1.7"
        return json.dumps({
            "overview": f"{finding}{score}",
            "key_findings": [f"{no}：该项不符合，详见附页候选证据。"],
            "risk_statement": "风险类别、得分与等级由规则程序计算。",
            "limitations": "图谱路径为工程候选，需人工复核。",
        }, ensure_ascii=False)
    raise ValueError(f"unexpected task {task}")


async def main() -> int:
    top = kg_v2.retrieve(item_no="1.7", item_name="机房工作安全空间",
                         reasons=["活动区域的净高度,以及通道宽度不符合要求。"])["candidates"][0]
    evidence_path = kg_v2.evidence([top["path_id"]])["paths"][0]
    evidence_path["item_no"] = "1.7"
    kg_evidence = {
        "selections": [{"item_no": "1.7", "decision": "selected",
                        "path_id": top["path_id"], "query": "活动区域净高度/通道宽度"}],
        "paths": [evidence_path],
    }
    result = await _run_kg_prompt_flow(
        kg_evidence=kg_evidence,
        unfit=[{"no": "1.7", "reasons": ["活动区域的净高度,以及通道宽度不符合要求。"], "other_text": ""}],
        risks={"1.7": {"category": "Ⅱ类", "issue": "",
                        "selected_risks": [{"key": "1.7:01", "text": "活动区域净高度/通道宽度不符合要求",
                                            "measure": "应整改活动区域。"}]}},
        score=97.73, grade="一级",
        required_keys=["finding", "score", "risk:1.7:01"],
        model_text=fake_model,
    )
    print(json.dumps({"used": result.get("used"), "errors": result.get("errors"),
                      "narrative": result.get("narrative", "")[:120],
                      "appendix": (result.get("appendix") or "")[:180],
                      "validation": result.get("validation")}, ensure_ascii=False, indent=2))
    if not result.get("used"):
        return 1
    # 失败回退：模型返回非法 JSON
    async def bad_model(prompt: str) -> str:
        return "not json"
    bad = await _run_kg_prompt_flow(
        kg_evidence=kg_evidence,
        unfit=[{"no": "1.7", "reasons": ["x"], "other_text": ""}],
        risks={"1.7": {"category": "Ⅱ类", "selected_risks": [{"key": "1.7:01", "text": "x", "measure": "y"}]}},
        score=97.73, grade="一级",
        required_keys=["finding", "score", "risk:1.7:01"], model_text=bad_model,
    )
    print("fallback_used:", bad.get("used"), "errors:", [e["code"] for e in bad.get("errors", [])])
    return 0 if not bad.get("used") else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
