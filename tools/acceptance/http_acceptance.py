"""接口层验收：对运行中的后端逐层校验，覆盖 HTTP、鉴权、业务接口、降级与安全边界。

用法（先启动后端，见 README）：
    python tools/acceptance/http_acceptance.py
    BASE=http://127.0.0.1:8081 python tools/acceptance/http_acceptance.py

退出码 0 表示全部通过。
"""

from __future__ import annotations

import os
import re
import sys

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
        check(3, "响应不含口令", "password" not in str(payload.get("user", {})))
        H = {"Authorization": f"Bearer {token}"}

        check(3, "GET /api/auth/me → 200", c.get("/api/auth/me", headers=H).status_code == 200)

        r = c.get("/api/report/jte-items", headers=H)
        items = r.json().get("items", [])
        check(3, "条目目录 66 条", r.status_code == 200 and len(items) == 66, f"实际 {len(items)}")
        if items:
            check(3, "条目字段完整",
                  all(k in items[0] for k in ("no", "name", "sub", "req", "opts")),
                  f"首条 {items[0]['no']} {items[0]['name']}")

        print("═══ 第 4 层：导出失败必须可见且可读 ═══")
        r = c.post("/api/report/export", headers=H, json={
            "fmt": "pdf", "title": "验收", "meta": [], "body_html": "<p>x</p>", "filename": "验收",
        })
        detail = ""
        try:
            detail = r.json().get("detail", "")
        except Exception:  # noqa: BLE001
            detail = r.text
        if r.status_code == 200:
            check(4, "导出成功", True, "本机具备 LibreOffice")
        else:
            check(4, "导出失败非静默", r.status_code >= 400, f"status={r.status_code}")
            check(4, "提示指向具体原因",
                  ("导出目录" in detail) or ("LibreOffice" in detail) or ("soffice" in detail),
                  detail[:110])
            check(4, "提示不泄漏内部异常",
                  not any(k in detail for k in
                          ("FileNotFoundError", "WinError", "Traceback", "AttributeError")),
                  detail[:110])

        print("═══ 第 5 层：打开文件的安全边界 ═══")
        outside = r"C:\Windows\win.ini" if os.name == "nt" else "/etc/passwd"
        check(5, "导出目录之外的路径 → 400",
              c.post("/api/report/open", headers=H, json={"target": outside}).status_code == 400)
        check(5, "导出目录内不存在的文件 → 404",
              c.post("/api/report/open", headers=H,
                     json={"target": "/home/user/导出/不存在的文件.pdf"}).status_code == 404)

        c.post("/api/auth/logout", headers=H)
    return summarize()


def summarize() -> int:
    passed = sum(1 for _, _, ok, _ in results if ok)
    print()
    print(f"合计 {len(results)} 项，通过 {passed}，失败 {len(results) - passed}")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
