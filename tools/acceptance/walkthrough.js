/**
 * 端到端走查验收：在板端逻辑视口（600x960）上像用户一样把主要路径走一遍，
 * 每步断言"页面不是空白"（曾经出现过点几下就整片空白且无提示的问题）。
 *
 * 前置：后端已在 8081 运行。
 * 用法：node tools/acceptance/walkthrough.js
 */
const PW =
  process.env.PLAYWRIGHT_MODULE ||
  "C:/Users/何/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright";
const EXE =
  process.env.CHROMIUM_EXE ||
  "C:/Users/何/AppData/Local/ms-playwright/chromium-1228/chrome-win64/chrome.exe";
const BASE = process.env.BASE || "http://127.0.0.1:8081";
const USERNAME = process.env.ELEVATOR_USER || "admin";
const PASSWORD = process.env.ELEVATOR_PASSWORD || "admin123";

const { chromium } = require(PW);

/** 本机没有 LibreOffice，"导出"必然返回 500 —— 属于预期，不算失败。 */
const EXPECTED = [/\/api\/export/];

const BLANK = () => {
  const main = document.querySelector(".main");
  return {
    mainW: main ? Math.round(main.getBoundingClientRect().width) : -1,
    bodyText: document.body.innerText.replace(/\s+/g, " ").trim().length,
    login: !!document.querySelector(".login-card"),
    boot: !!document.querySelector('#boot-fallback:not([hidden])'),
  };
};

/** 先种一份空白草稿：应用会续录上次未完成的草稿，不先清干净
    "点报告预览应被漏填拦下"这类步骤就不成立了。 */
async function seedEmptyDraft(browser) {
  const ctx = await browser.newContext();
  try {
    const login = await ctx.request.post(BASE + "/api/auth/login", {
      data: { username: USERNAME, password: PASSWORD },
    });
    const { token } = await login.json();
    await ctx.request.post(BASE + "/api/reports", {
      headers: { Authorization: `Bearer ${token}` },
      data: {},
    });
  } finally {
    await ctx.close();
  }
}

(async () => {
  const browser = await chromium.launch({ executablePath: EXE });
  const page = await browser.newPage({ viewport: { width: 600, height: 960 } });
  await seedEmptyDraft(browser);
  const errs = [];
  page.on("pageerror", (e) => errs.push("pageerror: " + String(e.message).split("\n")[0]));
  page.on("console", (m) => {
    if (m.type() !== "error") return;
    const t = String(m.text());
    if (t.includes("Failed to load resource") && EXPECTED.some((re) => re.source.includes("export"))) return;
    errs.push("console: " + t.slice(0, 120));
  });

  let ok = true;
  const step = async (name) => {
    await page.waitForTimeout(400);
    const s = await page.evaluate(BLANK);
    const bad = s.bodyText < 20 || s.boot;
    if (bad) ok = false;
    console.log(
      `  ${bad ? "✗" : "✓"} ${name.padEnd(26)} 正文${String(s.bodyText).padStart(4)}字 main=${s.mainW} 登录页=${s.login} 兜底=${s.boot}`,
    );
  };

  await page.goto(BASE + "/#/login", { waitUntil: "load" });
  await page.waitForSelector(".login-card", { timeout: 15000 });
  await step("打开登录页");

  await page.fill(".login-card .form-input[type=text]", USERNAME);
  await page.fill(".login-card .form-input[type=password]", PASSWORD);
  await page.click("button[type=submit]");
  await page.waitForSelector(".items tbody tr", { timeout: 20000 });
  await step("登录进入录入页");

  await page.click(".sidebar-nav li:nth-child(2)");
  await step("点「报告预览」(有漏填)");
  await page.locator(".alert-list a").first().click();
  await step("点漏填清单跳转");

  await page.fill("#f-clientName", "佛山市展翰房地产开发有限公司");
  await page.fill("#f-userName", "佛山市展翰房地产开发有限公司");
  await page.fill("#f-deviceCategory", "曳引驱动电梯");
  await page.fill("#f-productNo", "44786091");
  await page.click(".actionbar .btn:not(.btn-primary)");
  await step("点「保存草稿」");

  await page.evaluate(() => {
    document.querySelectorAll(".items tbody tr").forEach((tr) => {
      const first = tr.querySelectorAll(".seg label")[0];
      if (!first.classList.contains("on")) first.click();
    });
    document.getElementById("row-2-1").querySelectorAll(".seg label")[1].click();
  });
  await page.waitForTimeout(300);
  await page.evaluate(() =>
    document.getElementById("row-2-1").querySelector(".chk.is-other input").click(),
  );
  await page.locator("#row-2-1 textarea").fill("箱体出现裂纹");
  await step("填完 66 条 + 一条不符合");

  // 落库验证：刷新后必须还在（这一条是本批最要紧的行为 —— 以前纯前端状态，一刷新全没）
  // 等自动保存的防抖窗口过去（800ms）再刷新，否则测的是"防抖窗口内丢改动"
  await page.waitForTimeout(1400);
  await page.reload({ waitUntil: "load" });
  await page.waitForSelector(".items tbody tr", { timeout: 25000 });
  await page.waitForTimeout(800);
  const afterReload = await page.evaluate(() => {
    const client = document.querySelector("#f-clientName");
    const text = document.querySelector(".actionbar .count")?.textContent || "";
    return {
      client: client ? client.value : "",
      count: text.replace(/\s+/g, " ").trim(),
      rows: document.querySelectorAll(".items tbody tr").length,
    };
  });
  const persisted =
    afterReload.client.includes("展翰") &&
    afterReload.rows === 66 &&
    afterReload.count.includes("已评 66 项");
  if (!persisted) {
    ok = false;
    console.log(
      `  ✗ 刷新后没恢复录入内容：抬头="${afterReload.client}" 行数=${afterReload.rows} 计数=${afterReload.count}`,
    );
  }
  await step("刷新后数据仍在（已落库）");

  await page.click(".actionbar .btn-primary");
  await page.waitForSelector(".paper", { timeout: 20000 });
  await step("点「校验并生成报告」");

  const reportNo = await page
    .locator(".report-meta")
    .innerText()
    .then((t) => (t.match(/GDSEI-JTE-\d{8}-\d{3}/) || [""])[0])
    .catch(() => "");
  if (!reportNo) {
    ok = false;
    console.log("  ✗ 生成后报告页没显示报告编号");
  } else {
    console.log(`  · 后端分配的报告编号：${reportNo}`);
  }

  await page.locator(".actionbar .btn-primary").first().click();
  await page.waitForTimeout(2500);
  await step("点「导出 PDF」(本机无 LibreOffice)");

  await page.locator(".sidebar-nav li:nth-child(1)").click();
  // 只断言"不是空白页"会漏掉"点了没反应"这类问题，
  // 所以这里必须确认真的回到了录入视图（条目表可见）。
  await page.waitForTimeout(400);
  const backToInput = await page
    .locator(".items tbody tr")
    .first()
    .isVisible()
    .catch(() => false);
  const stillPreview = await page
    .locator(".actionbar .btn-primary")
    .first()
    .innerText()
    .catch(() => "");
  if (!backToInput || stillPreview.includes("导出")) {
    ok = false;
    console.log(`  ✗ 点「评估报告录入」没有回到录入视图（条目表可见=${backToInput} 悬浮岛按钮=${stillPreview}）`);
  }
  await step("返回录入页");

  // ── 报告管理页：能查到刚才生成的报告、能作废、能删除 ──
  await page.locator(".sidebar-nav li:nth-child(3)").click();
  await page.waitForSelector(".data-table, .empty-state", { timeout: 15000 });
  await page.waitForTimeout(600);
  const listText = await page.locator(".page-pad").innerText();
  if (reportNo && !listText.includes(reportNo)) {
    ok = false;
    console.log(`  ✗ 报告管理页里查不到刚生成的报告 ${reportNo}`);
  }
  const reportOverflow = await page.evaluate(
    () => document.documentElement.scrollWidth - window.innerWidth,
  );
  if (reportOverflow > 0) {
    ok = false;
    console.log(`  ✗ 报告管理页横向溢出 ${reportOverflow}px`);
  }
  await step("报告管理页");

  if (reportNo) {
    const row = page.locator(".data-table tbody tr", { hasText: reportNo });
    await row.locator("button", { hasText: "作废" }).click();
    await page.waitForSelector(".dialog-mask .dialog", { timeout: 8000 });
    await page.locator(".dialog .input").first().fill("走查用，作废");
    await page.locator(".dialog-foot button:last-child").click();
    await page.waitForTimeout(1200);
    const voidText = await page.locator(".page-pad").innerText();
    if (!voidText.includes("已作废")) {
      ok = false;
      console.log("  ✗ 作废后列表里没看到「已作废」");
    }
    await step("作废报告（必填原因）");

    await page
      .locator(".data-table tbody tr", { hasText: reportNo })
      .locator("button", { hasText: "删除" })
      .click();
    await page.waitForSelector(".dialog-mask .dialog", { timeout: 8000 });
    await page.locator(".dialog-foot button:last-child").click();
    await page.waitForTimeout(1200);
    if ((await page.locator(".page-pad").innerText()).includes(reportNo)) {
      ok = false;
      console.log("  ✗ 删除作废报告后仍在列表里");
    }
    await step("删除作废报告");
  }

  await page.locator(".sidebar-nav li:nth-child(1)").click();
  await page.waitForTimeout(600);
  await step("回到录入页");

  // ── 系统设置：诊断能出结果、日志能查、窄屏不横向溢出 ──
  await page.locator(".sidebar-nav li:nth-child(5)").click();
  await page.waitForSelector(".tabs", { timeout: 15000 });
  await step("打开系统设置");
  const settingsOverflow = await page.evaluate(
    () => document.documentElement.scrollWidth - window.innerWidth,
  );
  if (settingsOverflow > 0) {
    ok = false;
    console.log(`  ✗ 系统设置页横向溢出 ${settingsOverflow}px`);
  }
  await page.locator(".tab", { hasText: "诊断" }).click();
  await page.locator(".toolbar .btn-primary").click();
  await page.waitForTimeout(4000);
  const diagText = await page.locator(".page-pad").innerText();
  if (!diagText.includes("业务库") || !diagText.includes("正常")) {
    ok = false;
    console.log("  ✗ 诊断没给出检查结果");
  }
  await step("运行诊断");
  await page.locator(".tab", { hasText: "审计日志" }).click();
  await page.waitForTimeout(800);
  const auditText = await page.locator(".page-pad").innerText();
  if (!auditText.includes("login_ok")) {
    ok = false;
    console.log("  ✗ 审计日志页没显示登录事件");
  }
  await step("查看审计日志");
  await page.locator(".tab", { hasText: "关于" }).click();
  await page.waitForTimeout(600);
  const aboutText = await page.locator(".page-pad").innerText();
  if (!aboutText.includes("Qwen3.5-4B")) {
    ok = false;
    console.log("  ✗ 关于页没显示模型名");
  }
  await step("关于页");

  // ── 账号管理页（批 2 新增）：能开户、能删掉、不横向溢出 ──
  await page.locator(".sidebar-nav li:nth-child(4)").click();
  await page.waitForSelector(".data-table, .empty-state", { timeout: 15000 });
  await step("打开账号管理");
  const acctOverflow = await page.evaluate(
    () => document.documentElement.scrollWidth - window.innerWidth,
  );
  if (acctOverflow > 0) {
    ok = false;
    console.log(`  ✗ 账号管理页横向溢出 ${acctOverflow}px`);
  }
  const stamp = String(Date.now()).slice(-6);
  await page.locator(".toolbar .btn-primary").click();
  await page.waitForSelector(".dialog-mask .dialog", { timeout: 8000 });
  await page.locator(".dialog .input").nth(0).fill("验收临时账号");
  await page.locator(".dialog .input").nth(1).fill(`acc_${stamp}`);
  await page.locator(".dialog .input").nth(3).fill("Ee2026elevator");
  await page.locator(".dialog-foot .btn-primary").click();
  await page.waitForTimeout(1200);
  const created = await page.locator(".data-table tbody tr").count();
  if (!(await page.locator(".data-table").innerText()).includes(`acc_${stamp}`)) {
    ok = false;
    console.log(`  ✗ 开户后列表里没看到新账号（当前 ${created} 行）`);
  }
  await step("新增账号");
  // 删掉它（二次确认弹层）
  await page
    .locator(".data-table tbody tr", { hasText: `acc_${stamp}` })
    .locator("button", { hasText: "删除" })
    .click();
  await page.waitForSelector(".dialog-mask .dialog", { timeout: 8000 });
  // 确认按钮是红色的 btn-danger，不是 btn-primary —— 用"最后一个按钮"更稳
  await page.locator(".dialog-foot button:last-child").click();
  await page.waitForTimeout(1200);
  if ((await page.locator(".data-table").innerText()).includes(`acc_${stamp}`)) {
    ok = false;
    console.log("  ✗ 删除账号后列表里仍然存在");
  }
  await step("删除账号");
  await page.locator(".sidebar-nav li:nth-child(1)").click();
  await page.waitForTimeout(600);
  await step("回到录入页");

  await page.locator(".sidebar-toggle").click();
  await page.waitForTimeout(400);
  await page.locator(".user-bar button").first().click();
  await page.waitForSelector(".login-card", { timeout: 15000 });
  await step("点「注销」→ 登录页");

  await page.fill(".login-card .form-input[type=text]", USERNAME);
  await page.fill(".login-card .form-input[type=password]", PASSWORD);
  await page.click("button[type=submit]");
  await page.waitForSelector(".items tbody tr", { timeout: 20000 });
  const exitBtn = page.locator(".user-bar button.danger");
  if (await exitBtn.count()) {
    await exitBtn.click();
    await step("点「退出系统」");
  } else {
    console.log("  - 「退出系统」未显示（非一体机环境），跳过");
  }

  console.log();
  console.log(`  页面报错 ${errs.length} 条${errs.length ? ": " + [...new Set(errs)].slice(0, 3).join(" | ") : ""}`);
  console.log(`  结论 ${ok && errs.length === 0 ? "通过：全程无空白页" : "未通过"}`);
  await browser.close();
  process.exit(ok && errs.length === 0 ? 0 : 1);
})();
