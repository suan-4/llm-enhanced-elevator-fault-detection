"""Trusted report snapshot -> native DOCX/PDF -> recoverable file registration."""
import hashlib
from contextlib import contextmanager
import json
import logging
import os
import re
from pathlib import Path
import shutil
import subprocess
import tempfile
from time import perf_counter
from uuid import uuid4

from app import db
from app.repo import report_repo
from app.repo.base import now_iso
from app.services import audit_service, export_service, native_template
from app.services.report_snapshot import result_digest
from app.services.report_workflow import VersionConflict, _input_digest, OVERVIEW_POLICY

log = logging.getLogger(__name__)


@contextmanager
def work_lock(work):
    """Cross-process advisory lock; nonblocking so recovery never waits on LO."""
    stream = (work / "active.lock").open("a+b")
    acquired = False
    try:
        if os.name == "nt":
            import msvcrt
            if stream.seek(0, 2) == 0:
                stream.write(b"0")
                stream.flush()
            stream.seek(0)
            try:
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                acquired = True
            except OSError:
                pass
        else:
            import fcntl
            try:
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
            except BlockingIOError:
                pass
        yield acquired
    finally:
        if acquired:
            if os.name == "nt":
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
        stream.close()


def validate(report, version, digest):
    if report is None:
        raise LookupError("报告不存在")
    p = report.get("provenance") or {}
    if report["status"] not in ("generated", "filed"):
        raise VersionConflict("仅已生成或已归档的有效报告可以导出")
    if report["version"] != version or result_digest(report) != digest:
        raise VersionConflict("报告内容或生成结果已变化，请重新打开预览后导出")
    if (not report.get("report_no") or not report.get("generated_at")
            or p.get("assessment_complete") is not True or p.get("assessment_issues")
            or p.get("input_digest") != _input_digest(report)
            or p.get("overview_policy") != OVERVIEW_POLICY
            or report.get("score") is None or not report.get("grade")
            or not report.get("narrative") or len(report.get("items", [])) != 66):
        raise VersionConflict("这份报告缺少完整可信快照，请复制为新建后重新评估；原报告未修改")


def _sync_directory(directory):
    if os.name != "nt":
        fd = os.open(str(directory), os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


def _write_sync(path, data):
    with path.open("xb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())


def convert_pdf(source, work):
    outdir = work / "pdf"
    outdir.mkdir()
    cmd = [export_service.SOFFICE, "--headless", "--norestore", "--nolockcheck",
           "--nodefault", "-env:UserInstallation=" + (work / "profile").as_uri(),
           "--convert-to", "pdf:writer_pdf_Export", "--outdir", str(outdir), str(source)]
    try:
        proc = subprocess.run(cmd, capture_output=True, timeout=export_service.CONVERT_TIMEOUT)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("PDF转换超时，请重试；本次未归档") from exc
    except OSError as exc:
        raise RuntimeError("无法启动LibreOffice，Word仍可导出；请检查PDF转换组件") from exc
    target = outdir / (source.stem + ".pdf")
    if proc.returncode or not target.exists() or not target.read_bytes().startswith(b"%PDF-"):
        log.error("PDF converter failed: %r", proc.stderr[-1000:])
        raise RuntimeError("LibreOffice未生成有效PDF，本次未归档")
    return target


def export_report(*, report_id, version, result_digest: str, fmt, filename="", actor=None):
    started = perf_counter()
    rid = int(report_id)
    with db.get_conn() as conn:
        report = report_repo.find_by_id(conn, rid)
    validate(report, version, result_digest)
    if fmt not in ("docx", "pdf"):
        raise ValueError("只支持Word和PDF")
    export_service.ensure_export_dir()
    directory = Path(export_service.EXPORT_DIR).resolve()
    pending = directory / ".pending"
    pending.mkdir(exist_ok=True)
    token = uuid4().hex
    # Staging on the export filesystem makes publishing a complete file atomic.
    work = Path(tempfile.mkdtemp(prefix=token + "-", dir=pending))
    lock = work_lock(work)
    if not lock.__enter__():
        raise RuntimeError("无法锁定导出暂存目录")
    marker = pending / (token + ".json")
    published = None
    committed = False
    try:
        _write_sync(work / "owner.json", json.dumps({"db": str(db.DB_PATH.resolve())}).encode())
        _sync_directory(work)
        build_started = perf_counter()
        source = work / "report.docx"
        _write_sync(source, native_template.build_docx(report))
        build_ms = (perf_counter() - build_started) * 1000
        convert_started = perf_counter()
        output = source if fmt == "docx" else convert_pdf(source, work)
        if fmt == "pdf":
            with output.open("rb") as stream:
                os.fsync(stream.fileno())
        convert_ms = (perf_counter() - convert_started) * 1000
        digest = hashlib.sha256(output.read_bytes()).hexdigest()
        stamp = now_iso()
        default_name = f"{report['report_no']}_{report.get('user_name') or '电梯安全评估报告'}_{stamp[:10].replace('-', '')}"
        stem = export_service._safe_stem(filename or default_name)
        with db.get_conn() as conn:
            current = report_repo.lock_for_update(conn, rid)
            validate(current, version, result_digest)
            # Name choice, journal, publication and registration share the same
            # short write lock. Conversion never holds a database write lock.
            index = 0
            while True:
                suffix = f"_{index}" if index else ""
                final = directory / f"{stem}{suffix}.{fmt}"
                if not final.exists():
                    break
                index += 1
            journal = {"report_id": str(rid), "path": str(final), "sha256": digest,
                       "db": str(db.DB_PATH.resolve()), "work": work.name,
                       "device": output.stat().st_dev, "inode": output.stat().st_ino}
            _write_sync(marker, json.dumps(journal, ensure_ascii=False).encode())
            _sync_directory(pending)
            # Never replace any existing file, even one created outside this app.
            os.link(output, final)
            published = final
            try:
                if hasattr(os, "chown"):
                    os.chown(final, export_service.EXPORT_UID, export_service.EXPORT_GID)
                os.chmod(final, 0o644)
            except OSError:
                pass
            _sync_directory(directory)
            info = {"fmt": fmt, "filename": final.name, "path": str(final),
                    "size": final.stat().st_size, "sha256": digest, "at": stamp,
                    "version": version, "result_digest": result_digest}
            report_repo.mark_exported(conn, rid, exported_at=stamp,
                                      files=[*(current.get("files") or []), info])
            audit_service.record(conn, "report_export", actor=actor,
                                 target=report["report_no"], after=info)
        committed = True
        try:
            marker.unlink()
        except OSError:
            log.warning("Export committed; pending marker left for recovery")
        return {"success": True, **info, "dir": str(directory),
                "report_id": str(rid), "report_no": report["report_no"],
                "status": "filed", "exported_at": stamp,
                "performance": {"docx_build_ms": round(build_ms, 3),
                                "convert_ms": round(convert_ms, 3),
                                "export_total_ms": round((perf_counter()-started)*1000, 3)}}
    except Exception:
        if not committed:
            if published is not None:
                published.unlink(missing_ok=True)
            marker.unlink(missing_ok=True)
        raise
    finally:
        lock.__exit__(None, None, None)
        shutil.rmtree(work, ignore_errors=True)


def recover_pending():
    """Startup: reconcile only this database's journaled files under EXPORT_DIR.

    A marker is written only under the SQLite write lock. A recovering worker
    must take the same lock before deciding whether publication committed.
    Unknown/unrelated files are never removed.
    """
    directory = Path(export_service.EXPORT_DIR).resolve()
    pending = directory / ".pending"
    if not pending.is_dir():
        return
    for marker in pending.glob("*.json"):
        try:
            with db.get_conn() as conn:
                conn.execute("BEGIN IMMEDIATE")
                if not marker.exists():
                    continue
                data = json.loads(marker.read_text(encoding="utf-8"))
                if data.get("db") != str(db.DB_PATH.resolve()):
                    continue
                target = Path(data["path"])
                if target.parent != directory or target.is_symlink():
                    continue
                report = report_repo.find_by_id(conn, int(data["report_id"]))
                registered = any(f.get("path") == str(target) and f.get("sha256") == data["sha256"]
                                 for f in (report or {}).get("files", []))
                if target.exists() and not registered:
                    stat = target.stat()
                    if ((stat.st_dev, stat.st_ino) != (data.get("device"), data.get("inode"))
                            or hashlib.sha256(target.read_bytes()).hexdigest() != data["sha256"]):
                        continue
                    target.unlink()
                marker.unlink()
        except Exception:
            log.exception("Pending export recovery failed; marker retained")
    for work in pending.iterdir():
        if (not work.is_dir() or work.is_symlink()
                or not re.fullmatch(r"[0-9a-f]{32}-[A-Za-z0-9_-]+", work.name)):
            continue
        try:
            remove = False
            with work_lock(work) as acquired:
                if not acquired:
                    continue
                owner = work / "owner.json"
                if owner.exists():
                    remove = json.loads(owner.read_text()).get("db") == str(db.DB_PATH.resolve())
                # A crash before writing owner.json can leave only the empty lock.
                # Never claim an unknown directory containing actual data.
                else:
                    remove = {p.name for p in work.iterdir()} == {"active.lock"}
            if remove:
                shutil.rmtree(work)
        except Exception:
            log.exception("Interrupted export staging retained after cleanup error")
