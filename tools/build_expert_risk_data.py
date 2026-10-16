"""Build the small runtime lookup from the two expert documents, without DB changes."""
from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from pathlib import Path

from extract_expert_risk_review import extract

# Individually read normal observations, not a blanket filter on risk category.
NORMAL_KEYS = set("""
8.6:01 9.1:01 9.2:01 9.6:01 9.8:01 9.12:01 10.2:01 10.3:01 10.5:01
11.1:01 11.4:01 12.1:01 12.2:01 12.3:01 12.4:01 12.5:01 12.8:01 12.9:01
12.10:11 14.9:20 16.1:33 16.6:14 16.8:15 16.11:12 16.12:09 17.1:09 17.2:08
17.3:10 17.4:13 17.5:15 17.6:19 17.8:05 17.9:04 17.10:03 17.11:08
18.1:10 18.2:07 18.3:06 18.4:08
""".split())

# User confirmed 2026-10-16: these three differences follow the evaluation
# table's unfit reference. Keep the original category and source for audit.
EVALUATION_OVERRIDES = {"12.1:05", "16.1:32", "16.6:13"}


def build() -> dict:
    risk_source, eval_source, risks, evaluations, matrix, _, _ = extract()
    assert len(NORMAL_KEYS) == 39
    assert NORMAL_KEYS <= {r["review_key"] for r in risks}
    items = {}
    for e in evaluations:
        entry = items.setdefault(e["item_no"], {"options": [], "references": {}})
        code = "fit" if e["result"] == "符合" else "unfit"
        entry["references"][code] = {k: e[k] for k in ("severity", "probability", "category", "source")}
    for r in risks:
        if r["review_key"] in NORMAL_KEYS:
            continue
        assert r["item_association"] == "source_explicit_or_merged"
        items[r["item_no"]]["options"].append({
            "key": r["review_key"],
            "text": re.sub(r"^\s*\d{1,2}[.、)）]\s*", "", r["risk_text"]),
            "raw_text": r["risk_text"], "category": r["category"],
            "measure": r["measure_text"], "source": r["source"],
        })
    for item in items.values():
        counts = Counter(re.sub(r"\s+", "", r["text"]) for r in item["options"])
        for r in item["options"]:
            if r["key"] in EVALUATION_OVERRIDES:
                reference = item["references"]["unfit"]
                r["category_override"] = {
                    "original_category": r["category"], "source": reference["source"],
                    "basis": "user_confirmed_evaluation_unfit_2026-10-16",
                }
                r["category"] = reference["category"]
            if counts[re.sub(r"\s+", "", r["text"])] > 1:
                r["text"] += f"（对应措施：{r['measure']}）"
    content = {"sources": [risk_source, eval_source], "matrix": matrix, "items": items,
               "excluded_normal_keys": sorted(NORMAL_KEYS), "score_basis": "applicable_items"}
    digest = hashlib.sha256(json.dumps(content, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
    return {"version": "expert-" + digest[:12], **content}


if __name__ == "__main__":
    path = Path(__file__).resolve().parents[1] / "backend/app/data/expert_risks.json"
    payload = build()
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"{len(payload['items'])} items, {sum(len(i['options']) for i in payload['items'].values())} risk options -> {path}")
