"""Package exactly app/dist plus isolated QA helpers; never include data or .env."""
import hashlib
import json
from pathlib import Path
import subprocess
from zipfile import ZIP_DEFLATED, ZipFile

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT/'output/terminal-ui-acceptance'
OUT.mkdir(parents=True, exist_ok=True)
paths = []
for base in (ROOT/'backend/app', ROOT/'web/dist'):
    paths.extend(p for p in base.rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.suffix != '.pyc')
paths.extend(ROOT/name for name in ('tools/acceptance/terminal_board_smoke.py',
             'tools/acceptance/terminal_ui_server.py', 'tools/deploy/promote_native_export.py',
             'tools/deploy/promote_terminal_ui.py'))
inventory = {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
tracked = subprocess.check_output(['git', 'status', '--porcelain', '--', 'backend', 'web/src', 'tools'], cwd=ROOT, text=True)
if tracked.strip():
    raise SystemExit('Commit verified application and deployment source before packaging')
manifest = {'base_commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
            'source_state': 'committed release source', 'files': inventory}
target = OUT/'terminal-ui-candidate.zip'
with ZipFile(target, 'w', ZIP_DEFLATED) as package:
    for path in paths:
        package.write(path, path.relative_to(ROOT).as_posix())
    package.writestr('release-manifest.json', json.dumps(manifest, ensure_ascii=False, indent=2))
print(json.dumps({'package': str(target), 'sha256': hashlib.sha256(target.read_bytes()).hexdigest(),
                  'base_commit': manifest['base_commit'], 'files': len(paths)}))
