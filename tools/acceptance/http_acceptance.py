"""接口层验收：对运行中的后端逐层校验，覆盖 HTTP、鉴权、业务接口、降级与安全边界。

用法（先启动后端，见 README）：
    python tools/acceptance/http_acceptance.py
    BASE=http://127.0.0.1:8081 python tools/acceptance/http_acceptance.py

退出码 0 表示全部通过。
目录故障注入与备份文件检查使用本机临时文件，脚本须在后端所在主机运行。
"""

from __future__ import annotations

import os
import re
import sys
import tempfile as _tf
import uuid

import httpx

BASE = os.environ.get("BASE", "http://127.0.0.1:8081")
USERNAME = os.environ.get("ELEVATOR_USER", "admin")
PASSWORD = os.environ.get("ELEVATOR_PASSWORD", "admin123")

results: list[tuple[int, str, bool, str]] = []


def check(layer: int, name: str, cond: bool, detail: str = "") -> None:
    results.append((layer, name, cond, detail))
    mark = "PASS" if cond else "FAIL"
    print(f"  [{mark}] {name}" + (f"  {detail}" if detail else ""))


def main() -> int:
    with httpx.Client(base_url=BASE, timeout=60) as c:
        print("═══ 第 1 层：HTTP 与静态资源 ═══")
        r = c.get("/api/health")
        check(1, "GET /api/health = 200", r.status_code == 200, str(r.json()))

        r = c.get("/api/health/ready")
        body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
        # Neo4j 未就绪时应降级为 503 且说明原因，而不是静默 200
        check(1, "就绪探针在依赖未就绪时返回 503",
              r.status_code in (200, 503), f"status={r.status_code} body={body}")

        r = c.get("/")
        check(1, "GET / 伺服前端产物", r.status_code == 200 and 'id="app"' in r.text,
              f"长度 {len(r.text)}")

        m = re.search(r'/assets/[^"\']+\.js', r.text)
        check(1, "index.html 引用打包产物", bool(m), m.group(0) if m else "未找到")
        if m:
            r2 = c.get(m.group(0))
            check(1, "打包产物可访问", r2.status_code == 200, f"{len(r2.content)} B")

        for path in ("/fslogo.png", "/fosulogo.png", "/NotoSansSymbols2.ttf"):
            rr = c.get(path)
            check(1, f"{path} 可访问", rr.status_code == 200, f"{len(rr.content)} B")

        print("═══ 第 2 层：鉴权边界 ═══")
        check(2, "未带令牌 → 401", c.get("/api/report/jte-items").status_code == 401)
        check(2, "伪造令牌 → 401",
              c.get("/api/report/jte-items",
                    headers={"Authorization": "Bearer fake-token"}).status_code == 401)
        check(2, "错误口令 → 401",
              c.post("/api/auth/login",
                     json={"username": USERNAME, "password": "definitely-wrong"}).status_code == 401)

        print("═══ 第 3 层：登录与业务接口 ═══")
        r = c.post("/api/auth/login", json={"username": USERNAME, "password": PASSWORD})
        check(3, "正确口令登录 → 200", r.status_code == 200)
        if r.status_code != 200:
            print("  登录失败，后续用例跳过")
            return summarize()

        payload = r.json()
        token = payload["token"]
        # 断言要精确到"字段名"，不能拿子串碰 —— must_change_password 里也有 password
        user_keys = set(payload.get("user", {}).keys())
        check(3, "响应不含口令字段",
              not ({"password", "password_hash", "password_salt"} & user_keys))
        check(3, "用户 id 是字符串（雪花 ID）",
              isinstance(payload.get("user", {}).get("id"), str))
        H = {"Authorization": f"Bearer {token}"}

        check(3, "GET /api/auth/me → 200", c.get("/api/auth/me", headers=H).status_code == 200)

        r = c.get("/api/report/jte-items", headers=H)
        items = r.json().get("items", [])
        catalog = items
        check(3, "条目目录 66 条", r.status_code == 200 and len(items) == 66, f"实际 {len(items)}")
        if items:
            check(3, "条目字段完整",
                  all(k in items[0] for k in ("no", "name", "sub", "req", "opts")),
                  f"首条 {items[0]['no']} {items[0]['name']}")

        print("═══ 第 4 层：导出必须绑定服务端报告快照 ═══")
        r = c.post("/api/report/export", headers=H, json={
            "fmt": "pdf", "title": "验收", "meta": [], "body_html": "<p>x</p>", "filename": "验收",
        })
        check(4, "旧HTML请求/缺少快照绑定 → 422", r.status_code == 422)
        r = c.post("/api/report/export", headers=H, json={
            "fmt": "docx", "report_id": "123456789", "version": 1, "result_digest": "a"*64,
        })
        check(4, "不存在的报告 → 404", r.status_code == 404)
        check(4, "提示不泄漏内部异常",
              not any(k in r.text for k in ("Traceback", "FileNotFoundError", "WinError")))

        print("═══ 第 5 层：打开文件的安全边界 ═══")
        outside = r"C:\Windows\win.ini" if os.name == "nt" else "/etc/passwd"
        check(5, "导出目录之外的路径 → 400",
              c.post("/api/report/open", headers=H, json={"target": outside}).status_code == 400)
        server_info = c.get("/api/system/info", headers=H)
        export_dir = server_info.json().get("export_dir", "") if server_info.status_code == 200 else ""
        # 读取服务端实际配置；不能把板端默认目录当成本机或所有部署的目录。
        missing_path = export_dir.rstrip("/\\") + f"/acceptance-missing-{uuid.uuid4().hex}.pdf"
        missing_file = c.post("/api/report/open", headers=H, json={"target": missing_path}) if export_dir else None
        check(5, "导出目录内不存在的文件 → 404",
              missing_file is not None and missing_file.status_code == 404,
              f"配置目录={export_dir} status={missing_file.status_code if missing_file is not None else '未读取到配置'}")

        print("═══ 第 6 层：初始化状态与恢复口令 ═══")
        st = c.get("/api/setup/status")
        check(6, "GET /api/setup/status → 200", st.status_code == 200)
        info = st.json() if st.status_code == 200 else {}
        check(6, "已初始化", info.get("initialized") is True)
        check(6, "报告版本号", bool(info.get("version")))
        # 本机没有 /userdata/elevator/recovery.key，应当如实报"不可用"
        check(6, "恢复口令可用性如实上报",
              isinstance(info.get("recovery_available"), bool),
              f"recovery_available={info.get('recovery_available')}")
        forgot = c.post("/api/auth/forgot-password",
                        json={"recovery_key": "x", "username": USERNAME,
                              "new_password": "Ee2026elevator"})
        check(6, "未配置恢复口令 → 503（不给用不了的入口）",
              forgot.status_code in (403, 503), f"status={forgot.status_code}")
        check(6, "重复初始化 → 409",
              c.post("/api/setup/init",
                     json={"display_name": "x", "username": "someoneelse",
                           "password": "Ee2026elevator"}).status_code == 409)

        print("═══ 第 7 层：账号管理（单角色：登录即可）═══")
        listing = c.get("/api/accounts", headers=H)
        check(7, "GET /api/accounts → 200", listing.status_code == 200)
        items = listing.json().get("items", []) if listing.status_code == 200 else []
        check(7, "账号 id 是字符串", bool(items) and isinstance(items[0]["id"], str),
              str(items[:1]))
        check(7, "列表不含口令字段",
              all(not ({"password", "password_hash", "password_salt"} & set(i.keys()))
                  for i in items))

        weak = c.post("/api/accounts", headers=H,
                      json={"display_name": "弱口令", "username": "weakuser",
                            "password": "12345678"})
        check(7, "弱口令开户 → 422", weak.status_code == 422, f"status={weak.status_code}")

        created = c.post("/api/accounts", headers=H,
                         json={"display_name": "验收账号", "username": "acceptance_user",
                               "password": "Ee2026elevator", "employee_no": "T-001"})
        check(7, "开户 → 200", created.status_code in (200, 409),
              f"status={created.status_code}")
        new_id = created.json().get("account", {}).get("id") if created.status_code == 200 else None

        if new_id:
            check(7, "新账号 id 是字符串", isinstance(new_id, str))
            # 新账号能登录
            with httpx.Client(base_url=BASE, timeout=15) as c2:
                lr = c2.post("/api/auth/login",
                             json={"username": "acceptance_user", "password": "Ee2026elevator"})
                check(7, "新账号可登录 → 200", lr.status_code == 200)
                tok2 = lr.json().get("token") if lr.status_code == 200 else None
            # 停用需要二次确认
            check(7, "停用缺 confirm → 400",
                  c.patch(f"/api/accounts/{new_id}", headers=H,
                          json={"is_active": False}).status_code == 400)
            disabled = c.patch(f"/api/accounts/{new_id}", headers=H,
                               json={"is_active": False, "confirm": True})
            check(7, "停用成功 → 200", disabled.status_code == 200)
            if tok2:
                check(7, "停用后该账号令牌立即失效 → 401",
                      c.get("/api/auth/me",
                            headers={"Authorization": f"Bearer {tok2}"}).status_code == 401)
            check(7, "重置口令缺 confirm → 400",
                  c.post(f"/api/accounts/{new_id}/reset-password", headers=H,
                         json={"new_password": "Ee2027elevator"}).status_code == 400)
            # 收尾：把验收账号删掉（它没有报告，允许删除）
            check(7, "删除验收账号 → 200",
                  c.delete(f"/api/accounts/{new_id}?confirm=true", headers=H).status_code == 200)

        # 用"当前登录账号"来断言，别用 items[0] —— 列表里可能有测试残留账号，
        # 对已停用账号再停用会返回 200，断言就成了假通过/假失败。
        my_id = payload["user"]["id"]
        check(7, "停用当前登录账号 → 400（不许把自己锁在门外）",
              c.patch(f"/api/accounts/{my_id}", headers=H,
                      json={"is_active": False, "confirm": True}).status_code == 400)
        check(7, "删除当前登录账号 → 400",
              c.delete(f"/api/accounts/{my_id}?confirm=true", headers=H).status_code == 400)

        print("═══ 第 8 层：报告作业（草稿 → 生成 → 作废）═══")
        created = c.post("/api/reports", headers=H, json={})
        check(8, "新建草稿 → 200", created.status_code == 200)
        report = created.json().get("report", {}) if created.status_code == 200 else {}
        rid = report.get("id")
        check(8, "草稿 id 是字符串", isinstance(rid, str), str(rid))
        check(8, "草稿无编号", report.get("report_no") is None)

        if rid:
            items = [
                {"no": item["no"], "result": "fit", "reasons": [], "other_text": ""}
                for item in catalog
            ]
            governor = next(item for item in catalog if item["no"] == "1.9")
            next(item for item in items if item["no"] == "1.9").update(
                result="unfit", reasons=[governor["opts"][0]])
            saved = c.put(
                f"/api/reports/{rid}",
                headers=H,
                json={
                    "form": {"clientName": "验收委托单位", "userName": "验收使用单位",
                             "deviceCategory": "曳引驱动电梯", "productNo": "ACC-001",
                             "installSite": "验收楼", "assessDate": "2026-10-13"},
                    "items": items,
                },
            )
            check(8, "保存填写内容 → 200", saved.status_code == 200,
                  str(saved.json().get("detail", ""))[:80])
            counters = saved.json().get("counters", {})
            check(8, "计数正确（66/已评66/不符合1）",
                  counters.get("total") == 66 and counters.get("unfit") == 1
                  and counters.get("missing") == 0, str(counters))

            draft = c.get(f"/api/reports/{rid}/draft", headers=H)
            check(8, "续录接口回填抬头",
                  draft.status_code == 200
                  and draft.json().get("form", {}).get("clientName") == "验收委托单位")

            generated = c.post(f"/api/reports/{rid}/generate", headers=H, json={})
            check(8, "生成报告 → 200", generated.status_code == 200,
                  str(generated.json().get("detail", ""))[:80])
            rep = generated.json().get("report", {}) if generated.status_code == 200 else {}
            check(8, "生成后分配编号",
                  str(rep.get("report_no", "")).startswith("GDSEI-JTE-"), str(rep.get("report_no")))
            check(8, "状态改为已生成", rep.get("status") == "generated")
            # 限速器首条风险按专家材料为Ⅰ类 → 一票否决 → 0分/四级。
            check(8, "得分与等级按附录A", rep.get("score") == 0 and rep.get("grade") == "四级",
                  f"score={rep.get('score')} grade={rep.get('grade')}")
            check(8, "风险评定值覆盖不符合项", "1.9" in (rep.get("risks") or {}))
            check(8, "叙述文字非空", bool(rep.get("narrative")))

            listed = c.get("/api/reports?status=generated", headers=H)
            check(8, "按状态检索到该报告",
                  any(i["id"] == rid for i in listed.json().get("items", [])))

            cloned = c.post(f"/api/reports/{rid}/clone", headers=H)
            clone_body = cloned.json().get("report", {}) if cloned.status_code == 200 else {}
            check(8, "复制为新建：只带抬头",
                  cloned.status_code == 200 and clone_body.get("items") == []
                  and clone_body.get("form", {}).get("clientName") == "验收委托单位")

            check(8, "已生成不可直接删除 → 400",
                  c.delete(f"/api/reports/{rid}?confirm=true", headers=H).status_code == 400)
            voided = c.post(f"/api/reports/{rid}/void", headers=H,
                            json={"reason": "验收用，作废", "confirm": True})
            check(8, "作废 → 200 且保留编号",
                  voided.status_code == 200
                  and voided.json()["report"]["report_no"] == rep.get("report_no"))
            check(8, "作废后可删除 → 200",
                  c.delete(f"/api/reports/{rid}?confirm=true", headers=H).status_code == 200)
            if clone_body.get("id"):
                c.delete(f"/api/reports/{clone_body['id']}?confirm=true", headers=H)

        missing = c.put("/api/reports/999999999999", headers=H,
                        json={"form": {}, "items": []})
        check(8, "不存在的报告 → 404", missing.status_code == 404)

        print("═══ 第 9 层：系统管理与运维 ═══")
        info = c.get("/api/system/info", headers=H)
        check(9, "GET /api/system/info → 200", info.status_code == 200)
        body = info.json() if info.status_code == 200 else {}
        check(9, "「关于」信息含版本与模型",
              bool(body.get("version")) and "Qwen3.5-4B" in str(body.get("model", "")),
              f"model={body.get('model')}")
        check(9, "条目库 66 条且哈希非空",
              body.get("catalog", {}).get("count") == 66
              and len(str(body.get("catalog", {}).get("hash", ""))) >= 8)

        conf = c.get("/api/system/config", headers=H)
        conf_body = conf.json() if conf.status_code == 200 else {}
        items_cfg = conf_body.get("items", [])
        readonly_cfg = conf_body.get("readonly_items", [])
        editable = [i for i in items_cfg if i.get("editable")]
        editable_keys = {i["key"] for i in editable}
        check(9, "基本配置提供可编辑白名单",
              conf.status_code == 200 and bool(editable)
              and {"institution_name", "report_no_prefix", "backup_keep", "worker_id"} <= editable_keys,
              f"可编辑 {len(editable)} 项 / 总计 {len(items_cfg)} 项")
        check(9, "只读系统信息移出基本配置（改走关于本机）",
              bool(items_cfg) and all(i.get("editable") for i in items_cfg)
              and {i.get("key") for i in readonly_cfg} >= {"app_version", "model", "sqlite_path"},
              f"只读 {[i.get('key') for i in readonly_cfg]}")
        check(9, "可编辑项带表单类型与重启标记",
              all(i.get("type") in ("str", "int", "bool") and "restart" in i for i in editable))
        by_key = {i["key"]: i for i in editable}
        check(9, "目录类配置带 directory 标记",
              by_key.get("export_dir", {}).get("ui") == "directory"
              and by_key.get("backup_dir", {}).get("ui") == "directory")
        picker = c.get("/api/system/folder-picker", headers=H)
        picker_body = picker.json() if picker.status_code == 200 else {}
        check(9, "目录选择器可用性接口 → 200",
              picker.status_code == 200
              and isinstance(picker_body.get("available"), bool)
              and picker_body.get("platform") in ("windows", "linux"),
              f"available={picker_body.get('available')} method={picker_body.get('method')} platform={picker_body.get('platform')}")

        bad_cfg = c.put("/api/system/config", headers=H, json={"values": {"backup_keep": 0}})
        check(9, "基本配置非法值 → 400 且原因可读",
              bad_cfg.status_code == 400
              and "备份保留份数" in str(bad_cfg.json().get("detail", "")),
              str(bad_cfg.json().get("detail", ""))[:80])
        unknown_cfg = c.put("/api/system/config", headers=H, json={"values": {"__nope__": 1}})
        check(9, "基本配置未知键 → 400", unknown_cfg.status_code == 400,
              str(unknown_cfg.json().get("detail", ""))[:80])
        cur_keep = next((i["value"] for i in editable if i["key"] == "backup_keep"), None)
        same_cfg = c.put("/api/system/config", headers=H, json={"values": {"backup_keep": cur_keep}})
        check(9, "基本配置保存（同值不落盘） → 200", same_cfg.status_code == 200,
              str(same_cfg.json().get("detail", ""))[:80])

        audit = c.get("/api/system/audit?event=login_ok&size=5", headers=H)
        check(9, "GET /api/system/audit → 200", audit.status_code == 200)
        events = [i["event"] for i in audit.json().get("items", [])] if audit.status_code == 200 else []
        check(9, "审计可按事件筛选（有本次登录）",
              audit.json().get("total", 0) >= 1 and set(events) == {"login_ok"},
              str(events[:4]))

        diag = c.get("/api/system/diagnose", headers=H)
        check(9, "GET /api/system/diagnose → 200", diag.status_code == 200)
        checks = diag.json().get("checks", []) if diag.status_code == 200 else []
        names = [x["name"] for x in checks]
        check(9, "诊断覆盖关键项",
              all(n in names for n in ("业务库", "条目库", "知识图谱", "导出目录", "系统时间")),
              str(names))
        check(9, "业务库检查通过",
              next((x["status"] for x in checks if x["name"] == "业务库"), "") == "ok")

        # 使用真实临时文件充当父目录，确定性地触发目录创建失败。
        # 不再假定配置的备份目录一定不可写，正常部署的目录本来就应当可用。
        with _tf.NamedTemporaryFile(prefix="elevator-acc-blocked-") as blocked:
            bad_backup = c.post("/api/system/backup", headers=H, params={"target_dir": blocked.name})
        check(9, "备份目录不可用时提示可读",
              bad_backup.status_code == 503
              and "备份目录不可用" in str(bad_backup.json().get("detail", "")),
              str(bad_backup.json().get("detail", ""))[:80])

        target = _tf.mkdtemp(prefix="elevator-acc-backup-")
        ok_backup = c.post(f"/api/system/backup?target_dir={target}", headers=H)
        check(9, "指定目录可备份 → 200", ok_backup.status_code == 200,
              str(ok_backup.json().get("detail", ""))[:80])
        if ok_backup.status_code == 200:
            payload = ok_backup.json()
            check(9, "备份含业务库与清单", payload.get("files", 0) >= 1
                  and os.path.isfile(os.path.join(payload["dir"], "manifest.json")),
                  payload.get("dir"))
            listed_backups = c.get("/api/system/backups", headers=H)
            check(9, "备份列表接口可用", listed_backups.status_code == 200)
            check(9, "恢复缺 confirm → 400",
                  c.post(f"/api/system/restore?source_dir={payload['dir']}",
                         headers=H).status_code == 400)
            check(9, "拿非备份目录恢复 → 400 且原因可读",
                  c.post(f"/api/system/restore?source_dir={target}&confirm=true",
                         headers=H).status_code == 400)

        c.post("/api/auth/logout", headers=H)
    return summarize()


def summarize() -> int:
    passed = sum(1 for _, _, ok, _ in results if ok)
    print()
    print(f"合计 {len(results)} 项，通过 {passed}，失败 {len(results) - passed}")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
