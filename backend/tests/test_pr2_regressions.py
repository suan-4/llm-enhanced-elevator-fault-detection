"""PR #2 regressions. Uses disposable directories/SQLite; no board or production data."""
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tests._tempdb import TempDB
from app.config import settings
from app.services import export_service, folder_picker, runtime_config, system_service


class ConfigRegressions(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='elevator-pr2-fix-')
        self.root = Path(self.temp.name).resolve()
        self.original = {key: getattr(settings, key) for key in runtime_config.SPEC_BY_KEY}
        self.original_export = export_service.EXPORT_DIR
        settings.export_dir = str(self.root / 'exports')
        settings.backup_dir = str(self.root / 'backups')
        export_service.EXPORT_DIR = Path(settings.export_dir)
        self.database = TempDB()
        self.database.__enter__()

    def tearDown(self):
        self.database.__exit__(None, None, None)
        for key, value in self.original.items():
            setattr(settings, key, value)
        export_service.EXPORT_DIR = self.original_export
        self.temp.cleanup()

    def test_rejects_root_home_and_relative_directories(self):
        for directory in (str(Path(self.root.anchor)), str(Path.home()), '../reports'):
            with self.subTest(directory=directory):
                with self.assertRaises(ValueError):
                    runtime_config.update({'export_dir': directory}, path=self.root / 'config.json')

    def test_rejects_overlapping_export_and_backup(self):
        for values in ({'backup_dir': settings.export_dir},
                       {'backup_dir': str(Path(settings.export_dir) / 'backup')},
                       {'export_dir': str(Path(settings.backup_dir) / 'exports')}):
            with self.subTest(values=values):
                with self.assertRaises(ValueError):
                    runtime_config.update(values, path=self.root / 'config.json')

    def test_unchanged_legacy_paths_do_not_block_other_configuration_changes(self):
        settings.export_dir = 'data/exports'
        settings.backup_dir = 'data/backups'
        result = runtime_config.update({'export_dir': 'data/exports', 'backup_dir': 'data/backups',
                                        'institution_name': 'Updated institution'}, path=self.root / 'config.json')
        self.assertIn('institution_name', result['updated'])
        self.assertEqual(settings.institution_name, 'Updated institution')

    def test_failed_disk_save_does_not_change_live_configuration(self):
        blocked = self.root / 'regular-file'
        blocked.write_text('not a directory', encoding='utf-8')
        before = settings.export_dir
        with self.assertRaises(OSError):
            runtime_config.update({'export_dir': str(self.root / 'new-exports')},
                                  path=blocked / 'config.json')
        self.assertEqual(settings.export_dir, before)
        self.assertEqual(export_service.EXPORT_DIR, Path(before))

    def test_audit_failure_restores_disk_and_live_configuration(self):
        target = self.root / 'config.json'
        before = settings.export_dir
        saved = json.dumps({'export_dir': before}, ensure_ascii=False)
        target.write_text(saved, encoding='utf-8')
        with patch.object(runtime_config.audit_service, 'record', side_effect=RuntimeError('audit failed')):
            with self.assertRaises(RuntimeError):
                runtime_config.update({'export_dir': str(self.root / 'new-exports')}, path=target)
        self.assertEqual(settings.export_dir, before)
        self.assertEqual(export_service.EXPORT_DIR, Path(before))
        self.assertEqual(target.read_text(encoding='utf-8'), saved)

    def test_pruning_preserves_unrelated_and_invalid_backup_folders(self):
        base = self.root / 'backups'
        base.mkdir()
        protected = ['01-user-documents', '02-user-photos', '20200101-000000']
        for name in protected:
            (base / name).mkdir()
            (base / name / 'keep.txt').write_text('keep', encoding='utf-8')
        for name in ('20260101-000000', '20260102-000000'):
            dest = base / name
            dest.mkdir()
            with sqlite3.connect(dest / 'elevator.db') as conn:
                conn.execute('create table sample (id integer)')
            conn.close()
            data = (dest / 'elevator.db').read_bytes()
            (dest / 'manifest.json').write_text(json.dumps({
                'app_version': '1.1.0', 'created_at': '2026-01-01T00:00:00',
                'files': [{'path': 'elevator.db', 'size': len(data),
                           'sha256': hashlib.sha256(data).hexdigest()}]}), encoding='utf-8')
        settings.backup_keep = 1
        system_service._prune_backups(base)
        self.assertTrue(all((base / name / 'keep.txt').is_file() for name in protected))
        self.assertFalse((base / '20260101-000000').exists())
        self.assertTrue((base / '20260102-000000').is_dir())

    def test_existing_export_directory_permissions_are_unchanged(self):
        export_service.EXPORT_DIR.mkdir()
        with patch.object(export_service.os, 'chmod') as chmod:
            with patch.object(export_service.os, 'chown', create=True) as chown:
                export_service.ensure_export_dir()
        chmod.assert_not_called()
        chown.assert_not_called()


class FolderPickerRegressions(unittest.TestCase):
    def test_linux_without_display_does_not_claim_gui_available(self):
        result = folder_picker._linux_plan(which=lambda name: '/usr/bin/' + name,
                                           has_tk=False, display='')
        self.assertFalse(result['available'])

    def test_display_startup_error_is_not_treated_as_cancel(self):
        result = subprocess.CompletedProcess(['zenity'], 1, '', 'Gtk-WARNING: cannot open display')
        with patch.object(folder_picker.subprocess, 'run', return_value=result):
            with self.assertRaises(RuntimeError):
                folder_picker._run(['zenity'])

    def test_user_cancel_remains_non_error(self):
        result = subprocess.CompletedProcess(['zenity'], 1, '', '')
        with patch.object(folder_picker.subprocess, 'run', return_value=result):
            self.assertIsNone(folder_picker._run(['zenity']))


if __name__ == '__main__':
    unittest.main(verbosity=2)
