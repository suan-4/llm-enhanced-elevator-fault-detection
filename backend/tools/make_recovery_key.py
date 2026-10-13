"""生成板端「恢复口令」文件（界面「忘记口令」用它）。

用法（板端，root）：

    cd /home/ubuntu/elevator/backend
    python3 tools/make_recovery_key.py            # 生成并打印（已存在则拒绝，不覆盖）
    python3 tools/make_recovery_key.py --show     # 只看当前值
    python3 tools/make_recovery_key.py --force    # 重新生成（旧口令立即作废）

生成后请**把它抄进交付单/设备台账**：这个口令丢了，就只能走
tools/reset_password.py 那条命令行路径了。
文件权限设为 600，只有 root 能读。
"""
from __future__ import annotations

import argparse
import os
import secrets
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from app.config import settings  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="生成/查看恢复口令文件")
    parser.add_argument("--path", default=settings.recovery_key_path,
                        help="恢复口令文件路径（默认取配置）")
    parser.add_argument("--show", action="store_true", help="只显示当前口令")
    parser.add_argument("--force", action="store_true", help="已存在时重新生成")
    args = parser.parse_args(argv)

    target = Path(args.path)
    if args.show:
        if not target.is_file():
            print(f"尚未配置恢复口令（{target} 不存在）")
            return 1
        print(target.read_text(encoding="utf-8").strip())
        return 0

    if target.exists() and not args.force:
        print(f"已存在：{target}")
        print("没有覆盖 —— 已有口令可能已经抄进交付单了。要换请加 --force。")
        return 1

    key = secrets.token_urlsafe(24)
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(key + "\n", encoding="utf-8")
        if os.name != "nt":
            os.chmod(target, 0o600)
    except OSError as e:
        print(f"写入失败：{e}")
        return 1

    print("已生成恢复口令文件：")
    print(f"  路径：{target}")
    print(f"  口令：{key}")
    print("请把它抄进交付单/设备台账；登录页的「忘记口令」就是用它。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
