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

(async () => {
  const browser = await chromium.launch({ executablePath: EXE });
  const page = await browser.newPage({ viewport: { width: 600, height: 960 } });
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

  await page.click(".actionbar .btn-primary");
  await page.waitForSelector(".paper", { timeout: 20000 });
  await step("点「校验并生成报告」");

  await page.locator(".actionbar .btn-primary").first().click();
  await page.waitForTimeout(2500);
  await step("点「导出 PDF」(本机无 LibreOffice)");

  await page.locator(".sidebar-nav li:nth-child(1)").click();
  await step("返回录入页");

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
