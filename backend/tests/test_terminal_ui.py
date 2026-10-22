"""UI contract changes: new-only defaults, required variety and cover source slots."""
import asyncio
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tests._tempdb import TempDB
from tests.test_report_workflow import FORM, _actor, _items
from app.services import report_workflow as wf
from app.models.schemas import ItemAnswer


class TerminalUIContractTests(unittest.TestCase):
    def setUp(self):
        self.tempdb = TempDB()
        self.tempdb.__enter__()
        self.actor = _actor()

    def tearDown(self):
        self.tempdb.__exit__()

    def test_new_defaults_are_persisted_but_legacy_drafts_are_not_rewritten(self):
        new = wf.create_draft(actor=self.actor)
        self.assertEqual(len(new['items']), 66)
        self.assertTrue(all(i['result'] == 'fit' for i in new['items']))
        self.assertEqual(wf.get_report(new['id'])['items'], new['items'])
        wf.save_content(new['id'], form={}, items=[{'no': '1.7', 'result': '', 'reasons': [], 'other_text': ''}])
        self.assertEqual(wf.get_report(new['id'])['items'][0]['result'], '')

    def test_variety_is_required_and_category_is_not(self):
        new = wf.create_draft(actor=self.actor)
        form = {**FORM, 'deviceCategory': '/', 'deviceVariety': '曳引驱动乘客电梯'}
        wf.save_content(new['id'], form=form, items=_items())
        self.assertEqual(asyncio.run(wf.generate(new['id']))['status'], 'generated')
        wf.save_content(new['id'], form={**form, 'deviceVariety': '/'}, items=_items())
        with self.assertRaisesRegex(ValueError, '设备品种未填写'):
            asyncio.run(wf.generate(new['id']))

    def test_inactive_editing_state_survives_api_serialization_without_assessment(self):
        new = wf.create_draft(actor=self.actor)
        answer = ItemAnswer(no='1.7', result='fit', reasons=[], other_text='',
                            editing={'reasons': ['保留选项'], 'other': True, 'other_text': '未启用文字'})
        wf.save_content(new['id'], form={}, items=[answer.model_dump()])
        stored = wf.get_report(new['id'])['items'][0]
        self.assertEqual(stored['editing']['other_text'], '未启用文字')
        self.assertEqual(stored['reasons'], [])
        self.assertEqual(stored['other_text'], '')


if __name__ == '__main__':
    unittest.main()
