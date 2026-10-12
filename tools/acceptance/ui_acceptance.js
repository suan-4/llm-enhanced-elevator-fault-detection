/**
 * 界面层验收：用真实浏览器跑完整链路，覆盖两个板端逻辑视口。
 *
 * 前置：后端已在 BASE 上运行（前端产物由后端伺服）。
 *
 * 用法：
 *   node tools/acceptance/ui_acceptance.js
 *
 * 可用环境变量覆盖：
 *   BASE              默认 http://127.0.0.1:8081
 *   PLAYWRIGHT_MODULE 默认取捆绑运行时的 playwright
 *   CHROMIUM_EXE      默认取已安装的 chromium-1228
 */

const BASE = process.env.BASE || "http://127.0.0.1:8081";
const PLAYWRIGHT_MODULE =
  process.env.PLAYWRIGHT_MODULE ||
  "C:/Users/何/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright";
const CHROMIUM_EXE =
  process.env.CHROMIUM_EXE ||
  "C:/Users/何/AppData/Local/ms-playwright/chromium-1228/chrome-win64/chrome.exe";
const USERNAME = process.env.ELEVATOR_USER || "admin";
const PASSWORD = process.env.ELEVATOR_PASSWORD || "admin123";

const { chromium } = require(PLAYWRIGHT_MODULE);

(async () => {
  const browser = await chromium.launch({ executablePath: CHROMIUM_EXE });
  let allOk = true;

  const viewports = [
    { w: 600, h: 960, label: "竖屏 600x960（板端逻辑视口）" },
    { w: 960, h: 600, label: "横屏 960x600" },
  ];

  for (const vp of viewports) {
    const page = await browser.newPage({ viewport: { width: vp.w, height: vp.h } });
    const errs = [];
    page.on("pageerror", (e) => errs.push("pageerror: " + String(e.message).split("\n")[0]));
    page.on("response", (r) => {
      const u = r.url();
      if (r.status() >= 400 && !u.includes("/api/health/ready") && !u.includes("/api/report/export")) {
        errs.push(`${r.status()} ${u.replace(BASE, "")}`);
      }
    });

    await page.goto(BASE + "/#/login", { waitUntil: "load" });

    // ── 启动页与登录页要素（原版有、迁移中曾被遗漏，这里固化为回归项）──
    const splashSeen = await page
      .waitForSelector(".splash", { state: "attached", timeout: 5000 })
      .then(() => true)
      .catch(() => false);
    await page.waitForSelector(".login-card", { timeout: 10000 });
    const logoCount = await page.locator(".login-card .lockup img").count();
    const logoAlts = await page.locator(".login-card .lockup img").evaluateAll((els) =>
      els.map((e) => e.getAttribute("alt") || ""),
    );
    const hasFsLogo = logoAlts.some((a) => a.includes("特种设备"));
    const hasFosuLogo = logoAlts.some((a) => a.includes("佛山大学"));
    const loginTitle = (await page.locator(".login-title").innerText()).trim();
    const loginSub = (await page.locator(".login-sub").innerText()).trim();
    const loginFoot = (await page.locator(".login-foot").innerText()).trim();
    const placeholders = await page
      .locator(".login-field input")
      .evaluateAll((els) => els.map((e) => e.placeholder));
    // 退出系统按钮：非一体机环境下不应出现（kiosk 未运行）
    const exitBtnCount = await page.locator(".login-x").count();

    const loginPageOk =
      splashSeen &&
      logoCount === 2 &&
      hasFsLogo &&
      hasFosuLogo &&
      loginTitle === "电梯安全评估系统" &&
      loginSub.includes("请使用您的账号登录") &&
      loginFoot.includes("广东省特种设备检测研究院佛山检测院") &&
      loginFoot.includes("佛山大学") &&
      placeholders.includes("请输入用户名") &&
      placeholders.includes("请输入口令") &&
      exitBtnCount === 0;

    await page.fill(".login-field input[type=text]", USERNAME);
    await page.fill(".login-field input[type=password]", PASSWORD);
    await page.click("button[type=submit]");
    await page.waitForSelector(".items tbody tr", { timeout: 20000 });

    const rows = await page.locator(".items tbody tr").count();
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);

    await page.click(".actionbar .btn-primary");
    await page.waitForTimeout(300);
    const alertVisible = await page.locator(".alert").isVisible();
    const alertCount = await page.locator(".alert-list li").count();

    await page.locator(".alert-list a").first().click();
    await page.waitForTimeout(600);
    const focusedId = await page.evaluate(() => (document.activeElement && document.activeElement.id) || "");

    await page.fill("#f-clientName", "佛山市展翰房地产开发有限公司");
    await page.fill("#f-userName", "佛山市展翰房地产开发有限公司");
    await page.fill("#f-deviceCategory", "曳引驱动电梯");
    await page.fill("#f-productNo", "44786091");

    await page.evaluate(() => {
      document.querySelectorAll(".items tbody tr").forEach((tr) => {
        const first = tr.querySelectorAll(".seg label")[0];
        if (!first.classList.contains("on")) first.click();
      });
    });
    await page.evaluate(() =>
      document.getElementById("row-2-1").querySelectorAll(".seg label")[1].click(),
    );
    await page.locator("#row-2-1 .chk.is-other input").waitFor({ state: "attached", timeout: 8000 });
    await page.evaluate(() =>
      document.getElementById("row-2-1").querySelector(".chk.is-other input").click(),
    );
    const ta = page.locator("#row-2-1 textarea");
    await ta.waitFor({ state: "visible", timeout: 8000 });
    await ta.fill("箱体出现裂纹");
    await page.waitForTimeout(300);
    const counters = (await page.locator(".actionbar .count").innerText()).replace(/\s+/g, " ");

    await page.click(".actionbar .btn-primary");
    await page.locator(".export-zone").waitFor({ state: "visible", timeout: 12000 });
    const papers = await page.locator(".paper").count();
    const bodyText = await page.locator(".report-wrap").innerText();
    const overflowReport = await page.evaluate(
      () => document.documentElement.scrollWidth - window.innerWidth,
    );
    const grade4 = bodyText.includes("四级");
    const score0 = bodyText.includes("综合安全状况得分：0");
    const hasAppendix = bodyText.includes("降低风险措施");
    const hasAppendixA = bodyText.includes("附录A");
    const filled = bodyText.includes("44786091");

    await page.click(".export-zone .btn-primary");
    await page.waitForTimeout(2500);
    const toast = (await page.locator(".toast").count())
      ? await page.locator(".toast").innerText()
      : "";
    const exportOk = await page.locator(".export-result").count()
      ? await page.locator(".export-result").isVisible().catch(() => false)
      : false;

    const pass =
      loginPageOk && rows === 66 && overflow <= 0 && alertVisible && alertCount > 0 &&
      focusedId.startsWith("f-") && counters.includes("未填 0 项") &&
      papers === 4 && overflowReport <= 0 && grade4 && score0 &&
      hasAppendix && hasAppendixA && filled &&
      (exportOk || toast.length > 0) && errs.length === 0;
    allOk = allOk && pass;

    console.log(`══ ${vp.label} ══`);
    console.log(`  启动页              ${splashSeen ? "出现" : "未捕获"}`);
    console.log(`  登录页要素          联合logo=${logoCount}（特检院=${hasFsLogo} 佛山大学=${hasFosuLogo}）`);
    console.log(`                     标题「${loginTitle}」/「${loginSub}」`);
    console.log(`                     页脚含机构署名=${loginFoot.includes("广东省特种设备检测研究院佛山检测院")}`);
    console.log(`                     退出按钮（非一体机应无）=${exitBtnCount}`);
    console.log(`  条目行数        ${rows}`);
    console.log(`  横向溢出        主页面 ${overflow} px / 报告页 ${overflowReport} px`);
    console.log(`  必填拦截        ${alertVisible}，清单 ${alertCount} 条`);
    console.log(`  跳转定位        ${focusedId}`);
    console.log(`  计数栏          ${counters}`);
    console.log(`  报告页数        ${papers}`);
    console.log(`  内容校验        四级=${grade4} 得分0=${score0} 附页=${hasAppendix} 附录A=${hasAppendixA} 抬头=${filled}`);
    console.log(`  导出            ${exportOk ? "成功" : "失败可见 → " + toast.slice(0, 70)}`);
    console.log(`  页面错误        ${errs.length}${errs.length ? " " + errs.slice(0, 3).join(" | ") : ""}`);
    console.log(`  结论            ${pass ? "通过" : "未通过"}`);
    await page.close();
  }

  await browser.close();
  console.log();
  console.log(allOk ? "两个视口全部通过" : "存在未通过项");
  process.exit(allOk ? 0 : 1);
})();
