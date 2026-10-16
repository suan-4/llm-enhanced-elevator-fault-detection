"""Extract the two supplied DOCX tables for review; never modifies application data.

Run from any directory: python tools/extract_expert_risk_review.py
Outputs are review artifacts in docs/prd/risk-review-v1, not a production catalog.
"""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata
import zipfile
from collections import Counter
from pathlib import Path
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
SOURCES = ROOT / "docs/规范与模板"
OUT = ROOT / "docs/prd/risk-review-v1"
W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
NUMBER = re.compile(r"^\d+\.\d+$")
ORDER = {"I": 0, "II": 1, "III": 2}


def norm(value: str) -> str:
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", value))


def category(value: str) -> str:
    result = norm(value).removesuffix("类")
    if result not in ORDER:
        raise ValueError(f"Unknown category: {value!r}")
    return result


def text(cell: ET.Element) -> str:
    lines = []
    for child in cell:
        if child.tag == W + "p":
            value = "".join(t.text or "" for t in child.iter(W + "t"))
            if value.strip():
                lines.append(value.strip())
        elif child.tag == W + "tbl":
            for row in child.findall(W + "tr"):
                lines.append(" | ".join(text(c) for c in row.findall(W + "tc")))
    return "\n".join(lines)


def blocks(cell: ET.Element) -> list[dict]:
    result = []
    for child in cell:
        if child.tag == W + "p":
            value = "".join(t.text or "" for t in child.iter(W + "t"))
            if value.strip():
                result.append({"type": "paragraph", "text": value.strip()})
        elif child.tag == W + "tbl":
            result.append({"type": "table", "rows": [
                [text(c) for c in row.findall(W + "tc")]
                for row in child.findall(W + "tr")
            ]})
    return result


def read_doc(name: str) -> tuple[dict, ET.Element, list[ET.Element]]:
    path = SOURCES / name
    with zipfile.ZipFile(path) as archive:
        root = ET.fromstring(archive.read("word/document.xml"))
    body = root.find(W + "body")
    assert body is not None
    source = {"file": path.relative_to(ROOT).as_posix(),
              "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    return source, body, body.findall(W + "tbl")


def rows(table: ET.Element):
    """Resolve vertical merges by logical grid column, not physical cell index.

    Normal project names span 3 columns; rope group/subitem rows span 1+2.
    Table row numbers are 1-based XML rows, not rendered page numbers.
    """
    active: dict[tuple[int, int], ET.Element] = {}
    for row_no, row in enumerate(table.findall(W + "tr"), 1):
        column = 0
        resolved = []
        for cell in row.findall(W + "tc"):
            prop = cell.find(W + "tcPr")
            span_node = prop.find(W + "gridSpan") if prop is not None else None
            span = int(span_node.get(W + "val", "1")) if span_node is not None else 1
            key = (column, span)
            vm = prop.find(W + "vMerge") if prop is not None else None
            if vm is not None and vm.get(W + "val", "continue") != "restart":
                if key not in active:
                    raise ValueError(f"Unresolved merged cell at row {row_no}, grid {key}")
                origin = active[key]
            else:
                for old in list(active):
                    if old[0] < column + span and column < old[0] + old[1]:
                        del active[old]
                origin = cell
                if vm is not None:
                    active[key] = cell
            resolved.append(origin)
            column += span
        yield row_no, resolved


def locate(source: dict, table: int, row: int) -> dict:
    return {"file": source["file"], "table": table, "row": row}


def extract():
    risk_source, _, risk_tables = read_doc("总表-安全评估项目汇总-v1.docx")
    eval_source, eval_body, eval_tables = read_doc("评价结果与风险评定-v1.docx")
    template_path = next(SOURCES.glob("JTE*.docx"))
    template_source, template_body, _ = read_doc(template_path.name)
    math_t = "{http://schemas.openxmlformats.org/officeDocument/2006/math}t"
    appendix_n = next(
        "".join(t.text or "" for t in p.iter() if t.tag in (W + "t", math_t))
        for p in template_body.iter(W + "p")
        if "风险情节的总数" in "".join(t.text or "" for t in p.iter(W + "t"))
    )
    assert len(risk_tables) == 1 and len(eval_tables) == 3
    risks, header_rows, inferred_rows = [], [], []
    previous_seq, previous_no, previous_name = "", "", ""
    item_counts: Counter = Counter()
    for row_no, cells in rows(risk_tables[0]):
        values = [text(c) for c in cells]
        if len(values) == 6 and norm(values[1]) == "项目编号":
            header_rows.append(row_no)
            continue
        inferred = False
        if len(values) == 6 and not values[1] and not values[2] and values[0] == previous_seq and previous_no:
            # Source row 216 has no vMerge on its blank project/name cells.
            # Keep the contextual association explicitly provisional for review.
            values[1:3] = [previous_no, previous_name]
            inferred = True
            inferred_rows.append({"row": row_no, "inferred_item_no": previous_no,
                                  "basis": "same sequence cell; adjacent project context",
                                  "status": "requires_confirmation"})
        if len(values) != 6 or not NUMBER.fullmatch(norm(values[1])):
            raise ValueError(f"Unexpected total table row {row_no}: {values}")
        seq, no, name, description, cat, measure = values
        no = norm(no)
        previous_seq, previous_no, previous_name = seq, no, name
        assert name and description and measure
        item_counts[no] += 1
        risks.append({
            "review_key": f"{no}:{item_counts[no]:02}",
            "item_no": no, "item_name_raw": name,
            "risk_text": description, "category_raw": cat,
            "category": category(cat), "measure_text": measure,
            "option_review_status": "pending_semantic_review",
            "item_association": "context_inferred_requires_confirmation" if inferred else "source_explicit_or_merged",
            "source": locate(risk_source, 1, row_no),
        })

    matrix, actions = {}, {}
    for row_no, cells in rows(eval_tables[0]):
        if row_no == 1:
            continue
        cat, grades, action = [text(c) for c in cells]
        cat = category(cat)
        actions[cat] = {"text": action, "source": locate(eval_source, 1, row_no)}
        for grade in re.findall(r"[1-4][A-F]", grades):
            assert grade not in matrix
            matrix[grade] = cat
    assert set(matrix) == {f"{s}{p}" for s in range(1, 5) for p in "ABCDEF"}

    evaluations = []
    for row_no, cells in rows(eval_tables[2]):
        values = [text(c) for c in cells]
        if row_no <= 2:
            continue
        assert len(values) in (7, 8), (row_no, values)
        no, name = values[:2]
        has_sub = len(values) == 8
        sub = values[2] if has_sub else ""
        req_cell = cells[3 if has_sub else 2]
        result, severity, probability, cat = values[-4:]
        assert NUMBER.fullmatch(norm(no)) and result in ("符合", "不符合")
        grade = norm(severity + probability)
        assert matrix[grade] == category(cat), (row_no, grade, cat)
        evaluations.append({
            "item_no": norm(no), "name_raw": name, "sub_raw": sub,
            "requirements": text(req_cell), "requirement_blocks": blocks(req_cell),
            "result": result, "severity": int(severity),
            "probability": norm(probability), "category_raw": cat,
            "category": category(cat), "source": locate(eval_source, 3, row_no),
        })
    item_numbers = list(dict.fromkeys(e["item_no"] for e in evaluations))
    assert set(item_counts) == set(item_numbers)
    for no in item_numbers:
        assert Counter(e["result"] for e in evaluations if e["item_no"] == no) == {"符合": 1, "不符合": 1}

    catalog = json.loads((ROOT / "backend/app/data/jte_items.json").read_text(encoding="utf-8"))["items"]
    assert item_numbers == [i["no"] for i in catalog], "Template order differs"
    comparisons, requirement_differences, name_differences = [], [], []
    total_name_differences = []
    for no in item_numbers:
        risk = next(r for r in risks if r["item_no"] == no)
        ev = next(e for e in evaluations if e["item_no"] == no)
        if norm(risk["item_name_raw"]) != norm(ev["name_raw"] + ev["sub_raw"]):
            total_name_differences.append({"item_no": no, "total_name": risk["item_name_raw"],
                                           "evaluation_name": ev["name_raw"] + ev["sub_raw"]})
    assert list(item_counts) == item_numbers, "Total table project order differs"
    for item in catalog:
        ev = next(e for e in evaluations if e["item_no"] == item["no"] and e["result"] == "符合")
        if norm(ev["requirements"]) != norm("".join(item["req"])):
            requirement_differences.append(item["no"])
        if norm(ev["name_raw"] + ev["sub_raw"]) != norm(item["name"] + item["sub"]):
            name_differences.append(item["no"])
    for risk in risks:
        ev = next(e for e in evaluations if e["item_no"] == risk["item_no"] and e["result"] == "不符合")
        if risk["category"] != ev["category"]:
            comparisons.append({"review_key": risk["review_key"], "item_no": risk["item_no"],
                                "risk_category": risk["category"], "evaluation_category": ev["category"],
                                "risk_source_row": risk["source"]["row"], "evaluation_source_row": ev["source"]["row"]})
    thirds = [r for r in risks if r["category"] == "III"]
    notes = ["".join(t.text or "" for t in p.iter(W + "t")) for p in eval_body.findall(W + "p")]
    na_rows = [[text(c) for c in r.findall(W + "tc")] for r in eval_tables[1].findall(W + "tr")]
    duplicates = [list(key) for key, n in Counter((r["item_no"], r["risk_text"], r["category"], r["measure_text"]) for r in risks).items() if n > 1]
    audit = {
        "status": "review_only_not_for_production", "sources": [risk_source, eval_source],
        "appendix_n_evidence": {"source": template_source, "text": appendix_n,
                                "scope": "n definition only; equation layout not verified"},
        "summary": {"item_count": len(item_numbers), "risk_record_count": len(risks),
                    "category_counts": dict(Counter(r["category"] for r in risks)),
                    "evaluation_record_count": len(evaluations), "matrix_cell_count": len(matrix),
                    "excluded_header_rows": header_rows,
                    "category_mismatch_records": len(comparisons)},
        "confirmed_rule": {"multi_risk_item_category": "most_severe", "severity_order": ["I", "II", "III"]},
        "category_mismatches": comparisons,
        "context_inferred_project_rows": inferred_rows,
        "non_III_category_mismatches": [c for c in comparisons if c["risk_category"] != "III"],
        "III_records_for_semantic_review": [r["review_key"] for r in thirds],
        "requirement_differences_from_current_catalog": requirement_differences,
        "name_differences_from_current_catalog": name_differences,
        "total_vs_evaluation_name_differences": total_name_differences,
        "exact_duplicate_records": duplicates,
        "not_applicable_source_rows": na_rows,
        "evaluation_document_body_paragraphs": [n for n in notes if n.strip()],
        "checks": ["all source data rows accounted for", "every risk has category and measure",
                   "each item has exactly one compliant and one noncompliant evaluation",
                   "all evaluation triplets agree with the 24-cell matrix", "66-item template order matches",
                   "merged group/subitem names resolved", "nested requirement tables retained"],
    }
    return risk_source, eval_source, risks, evaluations, matrix, actions, audit


def md(value) -> str:
    return str(value).replace("|", "\\|").replace("\n", "<br>")


def write_outputs():
    rs, es, risks, evaluations, matrix, actions, audit = extract()
    OUT.mkdir(parents=True, exist_ok=True)
    payloads = {
        "risk-options.review.json": {"status": "review_only", "source": rs, "records": risks},
        "evaluations.review.json": {"status": "review_only", "source": es,
                                    "matrix": matrix, "category_actions": actions, "records": evaluations},
        "audit.review.json": audit,
    }
    for filename, data in payloads.items():
        (OUT / filename).write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    s = audit["summary"]
    lines = ["# 风险数据整理与规则对照", "", "日期：2026-10-15。状态：待评审；未接入页面、算法或业务数据库。", "",
             "## 核对结果", "",
             f"两份文档覆盖相同的 {s['item_count']} 个项目，顺序与当前条目库一致。总表提取 {s['risk_record_count']} 条记录，"
             f"类别分布为 I {s['category_counts'].get('I', 0)}、II {s['category_counts'].get('II', 0)}、III {s['category_counts'].get('III', 0)}。",
             f"总表共 {s['risk_record_count'] + len(s['excluded_header_rows'])} 行，已排除表头行 {s['excluded_header_rows']}；重复表头不算风险记录。",
             f"评价表提取 {s['evaluation_record_count']} 条符合/不符合样例，全部与 {s['matrix_cell_count']} 格风险矩阵一致。",
             "", "用户已确认：同一项目可存在多个风险，项目最终只取一个类别，按 I > II > III 取最严重类别。所有风险和对应措施保留。",
             "", "记录数量不等于可直接上线的选项数量：尤其 III 类包含正常描述，需要逐条语义审核，不能仅按类别自动删除。",
             "", "总表第216行的项目编号、名称为空且未标合并；同序号和上下文指向12.10，暂关联供审核，未视为原文明确归属。具体记录见 audit.review.json。",
             "", "## 来源", ""]
    for source in (rs, es, audit["appendix_n_evidence"]["source"]):
        lines += [f"- 文件：`{source['file']}`；SHA-256：`{source['sha256']}`。"]
    lines += ["", "来源行号为 DOCX XML 中的表行编号，从 1 开始；不代表页码。JSON 的 review_key 仅为本次核对定位键，不是正式风险 ID。", "",
              "## 逐项目对照", "", "符合/不符合列写作 严重程度 + 概率等级 / 类别；总表类别范围只展示原始分布，不代表当前项目已选择全部风险。", "",
              "| 项目编号 | 项目 | 总表记录数 | 总表类别范围 | 符合样例 | 不符合样例 |", "| --- | --- | ---: | --- | --- | --- |"]
    for no in dict.fromkeys(e["item_no"] for e in evaluations):
        yes = next(e for e in evaluations if e["item_no"] == no and e["result"] == "符合")
        bad = next(e for e in evaluations if e["item_no"] == no and e["result"] == "不符合")
        rr = [r for r in risks if r["item_no"] == no]
        cats = "/".join(sorted({r["category"] for r in rr}, key=ORDER.get))
        lines.append(f"| {no} | {md(yes['name_raw'] + ' ' + yes['sub_raw'])} | {len(rr)} | {cats} | {yes['severity']}{yes['probability']} / {yes['category']} | {bad['severity']}{bad['probability']} / {bad['category']} |")
    lines += ["", "## 需要处理的类别差异", "",
              f"共有 {s['category_mismatch_records']} 条总表记录的类别不同于该项目的不符合样例。差异必须保留，不能把总表类别批量覆盖为样例类别。",
              "下面列出非 III 类差异；III 类记录另列供语义审核。用户确认的最严重类别规则确定了汇总方式，但不能唯一确定严重程度和概率等级。", "",
              "| 定位键 | 总表行 | 项目编号 | 总表类别 | 不符合样例类别 | 评价表行 |", "| --- | ---: | --- | --- | --- | ---: |"]
    for c in audit["non_III_category_mismatches"]:
        lines.append(f"| {c['review_key']} | {c['risk_source_row']} | {c['item_no']} | {c['risk_category']} | {c['evaluation_category']} | {c['evaluation_source_row']} |")
    lines += ["", "## III 类记录逐条审核", "", "以下保留原文，不预先判定全部为符合或全部为不符合。措施原文见风险数据 JSON。", "",
              "| 定位键 | 总表行 | 原文 |", "| --- | ---: | --- |"]
    for r in risks:
        if r["category"] == "III":
            lines.append(f"| {r['review_key']} | {r['source']['row']} | {md(r['risk_text'])} |")
    lines += ["", "## 风险矩阵", "", "| 严重程度 \\ 概率等级 | A | B | C | D | E | F |", "| --- | --- | --- | --- | --- | --- | --- |"]
    for severity in range(1, 5):
        lines.append("| " + str(severity) + " | " + " | ".join(matrix[f"{severity}{p}"] for p in "ABCDEF") + " |")
    lines += ["", "表1的通用措施原文如下，不能覆盖总表的具体措施：", ""]
    for cat, action in actions.items():
        lines.append(f"- {cat}：{action['text']}")
    lines += ["", "## 无此项及模板内容差异", "",
              "评价文档原注：当输入项目不在表3检索范围内时，按表2输出报告。表2数据行的项目格为“无此项”，评价结果和风险评定值为“-”。该情形与现场没有相应部件是否同义，尚未确认。", "",
              f"与当前目录比较：要求内容差异项目 {audit['requirement_differences_from_current_catalog']}；名称差异项目 {audit['name_differences_from_current_catalog']}。比较仅消除空白和全半角差异。",
              "总表与评价文档另有名称写法差异：", "",
              "| 项目编号 | 总表名称 | 评价文档名称 |", "| --- | --- | --- |"]
    for item in audit["total_vs_evaluation_name_differences"]:
        lines.append(f"| {item['item_no']} | {md(item['total_name'])} | {md(item['evaluation_name'])} |")
    lines += ["", "两份资料按项目编号关联并保留各自名称；不能宣称全部名称原文完全相同。", "",
              "12.4 断丝要求包含嵌套表格，已在 requirement_blocks 中保留表行结构；不能只取正文段落而遗漏阈值表。", "",
              "## 待确认业务问题", "",
              "1. 项目类别取最严重风险后，严重程度和概率等级如何取得？若评价样例组合与所选风险类别不一致，不能反推或沿用冲突组合。",
              f"2. JTE模板附录A原文：{audit['appendix_n_evidence']['text']} 需确认这里的风险情节与本次项目级类别汇总如何对应，以及符合、无此项如何计入；不是缺少公式，不另造公式。",
              "3. 上述 III 类原文逐条属于正常描述还是低风险异常？不得只凭类别过滤选项。",
              "4. 表2的检索范围外与现场无此项是否采用相同输出？",
              "", "## 文件与复核方法", "",
              "- risk-options.review.json：总表全部风险、类别、措施、来源行和核对键。",
              "- evaluations.review.json：符合/不符合样例、24格矩阵、措施、要求原文及嵌套表。",
              "- audit.review.json：统计、全部类别差异、模板差异、来源哈希和检查结果。",
              "- 风险选项与措施原文.md：按项目排列的全部风险与措施，便于逐条审核。",
              "- 重建命令：`python tools/extract_expert_risk_review.py`。仅写本审核目录，不修改运行数据。",
              "", "本次为原文结构和内容核对，不作 Word 页面版式一致性验收。未建立 66 个模板项目与旧 Neo4j 41 个 INS 项目的映射，也未进行模型微调。", ""]
    (OUT / "规则对照与待确认问题.md").write_text("\n".join(lines), encoding="utf-8")
    detail = ["# 风险选项与措施原文", "", "状态：待审核原文清单，未接入系统。", "",
              "按总表顺序完整保留484条记录。类别统一显示为 I、II、III；原始类别写法见 JSON。定位行是原DOCX表行号。",
              "39条III类原文已单独列入对照文档供审核；建议将其中正常描述排除出不符合选项，但本清单不删除任何原文。",
              "本清单不等于已发布选项库；第216行的项目归属属于上下文推定，须确认。", ""]
    previous = None
    for risk in risks:
        if risk["item_no"] != previous:
            detail += [f"## {risk['item_no']} {risk['item_name_raw']}", ""]
            previous = risk["item_no"]
        detail += [f"### {risk['review_key']}　{risk['category']}类　总表第{risk['source']['row']}行", "",
                   risk["risk_text"], "", "降低风险措施：" + risk["measure_text"], ""]
        if risk["item_association"] == "context_inferred_requires_confirmation":
            detail += ["项目归属提示：原格为空，按同序号及相邻项目暂关联，待确认。", ""]
    (OUT / "风险选项与措施原文.md").write_text("\n".join(detail), encoding="utf-8")
    print(json.dumps(audit["summary"], ensure_ascii=False))
    print("Non-III differences:", json.dumps(audit["non_III_category_mismatches"], ensure_ascii=False))
    print("Requirement differences:", audit["requirement_differences_from_current_catalog"])
    print("Name differences:", audit["name_differences_from_current_catalog"])
    print("Output:", OUT)


if __name__ == "__main__":
    write_outputs()
