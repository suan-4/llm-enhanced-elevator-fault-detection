"""Run every standalone backend test script, preserving full output for review."""
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'output/terminal-ui-acceptance'
OUT.mkdir(parents=True, exist_ok=True)
results = []
for script in sorted((ROOT / 'backend/tests').glob('test_*.py')):
    result = subprocess.run([sys.executable, str(script)], cwd=ROOT, capture_output=True,
                            text=True, encoding='utf-8', errors='replace', timeout=120)
    (OUT / (script.stem + '.log')).write_text(result.stdout + result.stderr, encoding='utf-8')
    results.append({'test': script.name, 'exit_code': result.returncode})
    print(script.name, 'PASS' if result.returncode == 0 else 'FAIL', flush=True)
    if result.returncode:
        print((result.stdout + result.stderr)[-4500:], flush=True)
(OUT / 'backend-suite.json').write_text(json.dumps(results, indent=2), encoding='utf-8')
raise SystemExit(any(r['exit_code'] for r in results))
