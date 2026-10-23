"""Disposable localhost UI acceptance server; never uses the production database."""
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / 'output' / 'terminal-ui-acceptance'
DATA.mkdir(parents=True, exist_ok=True)
os.environ.update(SQLITE_PATH=str(DATA / 'test.db'),
                  RECOVERY_KEY_PATH=str(DATA / 'recovery.key'),
                  EXPORT_DIR=str(DATA / 'exports'),
                  BACKUP_DIR=str(DATA / 'backup'))
sys.path.insert(0, str(ROOT / 'backend'))
from app import db
from app.services import auth_service

db.init_db()
if not auth_service.setup_status()['initialized']:
    auth_service.init_system(display_name='界面验收', username='acceptance', password='Acceptance2026!')

if __name__ == '__main__':
    import uvicorn
    uvicorn.run('app.main:app', host='127.0.0.1', port=8087)
