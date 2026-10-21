/** Real-browser fault injection. Run only against the disposable local test server. */
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { chromium } = require(
  process.env.PLAYWRIGHT_MODULE ||
    "C:/Users/何/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright",
);
const BASE = process.env.BASE || "http://127.0.0.1:8087";
if (BASE !== "http://127.0.0.1:8087") throw new Error("Use the isolated local acceptance server");

(async () => {
  const browser = await chromium.launch({
    executablePath: process.env.CHROMIUM_EXE ||
      "C:/Users/何/AppData/Local/ms-playwright/chromium-1228/chrome-win64/chrome.exe",
  });
  try {
    const page = await browser.newPage({ viewport: { width: 600, height: 960 } });
    const errors = [];
    page.on("pageerror", e => errors.push(e.message));
    const login = await page.request.post(BASE + "/api/auth/login", {
      data: { username: "admin", password: "admin123" },
    });
    assert.equal(login.status(), 200);
    const { token } = await login.json();
    const headers = { Authorization: `Bearer ${token}` };
    const created = await page.request.post(BASE + "/api/reports", { headers, data: {} });
    const { report } = await created.json();
    const count = async () => (await (await page.request.get(BASE + "/api/reports", { headers })).json()).total;
    const beforeCount = await count();
    await page.goto(BASE + "/#/login");
    await page.locator(".login-card").waitFor();
    await page.locator(".login-card input[type=text]").fill("admin");
    await page.locator(".login-card input[type=password]").fill("admin123");
    await page.locator("button[type=submit]").click();
    await page.locator(".items tbody tr").first().waitFor();
    let fail = true;
    await page.route("**/api/reports/*", route => {
      if (fail && route.request().method() === "PUT")
        return route.fulfill({ status: 500, contentType: "application/json",
          body: JSON.stringify({ detail: "验收注入：保存失败" }) });
      return route.continue();
    });
    const failedSave = page.waitForResponse(r => r.request().method() === "PUT" && r.status() === 500);
    await page.locator("#f-clientName").fill("保存失败时必须保留的输入");
    await failedSave;
    for (let attempt = 0; attempt < 2; attempt++) {
      await page.locator(".new-btn").click();
      await page.locator(".dialog-foot .btn-primary").click();
      await page.getByText("验收注入：保存失败", { exact: true }).waitFor();
      assert.equal(await page.locator("#f-clientName").inputValue(), "保存失败时必须保留的输入");
      assert.equal(await count(), beforeCount, "failed save must not create a new report");
    }
    const output = path.resolve("output/playwright/save-failure-20261020");
    fs.mkdirSync(output, { recursive: true });
    await page.screenshot({ path: path.join(output, "save-blocked.png") });
    fail = false;
    const saved = page.waitForResponse(r =>
      r.url().endsWith(`/api/reports/${report.id}`) && r.request().method() === "PUT" && r.status() === 200);
    await page.locator(".btn-save").click();
    await saved;
    const stored = await (await page.request.get(BASE + `/api/reports/${report.id}`, { headers })).json();
    assert.equal(stored.report.form.clientName, "保存失败时必须保留的输入");
    await page.locator(".new-btn").click();
    await page.locator(".dialog-foot .btn-primary").click();
    await page.waitForFunction(() => document.querySelector("#f-clientName").value === "");
    assert.equal(await count(), beforeCount + 1);
    assert.deepEqual(errors, []);
    const result = { save_failure_blocks_new: true, repeated_attempt_preserves_input: true,
      recovery_saves_input: true, new_after_save_works: true, page_errors: errors };
    fs.writeFileSync(path.join(output, "results.json"), JSON.stringify(result, null, 2));
    console.log(JSON.stringify(result, null, 2));
  } finally {
    await browser.close();
  }
})().catch(e => { console.error(e); process.exitCode = 1; });
