"""Promote the verified native-export package on EM-R16, with program rollback.

Run as root on the board only. Production reports are never used as test input;
the post-release workflow uses a private disposable SQLite database.
"""
from pathlib import Path
from zipfile import ZipFile
from datetime import datetime
import asyncio
import hashlib
import json
import os
import pwd
import shutil
import signal
import sqlite3
import subprocess
import sys
import time
import urllib.request
from uuid import uuid4

ROOT = Path('/home/ubuntu/elevator')
CANDIDATE = Path('/userdata/releases/20261020-native-export-01/candidate-final.zip')
PACKAGE_SHA = 'a498bad3e61120e8346caaa9ad8d74f0dace063a1ffd91d65cd4287adeb4d14b'
OFFLINE = Path('/userdata/releases/20261018-prompt-guard-01')
DATABASE = Path('/userdata/elevator/elevator.db')
DROPIN = Path('/etc/systemd/system/elevator-api.service.d/60-native-export-runtime.conf')


def run(*args):
    return subprocess.run(args, check=True, capture_output=True, text=True, timeout=45).stdout.strip()


def report_state():
    with sqlite3.connect('file:'+str(DATABASE)+'?mode=ro', uri=True) as conn:
        conn.row_factory = sqlite3.Row
        rows = [dict(row) for row in conn.execute('SELECT * FROM report ORDER BY id')]
    return {'count': len(rows), 'sha256': hashlib.sha256(json.dumps(
        rows, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()}


def wait_health():
    for _ in range(30):
        try:
            with urllib.request.urlopen('http://127.0.0.1:8081/api/health', timeout=2) as response:
                if response.status == 200:
                    return
        except OSError:
            time.sleep(.5)
    raise RuntimeError('Formal API health check did not recover')


def gui_processes():
    result = []
    for proc in Path('/proc').iterdir():
        if not proc.name.isdigit():
            continue
        try:
            args = [v.decode() for v in (proc/'cmdline').read_bytes().split(b'\0') if v]
            if '/home/user/elevator_app.py' not in args:
                continue
            env = dict(v.decode().split('=', 1) for v in (proc/'environ').read_bytes().split(b'\0') if b'=' in v)
            result.append((int(proc.name), args, env, proc.stat().st_uid))
        except (OSError, UnicodeError):
            continue
    return result


def restart_gui(previous, release):
    if not previous:
        return False
    # Restart only the exact native app seen before deployment.
    for pid, args, env, uid in previous:
        try:
            current = Path('/proc')/str(pid)/'cmdline'
            if current.exists() and b'/home/user/elevator_app.py\0' in current.read_bytes():
                os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    time.sleep(1)
    if gui_processes():
        return False
    _, args, env, uid = previous[0]
    user = pwd.getpwuid(uid)
    with (release/'desktop.log').open('ab') as output:
        subprocess.Popen(args, env=env, cwd=user.pw_dir, user=uid, group=user.pw_gid,
                         extra_groups=os.getgrouplist(user.pw_name, user.pw_gid),
                         start_new_session=True, stdout=output, stderr=output)
    return True


def smoke(release):
    # Match the newly installed production interpreter, configuration and assets.
    # db.DB_PATH is redirected before schema/account/report operations.
    os.chdir(ROOT/'backend')
    sys.path.insert(0, str(ROOT/'backend'))
    sys.path.insert(0, str(release/'runtime'))
    from app import db
    from app.config import settings
    from app.repo import ids
    from app.services import auth_service, report_workflow as wf, report_export, export_service
    from app.services.prompt_budget import configured_budget
    settings.rkllm_tokenizer_path = str(release/'tokenizer/tokenizer.json')
    settings.rkllm_calibration_path = str(release/'tokenizer/calibration.json')
    settings.recovery_key_path = str(release/'smoke/recovery.key')
    db.DB_PATH = release/'smoke/test.db'
    export_service.EXPORT_DIR = release/'smoke/exports'
    db.init_db()
    ids.configure(31, db.max_business_id())
    budget = configured_budget().check('部署验收：电梯安全评估')
    actor, _ = auth_service.init_system(display_name='发布验收', username='release_smoke', password=uuid4().hex)
    report = wf.create_draft(actor=actor)
    items = json.loads(wf.ITEMS_PATH.read_text())['items']
    wf.save_content(report['id'], actor=actor,
                    form=dict(clientName='发布隔离验收', userName='发布隔离验收',
                              deviceCategory='曳引驱动电梯', productNo='RELEASE-SMOKE',
                              instruments='/', basis='/'),
                    items=[dict(no=i['no'], result='fit', reasons=[], other_text='') for i in items])
    generated = asyncio.run(wf.generate(report['id'], use_llm=True, actor=actor))
    if generated['provenance']['llm_used'] is not True:
        raise RuntimeError('Model smoke failed: '+generated['provenance'].get('llm_error', ''))
    files = [report_export.export_report(report_id=report['id'], version=generated['version'],
              result_digest=generated['provenance']['result_digest'], fmt=fmt, actor=actor)
             for fmt in ['docx', 'pdf']]
    assert wf.get_report(report['id'])['status'] == 'filed'
    return {'llm_used': True, 'score': generated['score'], 'grade': generated['grade'],
            'input_tokens': budget['input_tokens'],
            'exports': [{k: f[k] for k in ('fmt', 'size', 'sha256', 'performance')} for f in files]}


def main():
    assert os.name == 'posix' and os.geteuid() == 0
    assert ROOT.resolve() == ROOT and (ROOT/'backend/app').is_dir()
    assert run('systemctl', 'show', 'elevator-api', '-p', 'WorkingDirectory', '--value') == str(ROOT/'backend')
    assert hashlib.sha256(CANDIDATE.read_bytes()).hexdigest() == PACKAGE_SHA
    assert not DROPIN.exists(), 'Unexpected existing deployment drop-in; inspect before replacing'
    key = datetime.now().strftime('%Y%m%d-%H%M%S')+'-'+uuid4().hex[:6]
    release = Path('/userdata/releases')/('native-export-'+key)
    release.mkdir(mode=0o700)
    stage = ROOT/('.deploy-'+key)
    stage.mkdir()
    previous_gui = gui_processes()
    manifest = {'source_commit': 'f176359', 'package_sha256': PACKAGE_SHA,
                'release': str(release), 'stage': str(stage), 'status': 'prepared'}
    (release/'manifest.json').write_text(json.dumps(manifest, indent=2))
    # Preserve everything needed for program/config rollback before changing service.
    shutil.copytree(ROOT/'backend/app', release/'backup-app')
    shutil.copytree(ROOT/'web/dist', release/'backup-dist')
    shutil.copy2(ROOT/'backend/.env', release/'backup.env')
    os.chmod(release/'backup.env', 0o600)
    (release/'api-unit.txt').write_text(run('systemctl', 'cat', 'elevator-api'))
    shutil.copytree(OFFLINE/'runtime', release/'runtime')
    shutil.copytree(OFFLINE/'backend/data/tokenizers/qwen3.5-4b', release/'tokenizer')
    print('program/config backup and offline assets ready: '+str(release), flush=True)
    with ZipFile(CANDIDATE) as package:
        for name in package.namelist():
            if not name.startswith(('backend/app/', 'web/dist/')):
                continue
            destination = (stage/name).resolve()
            assert stage in destination.parents
            package.extract(name, stage)
            assert hashlib.sha256(destination.read_bytes()).digest() == hashlib.sha256(package.read(name)).digest()
    run('python3', '-m', 'compileall', '-q', str(stage/'backend/app'))
    old_app, old_dist = stage/'previous-app', stage/'previous-dist'
    changed_app = changed_dist = False
    try:
        run('systemctl', 'stop', 'elevator-api')
        manifest['reports_before'] = report_state()
        with sqlite3.connect(str(DATABASE)) as source, sqlite3.connect(str(release/'backup.db')) as target:
            source.backup(target)
        assert not (ROOT/'backend/app').is_symlink() and not (ROOT/'web/dist').is_symlink()
        (ROOT/'backend/app').rename(old_app)
        changed_app = True
        (stage/'backend/app').rename(ROOT/'backend/app')
        (ROOT/'web/dist').rename(old_dist)
        changed_dist = True
        (stage/'web/dist').rename(ROOT/'web/dist')
        DROPIN.parent.mkdir(exist_ok=True)
        DROPIN.write_text('[Service]\n'
            f'Environment="PYTHONPATH={release}/runtime"\n'
            f'Environment="RKLLM_TOKENIZER_PATH={release}/tokenizer/tokenizer.json"\n'
            f'Environment="RKLLM_CALIBRATION_PATH={release}/tokenizer/calibration.json"\n')
        run('systemctl', 'daemon-reload')
        run('systemctl', 'start', 'elevator-api')
        wait_health()
        print('formal API started; running isolated model and export smoke', flush=True)
        manifest['smoke'] = smoke(release)
        manifest['reports_after'] = report_state()
        assert manifest['reports_before'] == manifest['reports_after'], 'Production reports changed during release'
        manifest['gui_restarted'] = restart_gui(previous_gui, release)
        manifest['status'] = 'deployed'
    except Exception as exc:
        manifest['error'] = str(exc)
        run('systemctl', 'stop', 'elevator-api')
        # Keep failed files for diagnosis. Restore programs only, never overwrite reports.
        if changed_app:
            if (ROOT/'backend/app').exists(): (ROOT/'backend/app').rename(stage/'failed-app')
            old_app.rename(ROOT/'backend/app')
        if changed_dist:
            if (ROOT/'web/dist').exists(): (ROOT/'web/dist').rename(stage/'failed-dist')
            old_dist.rename(ROOT/'web/dist')
        DROPIN.unlink(missing_ok=True)
        run('systemctl', 'daemon-reload')
        run('systemctl', 'start', 'elevator-api')
        wait_health()
        manifest['status'] = 'rolled_back'
        print(json.dumps(manifest, ensure_ascii=False), flush=True)
        raise
    finally:
        (release/'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
    print(json.dumps(manifest, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
