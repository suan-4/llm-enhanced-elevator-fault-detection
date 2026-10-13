"""命令行重置口令（进不去系统时的最后出口）。

用法（板端，root）：

    cd /home/ubuntu/elevator/backend
    python3 tools/reset_password.py <用户名>                 # 交互输入两次
    python3 tools/reset_password.py <用户名> --password '新口令' --yes

为什么需要它：界面的「忘记口令」依赖板端恢复口令文件
（/userdata/elevator/recovery.key）。那个文件没生成、丢了、或者交付时没人记下来，
这条命令行路径就是唯一还能把系统救回来的方式 —— 所以它必须存在且可靠。

它直接改库（不走接口）：正因为"连登录都进不去"，才需要它。
重置后会：踢掉该账号所有会话 + 写一条审计（actor 标"命令行"）。
"""
from __future__ import annotations

import argparse
import getpass
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from app import db  # noqa: E402
from app.repo import account_repo, session_repo  # noqa: E402
from app.services import audit_service, auth_service  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="重置某个账号的登录口令")
    parser.add_argument("username", help="登录用户名")
    parser.add_argument("--password", default=None, help="新口令（不填则交互输入）")
    parser.add_argument("--db", default=None, help="数据库路径（默认取配置）")
    parser.add_argument("--yes", action="store_true", help="不反问确认")
    args = parser.parse_args(argv)

    if args.db:
        db.DB_PATH = Path(args.db)
    if not Path(db.DB_PATH).exists():
        print(f"数据库不存在：{db.DB_PATH}")
        return 1

    username = args.username.strip()
    with db.get_conn() as conn:
        account = account_repo.find_by_username(conn, username)
    if account is None:
        print(f"账号不存在：{username}")
        return 1

    password = args.password
    if not password:
        password = getpass.getpass("新口令：")
        again = getpass.getpass("再输一次：")
        if password != again:
            print("两次输入不一致。")
            return 1

    try:
        auth_service.check_password_policy(username, password)
    except ValueError as e:
        print(f"口令不符合要求：{e}")
        return 1

    if not args.yes:
        print(f"即将重置「{account['display_name']}（{username}）」的口令，"
              f"该账号所有登录会话会立即失效。")
        if input("确认请输入 yes：").strip().lower() != "yes":
            print("已取消。")
            return 1

    salt, digest = auth_service.hash_password(password)
    with db.get_conn() as conn:
        account_repo.update(conn, account["id"], password_salt=salt, password_hash=digest,
                            must_change_password=0)
        killed = session_repo.delete_by_account(conn, account["id"])
        audit_service.record(conn, "password_reset", actor_name="命令行",
                             target=username, note=f"命令行重置，踢下线 {killed} 个会话")

    print(f"已重置「{account['display_name']}（{username}）」的口令，"
          f"并踢下线 {killed} 个会话。")
    print("请登录后让本人改成只有自己知道的口令。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
