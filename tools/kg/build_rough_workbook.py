#!/usr/bin/env python3
"""Build the pre-annotated (AI rough review) workbook for the human reviewer."""
from __future__ import annotations
import csv, json
from collections import Counter, defaultdict
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill, Border, Side
from openpyxl.worksheet.datavalidation import DataValidation

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "docs" / "kg-review"
OUT = SRC / "JTE-图谱映射审核表-粗审.xlsx"

HEADER_FILL = PatternFill("solid", fgColor="1B5E7A")
HEADER_FONT = Font(color="FFFFFF", bold=True)
THIN = Side(style="thin", color="D9E2E8")
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
FILL = {
    "批准": PatternFill("solid", fgColor="E8F5E9"),
    "待定": PatternFill("solid", fgColor="FFF8E1"),
    "驳回": PatternFill("solid", fgColor="F3F4F6"),
    "无合适候选": PatternFill("solid", fgColor="FDE7E7"),
}


def load(name: str) -> list[dict]:
    with (SRC / name).open(encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def style(ws, widths: dict[str, int]) -> None:
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions
    for cell in ws[1]:
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border = BORDER
    for col, width in widths.items():
        ws.column_dimensions[col].width = width
    for row in ws.iter_rows(min_row=2):
        for cell in row:
            cell.border = BORDER
            cell.alignment = Alignment(vertical="top", wrap_text=True)


def main() -> int:
    rows = load("JTE-图谱映射审核表-粗审.csv")
    items = load("JTE-条目候选表.csv")
    summary = json.loads((SRC / "rough_review_summary.json").read_text(encoding="utf-8"))

    wb = Workbook()
    info = wb.active
    info.title = "说明"
    lines = [
        ("JTE 66 项 × 知识图谱 v2：AI 粗审建议表", True),
        ("", False),
        ("这份表是我替你先做的一轮“粗审”，self_decision 已预填建议，你只需逐行判断/修改。", False),
        ("颜色：绿色=建议批准；黄色=待你判断；灰色=建议驳回；红色=无合适候选。", False),
        ("", False),
        ("你的操作", True),
        ("1. 先看绿色（建议批准）：确认“这确实是一条对应的故障演化路径”。", False),
        ("2. 重点看黄色（待定）：候选可能相关但证据不足，按你的判断改成 批准/驳回/无合适候选。", False),
        ("3. 灰色/红色可快速扫过：若你发现漏掉了正确路径，可在 self_note 里写正确 path_id。", False),
        ("4. self_decision 下拉：批准 / 驳回 / 无合适候选 / 待定。", False),
        ("5. 专家复核列 expert_* 留空，下一轮再填。", False),
        ("", False),
        ("口径提醒", True),
        ("- 图谱是故障演化候选（confidence=0.4，verified=false），不是已签核结论。", False),
        ("- 不要为了覆盖率勉强批准；驳回是正常操作。", False),
        ("- 规则表的处置 measure 与得分口径不变；图谱只提供路径、检查、整改/复验补充。", False),
        ("", False),
        (f"AI 粗审统计：445 情形 → 建议批准 {summary['counts'].get('批准',0)}，"
         f"待定 {summary['counts'].get('待定',0)}，驳回 {summary['counts'].get('驳回',0)}，"
         f"无合适候选 {summary['counts'].get('无合适候选',0)}。", False),
        ("覆盖：60/66 条目有候选，395/445 情形有候选，592 条路径进入候选池。", False),
        ("", False),
        ("生成脚本：tools/kg/rough_review_mapping.py；数据：v2_1000paths（1,052 路径）。", False),
    ]
    for i, (text, bold) in enumerate(lines, 1):
        cell = info.cell(row=i, column=1, value=text)
        cell.font = Font(bold=bold, size=13 if i == 1 else 10.5,
                         color="1B5E7A" if bold else "333333")
        cell.alignment = Alignment(wrap_text=True, vertical="top")
    info.column_dimensions["A"].width = 115
    info.sheet_view.showGridLines = False

    # item summary
    ws_items = wb.create_sheet("条目候选")
    cols_i = ["jte_no", "jte_name", "graph_system", "graph_component", "component_id",
              "component_score", "candidate_path_count", "sample_path_ids",
              "self_decision", "self_note", "expert_decision", "expert_note"]
    ws_items.append(cols_i)
    for row in items:
        ws_items.append([row.get(c, "") for c in cols_i])
    style(ws_items, {"A": 9, "B": 26, "C": 16, "D": 30, "E": 34, "F": 10, "G": 9,
                     "H": 70, "I": 12, "J": 30, "K": 12, "L": 30})
    dv_items = DataValidation(type="list", formula1='"批准,驳回,无合适候选,待定"', allow_blank=True)
    ws_items.add_data_validation(dv_items)
    dv_items.add(f"I2:I{ws_items.max_row}")

    # per-item overview
    ws_sum = wb.create_sheet("按系统汇总")
    ws_sum.append(["jte_no", "jte_name", "情形数", "建议批准", "待定", "驳回", "无合适候选", "覆盖率"])
    by_item = defaultdict(lambda: Counter())
    for r in rows:
        by_item[(r["jte_no"], r["jte_name"])][r["suggested_decision"]] += 1
    for (no, name), c in sorted(by_item.items(), key=lambda kv: [int(x) if x.isdigit() else x for x in kv[0][0].split(".")]):
        total = sum(c.values())
        ws_sum.append([no, name, total, c.get("批准", 0), c.get("待定", 0),
                       c.get("驳回", 0), c.get("无合适候选", 0),
                       f"{(total - c.get('无合适候选', 0)) / total:.0%}" if total else "0%"])
    style(ws_sum, {"A": 9, "B": 30, "C": 8, "D": 10, "E": 8, "F": 8, "G": 12, "H": 8})

    # main review sheet
    ws = wb.create_sheet("情形审核-粗审")
    cols = ["jte_no", "jte_name", "option_key", "option_text", "option_category",
            "rule_measure", "rank", "score", "suggested_decision", "suggestion_confidence",
            "suggestion_reason", "path_id", "system", "component", "path_summary",
            "inspection", "action", "verification", "risk",
            "self_decision", "self_note", "expert_decision", "expert_note"]
    ws.append([c + ("（已预填，可改）" if c == "self_decision" else "") for c in cols])
    for r in rows:
        line = []
        for c in cols:
            if c == "self_decision":
                line.append(r.get("suggested_decision", ""))
            else:
                line.append(r.get(c, ""))
        ws.append(line)
    style(ws, {"A": 8, "B": 22, "C": 9, "D": 52, "E": 7, "F": 42, "G": 6, "H": 7,
                "I": 12, "J": 9, "K": 34, "L": 38, "M": 14, "N": 28, "O": 52,
                "P": 38, "Q": 38, "R": 38, "S": 26, "T": 12, "U": 26, "V": 10, "W": 24})
    # colour by suggested decision
    for r_idx in range(2, ws.max_row + 1):
        decision = ws.cell(row=r_idx, column=9).value
        fill = FILL.get(decision)
        if fill:
            for c_idx in range(1, len(cols) + 1):
                ws.cell(row=r_idx, column=c_idx).fill = fill
    dv = DataValidation(type="list", formula1='"批准,驳回,无合适候选,待定"', allow_blank=True)
    ws.add_data_validation(dv)
    dv.add(f"T2:T{ws.max_row}")
    dv2 = DataValidation(type="list", formula1='"批准,驳回,待定"', allow_blank=True)
    ws.add_data_validation(dv2)
    dv2.add(f"V2:V{ws.max_row}")

    wb.save(OUT)
    print(str(OUT))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
