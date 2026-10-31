#!/usr/bin/env python3
"""在没有 pytest 的环境里运行 kg-prompt 测试函数。"""
from __future__ import annotations
import importlib.util
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
TEST = ROOT / "backend" / "tests" / "test_kg_prompt.py"


def main() -> int:
    spec = importlib.util.spec_from_file_location("test_kg_prompt", TEST)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    failed = 0
    for name in sorted(dir(module)):
        if name.startswith("test_") and callable(getattr(module, name)):
            try:
                getattr(module, name)()
                print("PASS", name)
            except Exception:
                failed += 1
                print("FAIL", name)
                traceback.print_exc()
    print("RESULT", "PASS" if failed == 0 else f"FAIL {failed}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
