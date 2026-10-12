#!/usr/bin/env python3
"""从 JTE-09-R02-3.00 报告模板 docx 抽取评价条目，生成后端条目目录。

用法：
    python tools/gen_jte_items.py <模板.docx> [输出.json]

默认输出到 backend/app/data/jte_items.json。

抽取规则（对应模板评价结果表）：
  - 只接受形如 1.7 / 12.10 的项目编号行
  - 项目编号后的单元格为「项目」；若该单元格带 vMerge restart，说明它是
    纵向合并的表头（如「钢丝绳」「包覆绳(带)」），其右侧单元格为子项名
  - 子项行的项目格为 vMerge continue，需沿用上一个分组名
  - 末列为「评价内容与要求」，按段落拆行；以 a) b) c) 开头的行另存为
    「不符合」候选情形
"""

from __future__ import annotations

import json
import re
import sys
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
NO_RE = re.compile(r"^\d+(\.\d+)?$")
CLAUSE_RE = re.compile(r"^[a-h]\)")

# 模板中评价结果表的表序号（文档 body 内第 3～8 张表）
TABLE_RANGE = range(2, 8)


def cell_text(tc: ET.Element) -> str:
    lines = []
    for para in tc.findall(W + "p"):
        text = "".join(t.text or "" for t in para.iter(W + "t")).strip()
        if text:
            lines.append(text)
    return "\n".join(lines)


def vmerge(tc: ET.Element) -> str | None:
    pr = tc.find(W + "tcPr")
    if pr is None:
        return None
    vm = pr.find(W + "vMerge")
    if vm is None:
        return None
    return "restart" if (vm.get(W + "val") or "continue") == "restart" else "continue"


def norm(text: str) -> str:
    return " ".join(text.split())


def extract(docx_path: Path) -> list[dict]:
    with zipfile.ZipFile(docx_path) as zf:
        body = ET.fromstring(zf.read("word/document.xml")).find(W + "body")

    tables = [child for child in body if child.tag == W + "tbl"]
    items: list[dict] = []
    last_group: str | None = None

    for table_index in TABLE_RANGE:
        if table_index >= len(tables):
            break
        for row in tables[table_index].findall(W + "tr"):
            cells = row.findall(W + "tc")
            if len(cells) < 3:
                continue

            no = cell_text(cells[0]).strip()
            if not NO_RE.match(no):
                continue  # 表头行

            name_cell, second_cell = cells[1], cells[2]
            name_text = cell_text(name_cell).strip()
            second_text = cell_text(second_cell).strip()
            merge = vmerge(name_cell)

            if merge == "continue":
                name, sub = last_group or "", norm(second_text)
                req_cell = cells[3] if len(cells) > 3 else None
            elif merge == "restart":
                last_group = norm(name_text)
                name, sub = last_group, norm(second_text)
                req_cell = cells[3] if len(cells) > 3 else None
            else:
                last_group = None
                name, sub, req_cell = norm(name_text), "", second_cell

            req = [norm(line) for line in cell_text(req_cell).split("\n") if line.strip()] if req_cell is not None else []
            opts = [line for line in req if CLAUSE_RE.match(line)]
            items.append({"no": no, "name": name, "sub": sub, "req": req, "opts": opts})

    return items


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2

    docx_path = Path(sys.argv[1])
    if not docx_path.is_file():
        print(f"找不到模板文件：{docx_path}", file=sys.stderr)
        return 1

    default_out = Path(__file__).resolve().parent.parent / "backend" / "app" / "data" / "jte_items.json"
    out_path = Path(sys.argv[2]) if len(sys.argv) > 2 else default_out

    items = extract(docx_path)
    if not items:
        print("未抽取到任何条目，请检查模板结构是否变化", file=sys.stderr)
        return 1

    payload = {
        "source": docx_path.name,
        "count": len(items),
        "items": items,
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")

    with_opts = sum(1 for item in items if item["opts"])
    empty = [item["no"] for item in items if not item["req"]]
    print(f"条目 {len(items)} 条，含预设情形 {with_opts} 条")
    print(f"编号范围 {items[0]['no']} → {items[-1]['no']}")
    if empty:
        print(f"警告：以下条目缺少评价内容与要求 {empty}", file=sys.stderr)
    print(f"已写入 {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
