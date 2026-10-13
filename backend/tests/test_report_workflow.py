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
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tests._tempdb import TempDB  # noqa: E402

from app.services import auth_service, report_workflow, risk_rules  # noqa: E402

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
    items = []
    for i in range(total):
        if i < unfit:
            items.append({"no": f"1.{i + 1}", "result": "unfit",
                          "reasons": ["箱体出现裂纹"], "other_text": ""})
        else:
            items.append({"no": f"1.{i + 1}", "result": "fit", "reasons": [], "other_text": ""})
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
        assert [i["no"] for i in draft["items"]] == ["1.1", "1.2", "1.3"]
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
        # 第 1 条不符合 → 占位规则给 Ⅰ类 → 一票否决 → G=0 → 四级
        report_workflow.save_content(
            report["id"], form=FORM, items=_items(unfit=1), actor=actor
        )
        generated = report_workflow.generate(report["id"], actor=actor)

        assert generated["status"] == "generated"
        assert generated["report_no"].startswith("GDSEI-JTE-")
        assert generated["report_no"].endswith("-001"), generated["report_no"]
        assert generated["generated_at"]
        assert generated["score"] == 0 and generated["grade"] == "四级"
        assert "1.1" in generated["risks"], generated["risks"]
        assert generated["risks"]["1.1"]["category"] == "Ⅰ类"
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
            report_workflow.generate(report["id"], actor=actor)
        except ValueError as e:
            assert "未填" in str(e)
        else:
            raise AssertionError("有未填项时不应允许生成")


def test_void_keeps_number_and_delete_rules() -> None:
    """作废保留编号；已作废可删，已生成不可删。"""
    with TempDB():
        actor = _actor()
        first = report_workflow.create_draft(actor=actor)
        report_workflow.save_content(first["id"], form=FORM, items=_items(), actor=actor)
        generated = report_workflow.generate(first["id"], actor=actor)
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
        no1 = report_workflow.generate(first["id"], actor=actor)["report_no"]
        report_workflow.void_report(first["id"], reason="作废", actor=actor)

        second = report_workflow.create_draft(actor=actor)
        report_workflow.save_content(second["id"], form=FORM, items=_items(), actor=actor)
        no2 = report_workflow.generate(second["id"], actor=actor)["report_no"]
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


def test_risk_placeholder_matches_frontend_cycle() -> None:
    """占位规则的前几项要与前端原来的演示值一致（避免两侧算法打架）。"""
    assert risk_rules.assign(0) == {"severity": 4, "probability": "B", "category": "Ⅰ类",
                                    "source": "rule"}
    assert risk_rules.assign(1)["category"] == "Ⅱ类"
    assert risk_rules.assign(2)["category"] == "Ⅱ类"
    assert risk_rules.assign(3)["category"] == "Ⅱ类"
    assert risk_rules.assign(4)["category"] == "Ⅰ类", "每 4 项循环一次"


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
        ("作废保留编号与删除规则", test_void_keeps_number_and_delete_rules),
        ("编号不复用", test_number_never_reused_after_void),
        ("复制只带抬头", test_clone_copies_header_only),
        ("列表筛选与分页", test_list_filters_and_pagination),
        ("风险占位与前端一致", test_risk_placeholder_matches_frontend_cycle),
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
