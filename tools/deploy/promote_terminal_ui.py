"""Promote a hash-verified, already-tested candidate; preserve programs and reports."""
from datetime import datetime
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import sys

from promote_native_export import ROOT, DATABASE, run, report_state, wait_health, gui_processes, restart_gui


def main():
    release = Path(sys.argv[1]).resolve()
    assert release.parent == Path('/userdata/releases') and release.name.startswith('terminal-ui-')
    candidate = release/'candidate'
    manifest = json.loads((candidate/'release-manifest.json').read_text())
    assert (candidate/'output/terminal-ui-acceptance/board-smoke.json').exists(), 'Candidate smoke missing'
    assert (release/'browser-verified.json').exists(), 'Candidate browser check missing'
    assert run('systemctl', 'show', 'elevator-api', '-p', 'WorkingDirectory', '--value') == str(ROOT/'backend')
    for name, digest in manifest['files'].items():
        assert hashlib.sha256((candidate/name).read_bytes()).hexdigest() == digest, name
    assert not (release/'production-result.json').exists(), 'Do not rerun an uncertain release'
    stage = ROOT/('.deploy-'+release.name)
    assert not stage.exists()
    stage.mkdir()
    for name, source in [('next-app', candidate/'backend/app'), ('next-dist', candidate/'web/dist')]:
        shutil.copytree(source, stage/name)
    assert not (ROOT/'backend/app').is_symlink() and not (ROOT/'web/dist').is_symlink()
    result = dict(release=str(release), candidate_sha256=hashlib.sha256((release/'candidate.zip').read_bytes()).hexdigest(),
                  base_commit=manifest['base_commit'], source_state=manifest['source_state'], status='prepared',
                  started_at=datetime.now().isoformat())
    shutil.copy2(ROOT/'backend/.env', release/'backup.env')
    (release/'backup.env').chmod(0o600)
    previous_gui = gui_processes()
    app_moved = dist_moved = False
    try:
        run('systemctl', 'stop', 'elevator-api')
        result['reports_before'] = report_state()
        with sqlite3.connect(str(DATABASE)) as original, sqlite3.connect(str(release/'backup.db')) as backup:
            original.backup(backup)
        (release/'backup.db').chmod(0o600)
        (ROOT/'backend/app').rename(stage/'previous-app')
        app_moved = True
        (stage/'next-app').rename(ROOT/'backend/app')
        (ROOT/'web/dist').rename(stage/'previous-dist')
        dist_moved = True
        (stage/'next-dist').rename(ROOT/'web/dist')
        run('systemctl', 'start', 'elevator-api')
        wait_health()
        result['reports_after'] = report_state()
        assert result['reports_before'] == result['reports_after'], 'Production report rows changed'
        result['gui_restarted'] = restart_gui(previous_gui, release)
        result['status'] = 'deployed'
    except Exception as exc:
        result['error'] = str(exc)
        run('systemctl', 'stop', 'elevator-api')
        # Roll back code only. Never overwrite any business data with an old backup.
        for changed, name, backup in ((app_moved, 'backend/app', 'previous-app'),
                                     (dist_moved, 'web/dist', 'previous-dist')):
            if changed:
                if (ROOT/name).exists():
                    (ROOT/name).rename(stage/('failed-'+backup))
                (stage/backup).rename(ROOT/name)
        run('systemctl', 'start', 'elevator-api')
        wait_health()
        result['status'] = 'rolled_back'
        raise
    finally:
        result['finished_at'] = datetime.now().isoformat()
        result['rollback_programs'] = str(stage)
        (release/'production-result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print(json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
