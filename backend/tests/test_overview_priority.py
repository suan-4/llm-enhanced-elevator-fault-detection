"""Priority coverage is deterministic, independent of the model's choices."""
import asyncio
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.services import expert_risk, report_workflow as wf
from app.services.llm_service import llm_service
from tests._tempdb import TempDB
from tests.test_expert_risk import answers, FORM
from app.services import auth_service


class OverviewPriorityTests(unittest.TestCase):
    def setUp(self):
        self.temp = TempDB()
        self.temp.__enter__()
        self.addCleanup(self.temp.__exit__, None, None, None)
        self.actor, _ = auth_service.init_system(display_name='测试检验员', username='priority-test', password='PriorityTest2026')
        self.high = expert_risk.options('16.1')[31]
        self.lower = expert_risk.options('16.6')[12]
        draft = wf.create_draft(actor=self.actor)
        self.rid = draft['id']
        wf.save_content(self.rid, form=FORM,
            items=answers({'16.1':[self.high['text']], '16.6':[self.lower['text']]}), actor=self.actor)

    def test_model_selecting_only_lower_risk_cannot_omit_highest_risk(self):
        async def model(prompt):
            return '{"overview_keys":["finding","score","risk:16.6:13"]}'
        with patch.object(llm_service, 'generate', model):
            report = asyncio.run(wf.generate(self.rid, use_llm=True, actor=self.actor))
        text = report['narrative']
        self.assertIn(self.high['text'], text)
        self.assertIn(self.high['measure'], text)
        self.assertLess(text.index(self.high['text']), text.index(self.lower['text']))
        self.assertEqual(text.count(self.high['text']), 1)
        self.assertEqual((report['score'], report['grade']), (0, '四级'))
        self.assertTrue(report['provenance']['llm_used'])
        self.assertEqual(report['provenance']['overview_required_keys'], ['risk:16.1:32'])
        self.assertEqual(report['risks']['16.1']['selected_risks'], [self.high])

    def test_rule_only_overview_keeps_highest_risk_without_runtime_messages(self):
        report = asyncio.run(wf.generate(self.rid, use_llm=False, actor=self.actor))
        self.assertIn(self.high['text'], report['narrative'])
        self.assertIn(self.high['measure'], report['narrative'])
        self.assertNotIn('未使用大模型', report['narrative'])
        self.assertFalse(report['provenance']['llm_used'])
        self.assertEqual(report['provenance']['overview_policy'], 'highest-risk-first-v1')

    def test_invalid_model_still_has_safe_priority_rule_overview(self):
        async def model(prompt): return 'not JSON'
        with patch.object(llm_service, 'generate', model):
            report = asyncio.run(wf.generate(self.rid, use_llm=True, actor=self.actor))
        self.assertIn(self.high['text'], report['narrative'])
        self.assertFalse(report['provenance']['llm_used'])
        self.assertEqual(report['provenance']['llm_error_code'], 'model_response_invalid')

    def test_more_than_three_highest_risks_are_not_silently_truncated(self):
        selected = [dict(key=f'16.1:{i:02}', text=f'风险{i}', measure=f'措施{i}') for i in range(1,7)]
        unfit = [{'no':'16.1'}]
        risks = {'16.1':{'category':'Ⅰ类','selected_risks':selected}}
        facts = wf._overview_facts(unfit, risks, 0, '四级')
        required = wf._priority_fact_keys(unfit, risks)
        text = wf._grounded_overview('{"overview_keys":["finding","score"]}', facts, required)
        self.assertEqual(len(required), 6)
        self.assertTrue(all(text.count(r['text']) == 1 and r['measure'] in text for r in selected))

    def test_priority_uses_final_project_category_and_falls_back_to_class_two(self):
        risks = {'a':{'category':'Ⅲ类','selected_risks':[{'key':'a:1'}]},
                 'b':{'category':'Ⅱ类','selected_risks':[{'key':'b:1','category':'III'}, {'key':'b:2','category':'II'}]}}
        self.assertEqual(wf._priority_fact_keys([{'no':'a'}, {'no':'b'}], risks), ['risk:b:1','risk:b:2'])
        self.assertEqual(wf._priority_fact_keys([], {}), [])

    def test_priority_completion_does_not_accept_unknown_or_duplicate_model_keys(self):
        facts = {'finding':'发现风险','score':'得分0','risk:16.1:32':'已核实风险'}
        for keys in (['finding','score','invented'], ['finding','score','score'], ['score']):
            with self.subTest(keys=keys), self.assertRaises(ValueError):
                wf._grounded_overview(json.dumps({'overview_keys':keys}), facts, ['risk:16.1:32'])


if __name__ == '__main__': unittest.main()
