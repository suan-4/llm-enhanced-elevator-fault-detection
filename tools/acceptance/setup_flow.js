/**
 * 初始化向导验收：**必须用全新空库**跑，否则进不了向导页。
 *
 * 用法（两步）：
 *   1) 起一个指向空库的临时后端：
 *        $env:SQLITE_PATH="D:\tmp\fresh.db"
 *        cd backend; python -m uvicorn app.main:app --port 8082
 *   2) BASE=http://127.0.0.1:8082 node tools/acceptance/setup_flow.js
 *
 * 覆盖：空库打开即进向导 → 口令未确认时按钮禁用 → 建号后直接进入录入页。
 */
const PW =
  process.env.PLAYWRIGHT_MODULE ||
  "C:/Users/何/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright";
const EXE =
  process.env.CHROMIUM_EXE ||
  "C:/Users/何/AppData/Local/ms-playwright/chromium-1228/chrome-win64/chrome.exe";
const BASE = process.env.BASE || "http://127.0.0.1:8082";
const { chromium } = require(PW);

(async () => {
  const browser = await chromium.launch({ executablePath: EXE });
  const page = await browser.newPage({ viewport: { width: 600, height: 960 } });
  const errs = [];
  page.on("pageerror", (e) => errs.push(String(e.message).split("\n")[0]));
  page.on("console", (m) => m.type() === "error" && errs.push(String(m.text()).slice(0, 100)));

  await page.goto(BASE + "/#/", { waitUntil: "load" });
  const title = await page
    .waitForSelector(".plain-card h1", { timeout: 15000 })
    .then(() => page.locator(".plain-card h1").innerText())
    .catch(() => "(没出现向导)");
  const atSetup = page.url().includes("#/setup");
  console.log(`  空库打开 → 标题「${title.trim()}」，地址 ${page.url()}`);

  await page.locator(".plain-card .input").nth(0).fill("张三");
  await page.locator(".plain-card .input").nth(1).fill("zhangsan");
  await page.locator(".plain-card .input").nth(2).fill("elevator2026");
  const blockedWithoutConfirm = await page.locator(".plain-card .btn-primary").isDisabled();
  console.log(`  口令未确认 → 按钮禁用：${blockedWithoutConfirm}`);

  await page.locator(".plain-card .input").nth(3).fill("elevator2026");
  await page.locator(".plain-card .btn-primary").click();
  await page.waitForSelector(".items tbody tr", { timeout: 20000 });
  const rows = await page.locator(".items tbody tr").count();
  const sidebar = await page.locator(".sidebar").count();
  console.log(`  建号后 → 条目 ${rows} 条，侧栏 ${sidebar} 个，报错 ${errs.length} 条`);

  const ok =
    title.trim() === "系统初始化" && atSetup && blockedWithoutConfirm && rows === 66 && sidebar === 1 && errs.length === 0;
  console.log(`  结论 ${ok ? "通过：空库可自助初始化" : "未通过"}`);
  await browser.close();
  process.exit(ok ? 0 : 1);
})();
