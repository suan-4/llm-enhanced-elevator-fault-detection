"""系统管理与运维：信息、诊断、备份、恢复。

两条实现上的硬规矩（都吃过亏）：
1. 备份**不能直接拷 elevator.db 文件** —— WAL 模式下还有 -wal/-shm，
   直接拷可能拿到"缺了最近事务"的库。必须用 SQLite 官方在线备份接口。
2. 恢复**不能半途而废** —— 先校验 manifest 里每个文件的 SHA-256，
   再备份现状，最后写临时文件 + 原子替换。
"""
from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
import socket
from datetime import datetime
from pathlib import Path
from typing import Any

from app import db
from app.config import settings
from app.repo import audit_repo, ids as id_gen
from app.repo.base import now_iso
from app.services import audit_service

ITEMS_PATH = Path(__file__).resolve().parent.parent / "data" / "jte_items.json"
MODEL_NAME = "Qwen3.5-4B / RKLLM"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _catalog() -> dict:
    """条目库信息：启动时现算（不建表）。"""
    try:
        raw = ITEMS_PATH.read_bytes()
        items = json.loads(raw.decode("utf-8")).get("items", [])
    except (OSError, ValueError):
        return {"version": "未找到条目库", "count": 0, "hash": "", "ok": False}
    return {
        "version": "JTE-09-R02-3.00",
        "count": len(items),
        "hash": hashlib.sha256(raw).hexdigest()[:12],
        "ok": len(items) == 66,
    }


def _db_size() -> int:
    total = 0
    for suffix in ("", "-wal", "-shm"):
        path = Path(str(db.DB_PATH) + suffix)
        if path.exists():
            total += path.stat().st_size
    return total


def info() -> dict:
    """「关于」页与诊断用。"""
    db_path = Path(db.DB_PATH)
    try:
        free = shutil.disk_usage(db_path.parent).free
    except OSError:
        free = -1
    with db.get_conn() as conn:
        tables = [
            r["name"]
            for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        ]
    return {
        "version": settings.app_version,
        "model": MODEL_NAME,
        "catalog": _catalog(),
        "db": {"path": str(db_path), "size": _db_size(), "schema_version": db.user_version(),
               "tables": tables},
        "export_dir": str(settings.export_dir),
        "backup_dir": settings.backup_dir,
        "disk_free": free,
        "worker_id": settings.worker_id,
        "clock_rollbacks": id_gen.rollback_events(),
    }


def _check_neo4j() -> dict:
    """先探端口再验连接。

    顺序很重要：neo4j 驱动自己的连接超时是几十秒，直接调 verify_connectivity()
    在"服务没起来"时会把诊断卡成半分钟 —— 诊断必须秒出结果。
    """
    from urllib.parse import urlparse

    parsed = urlparse(settings.neo4j_uri)
    host, port = parsed.hostname or "127.0.0.1", parsed.port or 7687
    try:
        with socket.create_connection((host, port), timeout=1.5):
            pass
    except OSError:
        return {"status": "fail", "detail": f"图谱服务未启动（{host}:{port} 连不上）",
                "advice": "检查 Neo4j 服务是否已启动（systemctl status neo4j）"}
    try:
        from app.services.kg_service import kg_service

        kg_service.driver.verify_connectivity()
        return {"status": "ok", "detail": "图谱可连接"}
    except Exception as e:  # noqa: BLE001
        return {"status": "fail", "detail": f"端口通但连接失败（{type(e).__name__}）",
                "advice": "检查 Neo4j 账号口令与数据库是否就绪"}


def _check_rkllm() -> dict:
    """只做 TCP 连通性探测：不去触发一次真实推理，免得诊断自己把模型占住。"""
    from urllib.parse import urlparse

    parsed = urlparse(settings.rkllm_server_url)
    host, port = parsed.hostname or "127.0.0.1", parsed.port or 8080
    try:
        with socket.create_connection((host, port), timeout=1.5):
            return {"status": "ok", "detail": f"{host}:{port} 可连接"}
    except OSError:
        return {"status": "warn", "detail": f"{host}:{port} 连不上",
                "advice": "模型不可用时报告仍可生成，叙述文字降级为规则摘要"}


def _check_export_dir() -> dict:
    path = Path(settings.export_dir)
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".write-probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        return {"status": "ok", "detail": f"{path} 可写"}
    except OSError as e:
        return {"status": "fail", "detail": f"{path} 不可写（{e.strerror or e}）",
                "advice": "检查目录是否存在、权限是否正确（板端应为 user 可写）"}


def _check_disk() -> dict:
    try:
        free = shutil.disk_usage(Path(db.DB_PATH).parent).free
    except OSError:
        return {"status": "warn", "detail": "无法读取磁盘空间"}
    mb = free // (1024 * 1024)
    if mb < 200:
        return {"status": "fail", "detail": f"剩余 {mb} MB",
                "advice": "清理导出目录或历史备份后重试"}
    if mb < 1024:
        return {"status": "warn", "detail": f"剩余 {mb} MB，偏少",
                "advice": "建议清理导出目录"}
    return {"status": "ok", "detail": f"剩余 {mb} MB"}


def _check_clock() -> dict:
    """这台板子 RTC 不可信，所以时间这项要单独查。"""
    now = datetime.now()
    with db.get_conn() as conn:
        row = conn.execute("SELECT MAX(updated_at) AS m FROM report").fetchone()
    latest = row["m"] if row else None
    if now.year < 2026:
        return {"status": "warn", "detail": f"当前系统时间 {now:%Y-%m-%d %H:%M} 明显偏早",
                "advice": "板端 RTC 不可信，请在系统设置里手工校时"}
    if latest and latest[:19] > now.isoformat(timespec="seconds"):
        return {"status": "warn", "detail": f"系统时间早于最后一条业务记录（{latest}）",
                "advice": "时间回退会让报告时间不可信，请校时"}
    return {"status": "ok", "detail": f"系统时间 {now:%Y-%m-%d %H:%M}"}


def _check_db() -> dict:
    try:
        with db.get_conn() as conn:
            result = conn.execute("PRAGMA quick_check").fetchone()[0]
            bad = conn.execute("PRAGMA foreign_key_check").fetchall()
        if result != "ok":
            return {"status": "fail", "detail": f"quick_check：{result}",
                    "advice": "用最近一次备份恢复"}
        if bad:
            return {"status": "warn", "detail": f"外键校验 {len(bad)} 条异常"}
        return {"status": "ok", "detail": "完整性与外键校验通过"}
    except Exception as e:  # noqa: BLE001
        return {"status": "fail", "detail": f"{type(e).__name__}"}


def _check_catalog() -> dict:
    catalog = _catalog()
    if not catalog["ok"]:
        return {"status": "fail", "detail": f"条目库异常（{catalog['count']} 条）",
                "advice": "在仓库根目录执行 tools/gen_jte_items.py 重新生成"}
    return {"status": "ok", "detail": f"{catalog['count']} 条，哈希 {catalog['hash']}"}


def _check_soffice() -> dict:
    found = shutil.which("soffice") or shutil.which("libreoffice")
    if found:
        return {"status": "ok", "detail": found}
    return {"status": "fail", "detail": "未找到 LibreOffice",
            "advice": "没有它无法导出 PDF/Word（板端应预装）"}


def diagnose() -> dict:
    """一次把该查的都查了。status: ok / warn / fail。"""
    checks = [
        {"name": "业务库", **_check_db()},
        {"name": "条目库", **_check_catalog()},
        {"name": "知识图谱", **_check_neo4j()},
        {"name": "大模型服务", **_check_rkllm()},
        {"name": "导出目录", **_check_export_dir()},
        {"name": "文档转换", **_check_soffice()},
        {"name": "磁盘空间", **_check_disk()},
        {"name": "系统时间", **_check_clock()},
    ]
    if id_gen.rollback_events():
        checks.append({
            "name": "ID 生成", "status": "warn",
            "detail": f"检测到 {id_gen.rollback_events()} 次时钟回拨",
            "advice": "已自动按上次时间戳继续，ID 不会重复；建议校时",
        })
    else:
        checks.append({"name": "ID 生成", "status": "ok", "detail": "未检测到时钟回拨"})
    worst = "ok"
    for check in checks:
        if check["status"] == "fail":
            worst = "fail"
            break
        if check["status"] == "warn":
            worst = "warn"
    return {"overall": worst, "checks": checks, "at": now_iso()}


# ── 备份 / 恢复 ─────────────────────────────────────────
def backup(target_dir: str | None = None, *, actor: dict | None = None) -> dict:
    base = Path(target_dir) if target_dir else Path(settings.backup_dir)
    dest = base / datetime.now().strftime("%Y%m%d-%H%M%S")
    dest.mkdir(parents=True, exist_ok=True)

    # ① 业务库：在线备份接口（WAL 下直接拷文件会丢事务）
    db_target = dest / "elevator.db"
    src = sqlite3.connect(str(db.DB_PATH))
    dst = sqlite3.connect(str(db_target))
    try:
        with dst:
            src.backup(dst)
    finally:
        dst.close()
        src.close()

    # ② 导出目录（存在才拷；没有也不算失败）
    export_src = Path(settings.export_dir)
    files = [db_target]
    if export_src.is_dir():
        export_dst = dest / "export"
        shutil.copytree(export_src, export_dst, dirs_exist_ok=True)
        files.extend(p for p in export_dst.rglob("*") if p.is_file())

    # ③ 清单：每个文件带 SHA-256，恢复前据此校验
    manifest = {
        "created_at": now_iso(),
        "app_version": settings.app_version,
        "files": [{"path": str(p.relative_to(dest)), "size": p.stat().st_size,
                   "sha256": _sha256(p)} for p in files],
    }
    (dest / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    _prune_backups(base)
    size = sum(f["size"] for f in manifest["files"])
    with db.get_conn() as conn:
        audit_service.record(conn, "backup_create", actor=actor, target=str(dest),
                             note=f"{len(manifest['files'])} 个文件，{size} 字节")
    return {"dir": str(dest), "files": len(manifest["files"]), "size": size,
            "manifest": manifest}


def _prune_backups(base: Path) -> None:
    """只保留最近 N 份（按目录名排序，名字就是时间戳）。"""
    if not base.is_dir():
        return
    dirs = sorted((d for d in base.iterdir() if d.is_dir()), key=lambda d: d.name)
    for old in dirs[: max(0, len(dirs) - settings.backup_keep)]:
        shutil.rmtree(old, ignore_errors=True)


def verify_backup(source_dir: str) -> dict:
    """恢复前的校验：manifest 里每个文件的 SHA-256 都要对上。"""
    src = Path(source_dir)
    manifest_path = src / "manifest.json"
    if not manifest_path.is_file():
        raise ValueError("这个目录不是一份备份（缺少 manifest.json）")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for entry in manifest.get("files", []):
        target = src / entry["path"]
        if not target.is_file():
            raise ValueError(f"备份不完整：缺少 {entry['path']}")
        if _sha256(target) != entry["sha256"]:
            raise ValueError(f"备份已损坏：{entry['path']} 校验不通过")
    return manifest


def list_backups() -> list[dict]:
    """列出可恢复的备份（按时间倒序）。只认带 manifest.json 的目录。"""
    base = Path(settings.backup_dir)
    if not base.is_dir():
        return []
    out = []
    for entry in sorted(base.iterdir(), reverse=True):
        manifest_path = entry / "manifest.json"
        if not entry.is_dir() or not manifest_path.is_file():
            continue
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        out.append({
            "dir": str(entry),
            "name": entry.name,
            "created_at": manifest.get("created_at", ""),
            "files": len(manifest.get("files", [])),
            "size": sum(f.get("size", 0) for f in manifest.get("files", [])),
        })
    return out


def restore(source_dir: str, *, actor: dict | None = None) -> dict:
    """恢复：校验 → 备份现状 → 原子替换 → 完整性校验。"""
    src = Path(source_dir)
    verify_backup(source_dir)

    # 恢复前先把现状备一份，避免"恢复错了回不去"。
    # 配置的备份目录万一写不了（比如路径没准备好），退回临时目录 ——
    # 恢复是"救命"操作，不能因为备份目录不可用就彻底做不了。
    try:
        pre = backup(str(Path(settings.backup_dir) / "pre-restore"), actor=actor)
    except OSError:
        pre = backup(str(Path(tempfile.gettempdir()) / "elevator-pre-restore"), actor=actor)
        pre["fallback"] = True

    incoming = src / "elevator.db"
    if not incoming.is_file():
        raise ValueError("备份里没有业务库文件")
    tmp = Path(str(db.DB_PATH) + ".restore-tmp")
    shutil.copy2(incoming, tmp)

    # 先做完整性校验再替换：宁可恢复失败，也不要换上一个坏库
    probe = sqlite3.connect(str(tmp))
    try:
        if probe.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise ValueError("备份里的业务库校验不通过，已中止恢复")
    finally:
        probe.close()

    for suffix in ("-wal", "-shm"):
        leftover = Path(str(db.DB_PATH) + suffix)
        if leftover.exists():
            leftover.unlink()
    tmp.replace(db.DB_PATH)

    with db.get_conn() as conn:
        audit_service.record(conn, "backup_restore", actor=actor, target=str(src))
    return {"pre_backup": pre["dir"], "restart_required": True}


def audit_events(*, from_: str | None = None, to: str | None = None,
                 event: str | None = None, actor: str | None = None,
                 page: int = 1, size: int = 50) -> dict:
    with db.get_conn() as conn:
        rows, total = audit_repo.list_(conn, from_=from_, to=to, event=event,
                                       actor=actor, page=page, size=size)
    return {"total": total, "page": page, "size": size, "items": rows}
import tempfile
