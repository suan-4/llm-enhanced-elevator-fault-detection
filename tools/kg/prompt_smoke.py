#!/usr/bin/env python3
"""kg-prompt-v1 冒烟测试：构造提示词 + 校验器正反例，不调用模型。"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app.services.kg_v2 import kg_v2  # noqa: E402
from app.services.kg_prompt import (  # noqa: E402
    PROMPT_VERSION, build_t1_query_prompt, build_t2_rerank_prompt,
    build_t3_item_prompt, build_t4_overview_prompt,
)
from app.services.kg_validation import validate_t3, validate_t4  # noqa: E402

SAMPLES = [
    ("5.1", "制动器型式", ["参与向制动面施加制动力的制动器机械部件未分成至少两组设置。"], ""),
    ("1.9", "限速器", ["限速器运行中有异响。"], ""),
    ("7.2", "门扇", ["门扇严重锈蚀穿孔或破损穿孔。"], ""),
    ("5.1", "制动器型式", [], "制动器柱塞发涩，松闸后回位慢"),
]


def main() -> int:
    print("prompt_version", PROMPT_VERSION)
    failures = []
    for no, name, reasons, other in SAMPLES:
        result = kg_v2.retrieve(item_no=no, item_name=name, reasons=reasons, other_text=other)
        top = result["candidates"][0]
        evidence = kg_v2.evidence([top["path_id"]])["paths"]
        t3 = build_t3_item_prompt(
            item_no=no, item_name=name, query=result["query"],
            rule_facts={"category": "Ⅱ类", "measure": "应采用修理、调整、更换等措施。", "issue": ""},
            paths=evidence,
        )
        # 用证据构造一个合法 T3 输出
        path = evidence[0]
        good = {
            "item_no": no,
            "path_ids": [path["path_id"]],
            "fault_chain": (path.get("states") or [])[:4],
            "trigger": path.get("trigger_condition") or "",
            "barrier": path.get("barrier_condition") or "",
            "risk": path.get("risk") or "",
            "inspection": path.get("inspection") or "",
            "action": path.get("action") or "",
            "verification": path.get("verification") or "",
            "evidence_note": "候选证据，未签核",
        }
        ok = validate_t3(good, item_no=no, allowed_path_ids={path["path_id"]},
                         evidence_paths=evidence,
                         rule_facts={"category": "Ⅱ类"})
        bad_path = json.loads(json.dumps(good, ensure_ascii=False))
        bad_path["path_ids"] = ["PATH_V2_FAKE"]
        bad_action = json.loads(json.dumps(good, ensure_ascii=False))
        bad_action["action"] = "随便更换一个部件"
        bad_chain = json.loads(json.dumps(good, ensure_ascii=False))
        bad_chain["fault_chain"] = ["不存在的状态"]
        r1 = validate_t3(bad_path, item_no=no, allowed_path_ids={path["path_id"]}, evidence_paths=evidence)
        r2 = validate_t3(bad_action, item_no=no, allowed_path_ids={path["path_id"]}, evidence_paths=evidence)
        r3 = validate_t3(bad_chain, item_no=no, allowed_path_ids={path["path_id"]}, evidence_paths=evidence)
        print(f"== {no} {name}: prompt {len(t3)} chars, top={top['path_id']}")
        print("   good:", ok["valid"], ok["errors"][:2])
        print("   bad_path:", r1["valid"], [e["code"] for e in r1["errors"]])
        print("   bad_action:", r2["valid"], [e["code"] for e in r2["errors"]])
        print("   bad_chain:", r3["valid"], [e["code"] for e in r3["errors"]])
        if not ok["valid"]:
            failures.append((no, "good_t3", ok))
        if r1["valid"] or r2["valid"] or r3["valid"]:
            failures.append((no, "negative", [r1, r2, r3]))

        # T1 / T2 prompts should be valid JSON envelopes
        t1 = build_t1_query_prompt(item_no=no, item_name=name, original_text=other or reasons[0] if reasons or other else name)
        t2 = build_t2_rerank_prompt(item_no=no, query=result["query"], candidates=result["candidates"])
        json.loads(t1); json.loads(t2)

    # T4 正反例
    facts = {
        "finding": "本次评估共发现 1 项不符合。",
        "score": "综合安全状况得分 97.73，等级 一级。",
        "risks": [{"key": "1.7", "text": "项目 1.7：活动区域净高度/通道宽度不符合要求，Ⅱ类。"}],
    }
    items = [{"item_no": "1.7", "category": "Ⅱ类", "measure": "应整改活动区域。", "has_candidate_evidence": True}]
    t4 = build_t4_overview_prompt(overview_facts=facts, required_keys=["finding", "score", "1.7"], items=items)
    good4 = {
        "overview": "本次评估共发现 1 项不符合，主要涉及机房工作安全空间。综合安全状况得分 97.73，等级 一级。",
        "key_findings": ["1.7：机房工作安全空间净高度/通道宽度不足，已给出候选演化路径。"],
        "risk_statement": "按规则评定为Ⅱ类风险，得分与等级由程序计算。",
        "limitations": "图谱路径为工程候选，需人工复核。",
    }
    v4 = validate_t4(good4, overview_facts=facts, required_keys=["finding", "score", "1.7"], items=items)
    bad4 = json.loads(json.dumps(good4, ensure_ascii=False))
    bad4["overview"] += " 详见 PATH_V2_FAKE。"
    bad4["key_findings"].append("1.7：新增了一个 999 的限值要求。")
    v4b = validate_t4(bad4, overview_facts=facts, required_keys=["finding", "score", "1.7"], items=items)
    print("== T4:", len(t4), "chars", "good:", v4["valid"], v4["errors"][:3])
    print("   bad:", v4b["valid"], [e["code"] for e in v4b["errors"]])
    if not v4["valid"] or v4b["valid"]:
        failures.append(("T4", "validator", [v4, v4b]))
    print("RESULT", "PASS" if not failures else f"FAIL {len(failures)}")
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
