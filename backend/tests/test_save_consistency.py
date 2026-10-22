"""Draft version checks must protect real SQLite writes, including parallel clients."""
import sys
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tests._tempdb import TempDB
from app.services import auth_service, report_workflow as wf


class SaveConsistencyTests(unittest.TestCase):
    def setUp(self):
        self.temp = TempDB()
        self.temp.__enter__()
        self.addCleanup(self.temp.__exit__, None, None, None)
        self.actor, _ = auth_service.init_system(
            display_name="验收", username="savecheck", password="SaveCheck2026")
        self.report = wf.create_draft(actor=self.actor)

    def save(self, name, version):
        return wf.save_content(self.report["id"], form={"clientName": name},
                               items=[], version=version, actor=self.actor)

    def test_stale_draft_cannot_overwrite_new_input(self):
        version = self.report["version"]
        saved = self.save("已保存的新内容", version)
        self.assertEqual(saved["version"], version + 1)
        with self.assertRaises(wf.VersionConflict):
            self.save("旧页面的内容", version)
        self.assertEqual(wf.get_report(self.report["id"])["form"]["clientName"], "已保存的新内容")

    def test_identical_save_keeps_version(self):
        saved = self.save("相同内容", self.report["version"])
        again = self.save("相同内容", saved["version"])
        self.assertEqual(again["version"], saved["version"])

    def test_parallel_same_version_has_exactly_one_winner(self):
        start = threading.Barrier(2)

        def submit(name):
            start.wait(timeout=5)
            try:
                self.save(name, self.report["version"])
                return name
            except wf.VersionConflict:
                return None

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(submit, ["甲页", "乙页"]))
        winners = [name for name in results if name is not None]
        self.assertEqual(len(winners), 1, results)
        self.assertEqual(wf.get_report(self.report["id"])["form"]["clientName"], winners[0])


if __name__ == "__main__":
    unittest.main()
