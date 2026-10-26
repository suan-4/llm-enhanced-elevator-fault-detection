"""Idempotent native focus-bridge update. Back up the exact known launcher first."""
from pathlib import Path
import os
import shutil
import sys


def install(launcher, backup):
    launcher, backup = Path(launcher), Path(backup)
    original = launcher.read_text(encoding='utf-8')
    marker = 'if (window.__elevatorInputManaged) { return false; }'
    if marker in original:
        return False
    needle = '  function isText(t) {\n'
    if original.count(needle) != 1:
        raise ValueError('原生键盘焦点桥与预期不同，未修改启动器')
    source = original.replace(needle, needle + '    ' + marker + '\n')
    compile(source, str(launcher), 'exec')
    if backup.exists():
        raise ValueError('已有原生启动器备份，请先核对')
    shutil.copy2(launcher, backup)
    info = launcher.stat()
    target = launcher.with_name(launcher.name + '.next-keyboard')
    target.write_text(source, encoding='utf-8')
    os.chmod(target, info.st_mode & 0o777)
    if hasattr(os, 'chown'):
        os.chown(target, info.st_uid, info.st_gid)
    os.replace(target, launcher)
    return True


if __name__ == '__main__':
    assert os.geteuid() == 0
    backup = Path(sys.argv[1]).resolve()
    assert backup.parent.parent == Path('/userdata/releases')
    print('native_bridge_updated', install('/home/user/elevator_app.py', backup))
