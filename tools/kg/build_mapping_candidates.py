#!/usr/bin/env python3
"""Generate review candidates: JTE 66 items / 445 options -> v2 graph paths.

Output (Excel-friendly, UTF-8 BOM):
  docs/kg-review/JTE-图谱映射审核表.csv   (option level, main review file)
  docs/kg-review/JTE-条目候选表.csv       (item level)
  docs/kg-review/summary.json

Review columns are blank on purpose: candidate -> self_reviewed -> expert_reviewed.
Run from repo root:  python tools/kg/build_mapping_candidates.py
"""
from __future__ import annotations
import csv, json, re, sqlite3, time, unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DB = ROOT / "backend" / "data" / "kg_v2.sqlite"
JTE = ROOT / "backend" / "app" / "data" / "jte_items.json"
EXPERT = ROOT / "backend" / "app" / "data" / "expert_risks.json"
OUT_DIR = ROOT / "docs" / "kg-review"

SYNONYMS = {
    "减速箱": ["减速器", "减速机", "减速箱", "曳引机减速"],
    "电动机": ["电机", "电动机", "曳引机", "驱动主机"],
    "钢丝绳": ["钢丝绳", "悬挂绳", "包覆绳", "绳带", "曳引绳"],
    "制动器": ["制动器", "制动", "抱闸"],
    "限速器": ["限速器", "限速"],
    "安全钳": ["安全钳", "夹钳"],
    "层门": ["层门", "门扇", "门锁", "门套", "地坎", "门机"],
    "轿门": ["轿门", "门扇", "门机"],
    "缓冲器": ["缓冲器", "耗能", "蓄能"],
    "导轨": ["导轨", "导向", "轨线", "导靴"],
    "对重": ["对重", "平衡重"],
    "补偿链": ["补偿链", "补偿缆", "补偿绳", "补偿装置"],
    "随行电缆": ["随行电缆", "电缆", "软缆"],
    "控制柜": ["控制柜", "控制屏", "电气控制", "变频器"],
    "接地": ["接地", "接地线", "等电位", "保护线"],
    "平层": ["平层", "平层感应", "层楼位置", "编码器"],
    "安全开关": ["安全开关", "电气安全装置", "安全回路", "开关"],
    "盘车": ["盘车", "手动", "紧急操作"],
    "夹绳器": ["夹绳器", "夹紧件", "上行超速", "超速保护"],
    "轿架": ["轿架", "轿厢架", "上梁", "下梁"],
    "轿厢": ["轿厢", "轿壁", "轿顶", "轿底"],
    "井道": ["井道", "底坑", "机房", "滑轮间"],
    "门锁": ["门锁", "锁钩", "电气联锁"],
    "钢丝绳端接": ["端接", "绳头", "锥套", "楔块"],
    "曳引轮": ["曳引轮", "绳轮", "轮槽"],
    "联轴器": ["联轴器", "弹性联轴", "制动轮"],
}

SUFFIXES = ["联结情况", "运转状况", "工作状况", "情况", "检查", "固定", "型式", "结构",
            "装置试验", "试验", "尺寸", "性能"]


def norm(text: str) -> str:
    s = unicodedata.normalize("NFKC", text or "")
    s = re.sub(r"[（(].*?[）)]", "", s)
    for suffix in SUFFIXES:
        if s.endswith(suffix):
            s = s[: -len(suffix)]
    return re.sub(r"[\s，,。；;、:：/]+", "", s)


def bigrams(text: str) -> set[str]:
    s = norm(text)
    return {s[i:i + 2] for i in range(max(0, len(s) - 1))}


def jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    paths = [dict(r) for r in conn.execute("SELECT * FROM path")]
    comps = [dict(r) for r in conn.execute("SELECT * FROM component")]
    jte = json.loads(JTE.read_text(encoding="utf-8"))["items"]
    expert = json.loads(EXPERT.read_text(encoding="utf-8"))["items"]

    path_by_comp: dict[str, list[dict]] = {}
    for p in paths:
        path_by_comp.setdefault(p["component_id"], []).append(p)

    def component_score(item_name: str, comp: dict) -> float:
        n = norm(item_name)
        cn = norm(comp["name"] or "")
        desc = norm(comp.get("description") or "")
        score = 0.0
        if n and cn and (n == cn):
            score += 100
        elif n and cn and (n in cn or cn in n):
            score += 60
        score += 40 * jaccard(bigrams(n), bigrams(cn))
        for key, aliases in SYNONYMS.items():
            if key in n or any(a in n for a in aliases):
                if any(a in cn or a in desc for a in aliases):
                    score += 30
        return score

    item_rows, review_rows = [], []
    covered_items = covered_options = 0
    covered_paths: set[str] = set()

    for item in jte:
        no, name = str(item["no"]), item["name"]
        scored = sorted(((component_score(name, c), c) for c in comps), key=lambda x: -x[0])
        picked = [(s, c) for s, c in scored if s >= 30][:8]
        candidate_paths: list[dict] = []
        for _, comp in picked:
            for p in path_by_comp.get(comp["component_id"], []):
                if p not in candidate_paths:
                    candidate_paths.append(p)
        if not candidate_paths:
            n = norm(name)
            for p in paths:
                text = norm(" ".join(filter(None, [p["item_name"], p["path_summary"], p["component_name"],
                                                   p["inspection_method"]])))
                if n and (n in text or any(a in text for aliases in SYNONYMS.values() for a in aliases if a in n)):
                    candidate_paths.append(p)
        candidate_paths = candidate_paths[:40]
        if candidate_paths:
            covered_items += 1
            covered_paths.update(p["path_id"] for p in candidate_paths)
        item_rows.append({
            "jte_no": no, "jte_name": name,
            "graph_system": picked[0][1]["system_id"] if picked else "",
            "graph_component": picked[0][1]["name"] if picked else "",
            "component_id": picked[0][1]["component_id"] if picked else "",
            "component_score": round(picked[0][0], 1) if picked else 0,
            "candidate_path_count": len(candidate_paths),
            "sample_path_ids": "|".join(p["path_id"] for p in candidate_paths[:5]),
            "self_decision": "", "self_note": "", "expert_decision": "", "expert_note": "",
        })

        options = expert.get(no, {}).get("options", [])
        for opt in options:
            opt_text = opt.get("text") or opt.get("raw_text") or ""
            ob = bigrams(opt_text)
            scored_paths = []
            for p in candidate_paths:
                text = " ".join(filter(None, [
                    p["path_summary"], p["state_names"], p["mechanism_steps"],
                    p["corrective_action"], p["inspection_method"], p["risk_name"],
                ]))
                score = 100 * jaccard(ob, bigrams(text))
                hits = [a for aliases in SYNONYMS.values() for a in aliases
                        if a and (a in norm(opt_text)) and (a in norm(text))]
                score += min(len(hits), 5) * 6
                if score > 0:
                    scored_paths.append((score, p))
            scored_paths.sort(key=lambda x: -x[0])
            top = scored_paths[:3]
            if top:
                covered_options += 1
            for rank, (score, p) in enumerate(top, 1):
                review_rows.append({
                    "jte_no": no, "jte_name": name,
                    "option_key": opt.get("key"), "option_text": opt_text,
                    "option_category": opt.get("category", ""),
                    "rule_measure": opt.get("measure", ""),
                    "rank": rank, "score": round(score, 1),
                    "path_id": p["path_id"],
                    "system": p["system_name"], "component": p["component_name"],
                    "path_summary": p["path_summary"],
                    "inspection": p["inspection_method"],
                    "action": p["corrective_action"],
                    "verification": p["verification_after_action"],
                    "risk": p["risk_name"],
                    "match_reason": "name/alias+bigram; candidate only",
                    "self_decision": "", "self_note": "", "expert_decision": "", "expert_note": "",
                })
            if not top:
                review_rows.append({
                    "jte_no": no, "jte_name": name,
                    "option_key": opt.get("key"), "option_text": opt_text,
                    "option_category": opt.get("category", ""),
                    "rule_measure": opt.get("measure", ""),
                    "rank": 0, "score": 0,
                    "path_id": "", "system": "", "component": "", "path_summary": "",
                    "inspection": "", "action": "", "verification": "", "risk": "",
                    "match_reason": "无候选，运行时走自由文本检索",
                    "self_decision": "", "self_note": "", "expert_decision": "", "expert_note": "",
                })

    item_fields = ["jte_no", "jte_name", "graph_system", "graph_component", "component_id",
                   "component_score", "candidate_path_count", "sample_path_ids",
                   "self_decision", "self_note", "expert_decision", "expert_note"]
    review_fields = ["jte_no", "jte_name", "option_key", "option_text", "option_category",
                     "rule_measure", "rank", "score", "path_id", "system", "component",
                     "path_summary", "inspection", "action", "verification", "risk",
                     "match_reason", "self_decision", "self_note", "expert_decision", "expert_note"]
    for filename, fields, data in (
        ("JTE-条目候选表.csv", item_fields, item_rows),
        ("JTE-图谱映射审核表.csv", review_fields, review_rows),
    ):
        with (OUT_DIR / filename).open("w", encoding="utf-8-sig", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=fields)
            writer.writeheader()
            writer.writerows(data)

    total_options = sum(len(v.get("options", [])) for v in expert.values())
    summary = {
        "kg_version": "v2_1000paths",
        "items": len(jte), "items_with_candidates": covered_items,
        "options": total_options, "options_with_candidates": covered_options,
        "candidate_paths_covered": len(covered_paths),
        "review_rows": len(review_rows),
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    (OUT_DIR / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
