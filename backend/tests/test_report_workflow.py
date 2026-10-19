"""报告作业测试：草稿 → 生成（编号/风险值/得分）→ 作废 / 复制 / 删除。

这几条是"报告"这条主线上最要紧的规则：
  - 草稿保存全部状态，抬头要同步提升成可检索的列；
  - 生成时才分配编号，且编号只增不减、作废不回收；
  - 得分等级必须按附录A 公式算（大模型不参与定级）；
  - 复制为新建只带抬头，不带上一次的评价结果。

不依赖 pytest：python backend/tests/test_report_workflow.py
"""
from __future__ import annotations

import sys
import asyncio
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tests._tempdb import TempDB  # noqa: E402

from app.services import auth_service, report_workflow, risk_rules, expert_risk  # noqa: E402
from app.services.llm_service import llm_service  # noqa: E402

FORM = {
    "clientName": "佛山某公司",
    "userName": "佛山某公司",
    "deviceCategory": "曳引驱动电梯",
    "productNo": "44786091",
    "installSite": "3号楼",
    "assessDate": "2026-10-13",
}


def _actor() -> dict:
    account, _ = auth_service.init_system(
        display_name="张三", username="zhangsan", password="elevator2026"
    )
    return account


def _items(unfit: int = 0, total: int = 66) -> list[dict]:
    catalog = json.loads(report_workflow.ITEMS_PATH.read_text(encoding="utf-8"))["items"]
    # Use real template numbers; put the I-category governor first for veto tests.
    catalog.sort(key=lambda item: item["no"] != "1.9")
    items = []
    for i, entry in enumerate(catalog[:total]):
        no = entry["no"]
        if i < unfit:
            items.append({"no": no, "result": "unfit",
                          "reasons": [expert_risk.options(no)[0]["text"]], "other_text": ""})
        else:
            items.append({"no": no, "result": "fit", "reasons": [], "other_text": ""})
    return items


def test_create_save_and_get_draft() -> None:
    """草稿：整存整取，并且抬头同步提升成可检索的列。"""
    with TempDB():
        actor = _actor()
        report = report_workflow.create_draft(actor=actor)
        assert report["status"] == "draft" and report["report_no"] is None
        assert isinstance(report["id"], str), "对外 id 必须是字符串"

        result = report_workflow.save_content(
            report["id"], form=FORM, items=_items(total=3), actor=actor
        )
        assert result["counters"] == {"total": 3, "done": 3, "unfit": 0, "missing": 0}

        draft = report_workflow.get_draft(report["id"])
        assert draft["form"]["clientName"] == "佛山某公司"
        assert [i["no"] for i in draft["items"]] == ["1.9", "1.7", "1.10"]
        # 提升列（用于列表检索）
        detail = report_workflow.get_report(report["id"])
        assert detail["client_name"] == "佛山某公司"
        assert detail["product_no"] == "44786091"
        assert detail["assessed_on"] == "2026-10-13"


def test_generate_assigns_number_and_computes_grade() -> None:
    """生成：分配编号、算出风险评定值与得分等级、状态变已生成。"""
    with TempDB():
        actor = _actor()
        report = report_workflow.create_draft(actor=actor)
        # 选择限速器运行异响，专家总表为Ⅰ类 → 一票否决。
        report_workflow.save_content(
            report["id"], form=FORM, items=_items(unfit=1), actor=actor
        )
        generated = asyncio.run(report_workflow.generate(report["id"], actor=actor))

        assert generated["status"] == "generated"
        assert generated["report_no"].startswith("GDSEI-JTE-")
        assert generated["report_no"].endswith("-001"), generated["report_no"]
        assert generated["generated_at"]
        assert generated["score"] == 0 and generated["grade"] == "四级"
        assert "1.9" in generated["risks"], generated["risks"]
        assert generated["risks"]["1.9"]["category"] == "Ⅰ类"
        assert generated["narrative"], "叙述文字不能为空（模型不可用时也要有兜底）"
        assert generated["provenance"].get("llm_used") is False


def test_generate_rejects_incomplete_items() -> None:
    """还有未填项时拒绝生成，并说明还差几项。"""
    with TempDB():
        actor = _actor()
        report = report_workflow.create_draft(actor=actor)
        items = _items(total=3)
        items[1]["result"] = ""
        report_workflow.save_content(report["id"], form=FORM, items=items, actor=actor)
        try:
            asyncio.run(report_workflow.generate(report["id"], actor=actor))
        except ValueError as e:
            assert "未填" in str(e)
        else:
            raise AssertionError("有未填项时不应允许生成")


def _prepare(actor: dict) -> str:
    report = report_workflow.create_draft(actor=actor)
    report_workflow.save_content(report["id"], form=FORM, items=_items(unfit=2), actor=actor)
    return report["id"]


def test_generate_uses_llm_when_available() -> None:
    """模型可用时：叙述文字用模型输出，并在溯源里记明用了模型。"""
    with TempDB():
        actor = _actor()
        rid = _prepare(actor)
        seen: dict = {}

        async def fake_generate(prompt_json: str) -> str:
            seen["prompt"] = prompt_json
            return '{"overview_keys":["finding","score"]}'

        original = llm_service.generate
        llm_service.generate = fake_generate  # type: ignore[assignment]
        try:
            report = asyncio.run(report_workflow.generate(rid, use_llm=True, actor=actor))
        finally:
            llm_service.generate = original  # type: ignore[assignment]

        assert report["narrative"].startswith("本次评估共发现 2 项不符合"), report["narrative"]
        assert report["provenance"]["llm_used"] is True
        # 提示词里必须带上真实数据，否则模型没得可写
        assert "GDSEI" not in seen["prompt"], "提示词里不该出现报告编号（还没分配）"
        assert "限速器运行中有异响" in seen["prompt"], "不符合情形要进提示词"
        assert "综合安全状况" in seen["prompt"] or "得分" in seen["prompt"]


def test_generate_falls_back_when_llm_fails() -> None:
    """模型不可用（或返回空）时：仍然出报告，叙述文字走规则摘要，并记明原因。"""
    with TempDB():
        actor = _actor()
        rid = _prepare(actor)

        async def broken(prompt_json: str) -> str:
            raise RuntimeError("RKLLM服务器响应超时")

        original = llm_service.generate
        llm_service.generate = broken  # type: ignore[assignment]
        try:
            report = asyncio.run(report_workflow.generate(rid, use_llm=True, actor=actor))
        finally:
            llm_service.generate = original  # type: ignore[assignment]

        assert report["status"] == "generated", "模型挂了也要能出报告"
        assert report["narrative"], "降级后叙述文字不能为空"
        assert report["provenance"]["llm_used"] is False
        assert "超时" in str(report["provenance"].get("llm_error", ""))
        assert report['provenance']['llm_status'] == 'degraded', '降级原因在页面工具栏展示'
        assert "未使用大模型" not in report["narrative"], "模型运行提示不能进入报告正文"


def test_void_keeps_number_and_delete_rules() -> None:
    """作废保留编号；已作废可删，已生成不可删。"""
    with TempDB():
        actor = _actor()
        first = report_workflow.create_draft(actor=actor)
        report_workflow.save_content(first["id"], form=FORM, items=_items(), actor=actor)
        generated = asyncio.run(report_workflow.generate(first["id"], actor=actor))
        number = generated["report_no"]

        try:
            report_workflow.delete_report(first["id"], actor=actor)
        except ValueError:
            pass
        else:
            raise AssertionError("已生成的报告不应允许直接删除")

        voided = report_workflow.void_report(first["id"], reason="录入有误", actor=actor)
        assert voided["status"] == "void" and voided["report_no"] == number
        assert voided["void_reason"] == "录入有误"
        report_workflow.delete_report(first["id"], actor=actor)
        assert report_workflow.get_report(first["id"]) is None


def test_number_never_reused_after_void() -> None:
    """作废后用掉的那个号不会被下一份报告捡走。"""
    with TempDB():
        actor = _actor()
        first = report_workflow.create_draft(actor=actor)
        report_workflow.save_content(first["id"], form=FORM, items=_items(), actor=actor)
        no1 = asyncio.run(report_workflow.generate(first["id"], actor=actor))["report_no"]
        report_workflow.void_report(first["id"], reason="作废", actor=actor)

        second = report_workflow.create_draft(actor=actor)
        report_workflow.save_content(second["id"], form=FORM, items=_items(), actor=actor)
        no2 = asyncio.run(report_workflow.generate(second["id"], actor=actor))["report_no"]
        assert no1 != no2, f"编号被重复使用：{no1} / {no2}"
        assert no2.endswith("-002"), no2


def test_clone_copies_header_only() -> None:
    """复制为新建：抬头带走，评价结果不带（避免上一次的判定被误用）。"""
    with TempDB():
        actor = _actor()
        source = report_workflow.create_draft(actor=actor)
        report_workflow.save_content(source["id"], form=FORM, items=_items(unfit=2), actor=actor)

        cloned = report_workflow.clone_report(source["id"], actor=actor)
        assert cloned["id"] != source["id"]
        assert cloned["status"] == "draft" and cloned["report_no"] is None
        assert cloned["form"]["clientName"] == "佛山某公司"
        assert cloned["items"] == [], "复制后不应带评价结果"


def test_list_filters_and_pagination() -> None:
    """列表：按状态筛选、按关键字检索、只看自己。"""
    with TempDB():
        actor = _actor()
        for _ in range(2):
            report_workflow.create_draft(actor=actor)
        result = report_workflow.list_reports(status="draft")
        assert result["total"] == 2 and len(result["items"]) == 2
        assert isinstance(result["items"][0]["id"], str)

        result = report_workflow.list_reports(q="不存在的单位")
        assert result["total"] == 0
        result = report_workflow.list_reports(mine=actor["id"])
        assert result["total"] == 2


def test_risk_values_follow_expert_material() -> None:
    """相同风险不因位置改变而变化。"""
    reason = expert_risk.options("1.7")[0]["text"]
    selected = expert_risk.select("1.7", [reason])
    risk = expert_risk.assess("1.7", "unfit", selected)
    assert (risk["severity"], risk["probability"], risk["category"]) == (2, "D", "Ⅱ类")


def test_score_formula_matches_appendix_a() -> None:
    """附录A 公式：Ⅰ类一票否决；Σv<0 记 0；无风险情节记 100。"""
    assert risk_rules.score_of([]) == 100
    assert risk_rules.score_of(["Ⅲ类"]) == 100
    assert risk_rules.score_of(["Ⅱ类"]) == 0, "Σv = -1 < 0 → 0"
    assert risk_rules.score_of(["Ⅰ类", "Ⅲ类"]) == 0, "存在 Ⅰ类 → 一票否决"
    assert risk_rules.score_of(["Ⅲ类", "Ⅱ类"]) == 25, "100 × (2-1) / (2×2) = 25"
    assert risk_rules.grade_of(90) == "一级"
    assert risk_rules.grade_of(75) == "二级"
    assert risk_rules.grade_of(60) == "三级"
    assert risk_rules.grade_of(59.9) == "四级"


def _main() -> int:
    tests = [
        ("草稿整存整取与抬头提升", test_create_save_and_get_draft),
        ("生成分配编号并算等级", test_generate_assigns_number_and_computes_grade),
        ("漏填拒绝生成", test_generate_rejects_incomplete_items),
        ("模型可用则用模型", test_generate_uses_llm_when_available),
        ("模型不可用则降级", test_generate_falls_back_when_llm_fails),
        ("作废保留编号与删除规则", test_void_keeps_number_and_delete_rules),
        ("编号不复用", test_number_never_reused_after_void),
        ("复制只带抬头", test_clone_copies_header_only),
        ("列表筛选与分页", test_list_filters_and_pagination),
        ("风险值来自专家材料", test_risk_values_follow_expert_material),
        ("附录A 公式", test_score_formula_matches_appendix_a),
    ]
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"  [PASS] {name}")
        except AssertionError as e:
            failed += 1
            print(f"  [FAIL] {name}: {e}")
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"  [ERROR] {name}: {type(e).__name__}: {e}")
    print()
    print(f"合计 {len(tests)} 项，通过 {len(tests) - failed}，失败 {failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(_main())
