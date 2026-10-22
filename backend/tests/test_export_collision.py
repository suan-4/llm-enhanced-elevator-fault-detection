"""Repeated same-name exports must preserve every previously published file."""
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.services import export_service as svc


class ExportCollisionTests(unittest.TestCase):
    def test_three_exports_in_same_second_keep_distinct_bytes(self):
        counter = 0

        def convert(cmd, **kwargs):
            nonlocal counter
            counter += 1
            output = Path(cmd[cmd.index("--outdir") + 1]) / "report.pdf"
            output.write_bytes(f"report-{counter}".encode())
            return SimpleNamespace(stdout=b"", stderr=b"", returncode=0)

        with tempfile.TemporaryDirectory() as tmp, \
                patch.object(svc, "EXPORT_DIR", Path(tmp)), \
                patch.object(svc.subprocess, "run", convert), \
                patch.object(svc, "datetime") as clock:
            clock.now.return_value = datetime(2026, 10, 20, 12, 0, 0)
            outputs = [svc.export("<p>fixture</p>", "pdf", "report") for _ in range(3)]
            self.assertEqual(len({o["path"] for o in outputs}), 3)
            self.assertEqual([Path(o["path"]).read_bytes() for o in outputs],
                             [b"report-1", b"report-2", b"report-3"])


if __name__ == "__main__":
    unittest.main()
