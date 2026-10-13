"""每日备份（由 elevator-backup.timer 调用）。

复用系统服务里的备份实现：SQLite 在线快照 + 导出目录 + manifest（逐文件 SHA-256），
并按 backup_keep 只保留最近若干份。
"""
from __future__ import annotations

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from app.services import system_service  # noqa: E402


def main() -> int:
    try:
        result = system_service.backup()
    except OSError as e:
        print(f"备份失败（目录不可用）：{e}")
        return 1
    print(f"备份完成：{result['dir']}")
    print(f"  文件 {result['files']} 个，共 {result['size']} 字节")
    for entry in system_service.list_backups()[:5]:
        print(f"  现有备份：{entry['name']}（{entry['files']} 个文件）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
