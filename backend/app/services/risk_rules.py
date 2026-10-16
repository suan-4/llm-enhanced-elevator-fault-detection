"""附录A 的分值与等级计算；风险类别由 expert_risk 按专家材料查询。

是否启用综合计分、哪些项目进入 n，由已确认的计分口径决定：
    G = 100 · Σv / (2n)   当所有 v ≠ 0
    G = 0                 当存在 v = 0（Ⅰ 类，一票否决）或 Σv < 0
    无风险情节时视为 100 分
"""
from __future__ import annotations

# 表A.1 风险类别分值
CATEGORY_VALUE = {"Ⅰ类": 0, "Ⅱ类": -1, "Ⅲ类": 2}

# 附页「降低风险措施」：Ⅰ、Ⅱ 类取自模板样例；Ⅲ 类模板未给，暂沿用 Ⅱ 类表述
CATEGORY_MEASURE = {
    "Ⅰ类": "建议结合技术及经济可行性，加装或改进安全保护装置（措施）来消除或降低风险。",
    "Ⅱ类": "应采用修理、调整、更换等措施消除或降低风险。",
    "Ⅲ类": "应采用修理、调整、更换等措施消除或降低风险。",
}

def score_of(categories: list[str]) -> float:
    """附录A 综合安全状况得分 G。"""
    n = len(categories)
    if n == 0:
        return 100
    values = [CATEGORY_VALUE.get(c, 0) for c in categories]
    if any(v == 0 for v in values) or sum(values) < 0:
        return 0
    return round(100 * sum(values) / (2 * n), 2)


def grade_of(score: float) -> str:
    """表A.2 综合安全状况等级。"""
    if score >= 90:
        return "一级"
    if score >= 75:
        return "二级"
    if score >= 60:
        return "三级"
    return "四级"


def overview_text(categories: list[str], score: float) -> str:
    """评估概况文案（报告正文页用）。"""
    count = {"Ⅰ类": 0, "Ⅱ类": 0, "Ⅲ类": 0}
    for category in categories:
        if category in count:
            count[category] += 1
    return (
        f"1、存在Ⅰ类风险　{count['Ⅰ类']}　项，Ⅱ类风险　{count['Ⅱ类']}　项。\n"
        f"2、综合安全状况得分：{score}"
    )
