"""Validate operator-selected storage paths without touching their permissions."""
import os
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2]
PROJECT = BACKEND.parent


def storage_directory(value: str) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        raise ValueError('请选择绝对路径，并使用专用的导出或备份文件夹')
    path = path.resolve()
    roots = {Path(path.anchor), Path.home().resolve(), Path.home().resolve().parent}
    if os.name != 'nt':
        roots.update(Path(p) for p in ('/home', '/userdata', '/tmp', '/var', '/opt', '/mnt', '/media', '/srv'))
        if path.parent == Path('/home'):
            roots.add(path)
        system = [Path(p) for p in ('/etc', '/usr', '/bin', '/sbin', '/lib', '/lib64',
                                   '/proc', '/sys', '/dev', '/run', '/boot')]
    else:
        system = [Path(os.environ[key]).resolve() for key in
                  ('SystemRoot', 'ProgramFiles', 'ProgramFiles(x86)', 'ProgramData')
                  if os.environ.get(key)]
    code = [BACKEND / 'app', PROJECT / '.git', PROJECT / 'web' / 'src',
            PROJECT / 'web' / 'node_modules', PROJECT / 'native', PROJECT / 'kiosk']
    if path in roots or any(path == p or p in path.parents for p in system):
        raise ValueError('不能使用系统目录或用户根目录，请选择专用子文件夹')
    if any(path == p.resolve() or p.resolve() in path.parents or path in p.resolve().parents for p in code):
        raise ValueError('不能使用应用程序目录，请选择专用的导出或备份文件夹')
    if path.exists() and not path.is_dir():
        raise ValueError('所选路径不是文件夹')
    return path


def separate_storage(export_dir: Path, backup_dir: Path) -> None:
    export_dir, backup_dir = export_dir.resolve(), backup_dir.resolve()
    if (export_dir == backup_dir or export_dir in backup_dir.parents
            or backup_dir in export_dir.parents):
        raise ValueError('导出目录与备份目录不能相同或相互包含')
