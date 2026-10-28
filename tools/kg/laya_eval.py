r"""Laya 离线可行性 smoke：在板端已出现过的 Top3 候选上做 choice。

用法:
    .venv-laya\Scripts\python tools/kg/laya_eval.py --cases tools/kg/laya_eval_cases.json

注意:
- 只评估候选选择，不做 KG 检索；
- cases 里的 gold 来自板端 kg_selection；部分 gold 是 AI 推荐后操作员确认的，
  结果只作为 smoke，不作为正式准确率。
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path


def load_cases(path: Path) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    cases = []
    for case in data:
        gold = case.get("gold_decision")
        candidates = case.get("candidates") or []
        if gold == "selected" and case.get("gold_path_id") not in {
                c.get("path_id") for c in candidates}:
            continue
        if not candidates:
            continue
        cases.append(case)
    return cases


def criteria_of(case: dict) -> tuple[dict[str, str], dict[str, str]]:
    criteria: dict[str, str] = {}
    mapping: dict[str, str] = {}
    for i, c in enumerate(case["candidates"][:3], 1):
        key = f"p{i}"
        criteria[key] = (c.get("path_summary") or "")[:420]
        mapping[key] = c.get("path_id") or ""
    criteria["none"] = "以上候选都不符合，按规则表处置，不引用图谱路径"
    mapping["none"] = ""
    return criteria, mapping


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases", default="tools/kg/laya_eval_cases.json")
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--json-out", default="")
    parser.add_argument("--json-state", action="store_true")
    args = parser.parse_args()

    cases = load_cases(Path(args.cases))
    if args.limit:
        cases = cases[:args.limit]
    if not cases:
        print("没有可评估的案例")
        return 1

    from laya import Router

    # 只加载多语言 checkpoint，避免把三个权重都读进内存
    router = Router(device=args.device, max_loaded=1)
    router.preload(["multilingual"])
    rows = []
    for case in cases:
        criteria, mapping = criteria_of(case)
        if args.json_state:
            state = json.dumps({"项目名称": case.get("item_name") or "",
                                "不符合描述": case.get("query") or ""}, ensure_ascii=False)
        else:
            state = f"{case.get('item_name') or ''}\n{case.get('query') or ''}"
        questions = {
            "path": {
                "type": "choice",
                "instructions": "这项电梯不符合最接近哪条候选故障路径？都不符合时选 none。",
                "criteria": criteria,
            }
        }
        started = time.perf_counter()
        try:
            result = router.predict(state, questions, model="multilingual", max_len=1024)
            answer = (result.get("answers") or {}).get("path") or {}
            choice = answer.get("choice")
            probs = answer.get("probabilities") or {}
            confidence = float(probs.get(choice, 0)) if choice in probs else None
            picked_path = mapping.get(choice, "")
            gold = case.get("gold_path_id") if case.get("gold_decision") == "selected" else None
            correct = (picked_path == gold) if gold else (choice == "none")
            rows.append({
                "item_no": case.get("item_no"),
                "item_name": case.get("item_name"),
                "gold_decision": case.get("gold_decision"),
                "gold_path_id": gold,
                "choice": choice,
                "picked_path_id": picked_path,
                "confidence": confidence,
                "correct": bool(correct),
                "source": case.get("selection_source"),
                "candidates": len(case["candidates"]),
                "routing_model": ((result.get("routing") or {}).get("model") or ""),
                "elapsed_s": round(time.perf_counter() - started, 3),
            })
        except Exception as exc:
            rows.append({"item_no": case.get("item_no"), "error": f"{type(exc).__name__}: {exc}"})

    valid = [r for r in rows if "error" not in r]
    correct = sum(1 for r in valid if r["correct"])
    errors = [r for r in valid if not r["correct"]]
    high_conf_errors = [r for r in errors if (r.get("confidence") or 0) >= 0.7]
    result = {
        "cases": len(rows),
        "evaluated": len(valid),
        "correct": correct,
        "accuracy": round(correct / len(valid), 3) if valid else None,
        "high_confidence_errors": len(high_conf_errors),
        "rows": rows,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if args.json_out:
        Path(args.json_out).write_text(json.dumps(result, ensure_ascii=False, indent=2),
                                       encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
