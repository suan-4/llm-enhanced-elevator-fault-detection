"""Expert material integration: options, risk aggregation and grounded model input."""
from __future__ import annotations

import asyncio
import json
import sys
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch
from xml.etree import ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tests._tempdb import TempDB
from app.api.report import list_jte_items
from app.services import auth_service, report_workflow as wf
from app.services import expert_risk
from app.services.llm_service import llm_service

ROOT = Path(__file__).resolve().parents[2]
W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
FORM = {"clientName": "测试委托单位", "userName": "测试使用单位", "deviceCategory": "曳引驱动电梯", "productNo": "TEST-001"}


def source_risk(row: int) -> tuple[str, str]:
    with zipfile.ZipFile(ROOT / "docs/规范与模板/总表-安全评估项目汇总-v1.docx") as archive:
        body = ET.fromstring(archive.read("word/document.xml")).find(W + "body")
    cells = body.find(W + "tbl").findall(W + "tr")[row - 1].findall(W + "tc")
    value = lambda cell: "".join(t.text or "" for t in cell.iter(W + "t"))
    return value(cells[3]), value(cells[5])


def answers(selected: dict[str, list[str]] | None = None, other: dict[str, str] | None = None) -> list[dict]:
    selected, other = selected or {}, other or {}
    catalog = json.loads((ROOT / "backend/app/data/jte_items.json").read_text(encoding="utf-8"))["items"]
    return [{"no": item["no"], "result": "unfit" if item["no"] in selected or item["no"] in other else "fit",
             "reasons": selected.get(item["no"], []), "other_text": other.get(item["no"], "")} for item in catalog]


class ExpertRiskTests(unittest.TestCase):
    def test_overview_prompt_contains_each_grounded_fact_only_once(self):
        selected=expert_risk.options('1.7')[:2]
        risks={'1.7':expert_risk.assess('1.7','unfit',selected)}
        items=[{'no':'1.7','reasons':[r['text'] for r in selected],'other_text':'现场补充原文'}]
        prompt=wf._narrative_prompt({'form':FORM,'counters':{}},items,risks,97.73,'一级')
        data=json.loads(prompt)['data']
        for entry in selected:
            self.assertEqual(prompt.count(entry['measure']),1)
            self.assertIn('risk:'+entry['key'],data['overview_facts'])
        self.assertIn('现场补充原文',prompt)
        self.assertNotIn('委托单位名称',data)

    def test_overview_failure_has_machine_readable_degraded_status(self):
        rid=self.prepare(answers())
        from app.services.prompt_budget import ModelInputError
        async def blocked(prompt):
            raise ModelInputError('context_budget_exceeded','超过输入预算')
        with patch.object(llm_service,'generate',blocked):
            report=asyncio.run(wf.generate(rid,use_llm=True,actor=self.actor))
        self.assertEqual(report['provenance']['llm_status'],'degraded')
        self.assertEqual(report['provenance']['llm_error_code'],'context_budget_exceeded')
        self.assertFalse(report['provenance']['llm_used'])
        self.assertEqual(report['score'],100)

    def test_free_text_budget_failure_explains_reason_and_preserves_draft(self):
        rid=self.prepare(answers(other={'16.1':'需要解析的现场原文'}))
        from app.services.prompt_budget import ModelInputError
        async def blocked(prompt):
            raise ModelInputError('context_budget_exceeded','模型输入超过预算；未截断原始资料')
        with patch.object(llm_service,'generate',blocked):
            with self.assertRaisesRegex(ValueError,'超过预算'):
                asyncio.run(wf.generate(rid,use_llm=True,actor=self.actor))
        report=wf.get_report(rid)
        self.assertEqual(report['status'],'draft')
        self.assertIsNone(report['report_no'])
        self.assertEqual(next(i for i in report['items'] if i['no']=='16.1')['other_text'],'需要解析的现场原文')

    def setUp(self):
        self.temp = TempDB()
        self.temp.__enter__()
        self.addCleanup(self.temp.__exit__, None, None, None)
        self.actor, _ = auth_service.init_system(display_name="检验员", username="expert-test", password="expert-test-2026")

    def prepare(self, items: list[dict]) -> str:
        report = wf.create_draft(actor=self.actor)
        wf.save_content(report["id"], form=FORM, items=items, actor=self.actor)
        return report["id"]

    def test_options_are_actual_risks_not_positive_requirements(self):
        payload = asyncio.run(list_jte_items(user=self.actor))
        by_no = {i["no"]: i for i in payload["items"]}
        self.assertEqual(len(by_no["1.7"]["opts"]), 4)
        self.assertIn("控制柜前水平净空面积", by_no["1.7"]["opts"][0])
        self.assertIn("不符合", by_no["1.7"]["opts"][0])
        self.assertEqual(len(by_no["16.1"]["opts"]), 32)
        self.assertFalse(any("检查结果符合要求" in opt for i in by_no.values() for opt in i["opts"]))
        self.assertEqual(sum(len(i["opts"]) for i in by_no.values()), 445)

    def test_category_comes_from_selected_risk_not_position(self):
        text, measure = source_risk(2)
        rid = self.prepare(answers({"1.7": [text]}))
        report = asyncio.run(wf.generate(rid, actor=self.actor))
        risk = report["risks"]["1.7"]
        self.assertEqual(risk["category"], "Ⅱ类")
        self.assertEqual((risk["severity"], risk["probability"]), (2, "D"))
        self.assertEqual(risk["selected_risks"][0]["measure"], measure)
        self.assertEqual(report["risks"]["1.9"]["category"], "Ⅲ类")

    def test_multiple_risks_take_worst_without_dropping_measures(self):
        first, measure1 = source_risk(279)
        second, measure2 = source_risk(310)
        rid = self.prepare(answers({"16.1": [second, first, second]}))
        report = asyncio.run(wf.generate(rid, actor=self.actor))
        risk = report["risks"]["16.1"]
        self.assertEqual(risk["category"], "Ⅰ类")
        self.assertEqual(len(risk["selected_risks"]), 2)
        self.assertEqual({r["measure"] for r in risk["selected_risks"]}, {measure1, measure2})

    def test_overview_shows_only_project_final_category_for_each_risk(self):
        risks = {"16.1": {"category": "Ⅰ类", "selected_risks": [
            {"key": "16.1:01", "text": "风险甲", "category": "I", "measure": "措施甲"},
            {"key": "16.1:32", "text": "风险乙", "category": "II", "measure": "措施乙"},
        ]}}
        facts = wf._overview_facts([{"no": "16.1"}], risks, 0, "四级")
        self.assertIn("风险类别：Ⅰ类", facts["risk:16.1:32"])
        self.assertNotIn("风险类别：Ⅱ类", facts["risk:16.1:32"])
        self.assertIn("措施乙", facts["risk:16.1:32"])

    def test_confirmed_differences_follow_evaluation_unfit_reference(self):
        for no, row, severity, probability, category, original, score in (
            ("12.1", 166, 1, "C", "Ⅰ类", "II", 0),
            ("16.1", 310, 2, "B", "Ⅰ类", "II", 0),
            ("16.6", 324, 2, "D", "Ⅱ类", "I", 97.73),
        ):
            with self.subTest(no=no):
                text, measure = source_risk(row)
                rid = self.prepare(answers({no: [text]}))
                report = asyncio.run(wf.generate(rid, actor=self.actor))
                risk = report["risks"][no]
                self.assertEqual((risk["severity"], risk["probability"], risk["category"]), (severity, probability, category))
                self.assertEqual(risk["selected_risks"][0]["measure"], measure)
                override = risk["selected_risks"][0]["category_override"]
                self.assertEqual(override["original_category"], original)
                self.assertEqual(override["source"], risk["reference_source"])
                self.assertEqual(report["provenance"]["assessment_issues"], [])
                self.assertEqual(report["status"], "generated")
                self.assertTrue(report["report_no"])
                self.assertEqual(report["score"], score)

    def test_unknown_old_choice_is_not_silently_scored(self):
        rid = self.prepare(answers({"1.7": ["旧版含糊选项"]}))
        with self.assertRaisesRegex(ValueError, "1.7"):
            asyncio.run(wf.generate(rid, actor=self.actor))
        report = wf.get_report(rid)
        self.assertIsNone(report["report_no"])
        self.assertEqual(report["status"], "draft")

    def test_model_receives_both_selected_risks_and_original_free_text(self):
        text, measure = source_risk(279)
        rid = self.prepare(answers({"16.1": [text]}, {"16.1": "控制柜散热通道堵塞"}))
        narrative_data = []

        async def model(prompt: str):
            data = json.loads(prompt)["data"]
            if data.get("task") == "match_risk":
                return json.dumps({"risk_keys": ["16.1:32"], "unmatched": False})
            narrative_data.append(data)
            return "根据已记录的风险和对应措施进行整改。"

        with patch.object(llm_service, "generate", model):
            report = asyncio.run(wf.generate(rid, use_llm=True, actor=self.actor))
        self.assertEqual(len(report["risks"]["16.1"]["selected_risks"]), 2)
        self.assertEqual(len(narrative_data), 1)
        material = json.dumps(narrative_data[0], ensure_ascii=False)
        self.assertIn("控制柜散热通道堵塞", material)
        self.assertIn(measure, material)
        self.assertTrue(report["provenance"]["other_matches"])

    def test_model_unknown_risk_key_cannot_assign_a_category(self):
        rid = self.prepare(answers(other={"16.1": "无法在清单中确认的问题"}))

        async def model(prompt: str):
            return '{"risk_keys":["invented"],"unmatched":false,"category":"III"}'

        with patch.object(llm_service, "generate", model):
            with self.assertRaisesRegex(ValueError, "16.1"):
                asyncio.run(wf.generate(rid, use_llm=True, actor=self.actor))
        self.assertIsNone(wf.get_report(rid)["report_no"])

    def test_edited_input_during_model_call_is_not_overwritten(self):
        text, _ = source_risk(2)
        rid = self.prepare(answers({"1.7": [text]}))

        async def model(prompt: str):
            wf.save_content(rid, form={**FORM, "productNo": "EDITED"}, items=answers(), actor=self.actor)
            return "旧输入的说明"

        with patch.object(llm_service, "generate", model):
            with self.assertRaises(wf.VersionConflict):
                asyncio.run(wf.generate(rid, use_llm=True, actor=self.actor))
        current = wf.get_report(rid)
        self.assertEqual(current["form"]["productNo"], "EDITED")
        self.assertIsNone(current["report_no"])

    def test_pending_score_is_a_draft_without_a_formal_number(self):
        rid = self.prepare(answers())
        with patch.dict(expert_risk.knowledge(), {"score_basis": "pending"}):
            report = asyncio.run(wf.generate(rid, actor=self.actor))
        self.assertIsNone(report["score"])
        self.assertIsNone(report["grade"])
        self.assertIsNone(report["report_no"])
        self.assertEqual(report["status"], "draft")
        self.assertFalse(report["provenance"]["assessment_complete"])

    def test_applicable_scoring_counts_fit_once_and_excludes_na(self):
        first, _ = source_risk(2)
        second, _ = source_risk(3)
        items = answers({"1.7": [first, second]})
        next(i for i in items if i["no"] == "1.9")["result"] = "na"
        rid = self.prepare(items)
        report = asyncio.run(wf.generate(rid, actor=self.actor))
        self.assertEqual(len(report["risks"]), 65)
        self.assertNotIn("1.9", report["risks"])
        self.assertEqual(report["score"], 97.69)  # 100*(64*2-1)/(65*2)
        self.assertEqual(report["grade"], "一级")
        self.assertEqual(report["status"], "generated")
        self.assertEqual(len(report["risks"]["1.7"]["selected_risks"]), 2)

    def test_all_na_has_no_score_or_formal_report_number(self):
        items = answers()
        for item in items:
            item["result"] = "na"
        report = asyncio.run(wf.generate(self.prepare(items), actor=self.actor))
        self.assertIsNone(report["score"])
        self.assertIsNone(report["grade"])
        self.assertIsNone(report["report_no"])
        self.assertEqual(report["status"], "draft")
        self.assertTrue(any("所有项目均为无此项" in issue for issue in report["provenance"]["assessment_issues"]))
        self.assertNotIn("计分口径待确认", report["narrative"])

    def test_missing_model_content_is_a_recoverable_validation_error(self):
        rid = self.prepare(answers(other={"16.1": "需要匹配的描述"}))

        async def model(prompt: str):
            return None

        with patch.object(llm_service, "generate", model):
            with self.assertRaisesRegex(ValueError, "16.1"):
                asyncio.run(wf.generate(rid, use_llm=True, actor=self.actor))
        saved = next(i for i in wf.get_report(rid)["items"] if i["no"] == "16.1")
        self.assertEqual(saved["other_text"], "需要匹配的描述")

    def test_pending_rules_cannot_be_hidden_by_model_claiming_full_score(self):
        rid = self.prepare(answers())

        async def model(prompt: str):
            return "综合安全状况得分100，综合安全状况等级一级。"

        with patch.dict(expert_risk.knowledge(), {"score_basis": "pending"}), patch.object(llm_service, "generate", model):
            report = asyncio.run(wf.generate(rid, use_llm=True, actor=self.actor))
        self.assertFalse(report["provenance"]["llm_used"])
        self.assertIn("待确认", report["narrative"])

    def test_same_risk_text_with_different_measures_remains_independent(self):
        entries = expert_risk.options("6.6")
        third, fourth = entries[2:4]
        self.assertNotEqual(third["text"], fourth["text"])
        self.assertEqual(expert_risk.select("6.6", [third["text"]])[0]["key"], "6.6:03")
        self.assertEqual(expert_risk.select("6.6", [fourth["text"]])[0]["key"], "6.6:04")
        with self.assertRaises(ValueError):
            expert_risk.select("6.6", [third["raw_text"]])

    def test_free_model_prose_cannot_override_grounded_facts(self):
        rid = self.prepare(answers({"1.7": [source_risk(2)[0]]}))
        for unsafe in ("综合安全状况评分为100分，安全等级1级。", "项目1.7为III类风险，无需整改。"):
            async def model(prompt: str):
                return unsafe
            with self.subTest(unsafe=unsafe), patch.object(llm_service, "generate", model):
                report = asyncio.run(wf.generate(rid, use_llm=True, actor=self.actor))
                self.assertFalse(report["provenance"]["llm_used"])
                self.assertNotIn(unsafe, report["narrative"])

    def test_model_can_select_only_known_overview_facts(self):
        rid = self.prepare(answers({"1.7": [source_risk(2)[0]]}))
        async def model(prompt: str):
            data = json.loads(prompt)["data"]
            self.assertIn("finding", data["overview_facts"])
            return '{"overview_keys":["finding","score","risk:1.7:01"]}'
        with patch.object(llm_service, "generate", model):
            report = asyncio.run(wf.generate(rid, use_llm=True, actor=self.actor))
        self.assertTrue(report["provenance"]["llm_used"])
        self.assertIn(source_risk(2)[1], report["narrative"])

    def test_draft_preview_is_current_until_inputs_change(self):
        rid = self.prepare(answers())
        with patch.dict(expert_risk.knowledge(), {"score_basis": "pending"}):
            report = asyncio.run(wf.generate(rid, actor=self.actor))
        self.assertTrue(report["provenance"].get("result_current"))
        wf.save_content(rid, form=FORM, items=answers(), actor=self.actor)
        self.assertTrue(wf.get_report(rid)["provenance"].get("result_current"))
        wf.save_content(rid, form={**FORM, "productNo": "CHANGED"}, items=answers(), actor=self.actor)
        self.assertFalse(wf.get_report(rid)["provenance"].get("result_current"))

    def test_unchanged_formal_report_is_not_downgraded_when_saved(self):
        rid = self.prepare(answers())
        with patch.dict(expert_risk.knowledge(), {"score_basis": "applicable_items"}):
            report = asyncio.run(wf.generate(rid, actor=self.actor))
        saved = wf.save_content(rid, form=FORM, items=answers(), version=report["version"], actor=self.actor)
        self.assertEqual(saved["status"], "generated")
        self.assertEqual(saved["version"], report["version"])


if __name__ == "__main__":
    unittest.main()
