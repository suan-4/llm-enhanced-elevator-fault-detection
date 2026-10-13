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

/** 用接口种一份**全新空白草稿**再打开界面。
    应用改成"续录上次未完成的草稿"之后，不先清干净的话，
    「漏填拦截」「三态按钮」这类断言会因为草稿已被填满而失效。 */
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
  const browser = await chromium.launch({ executablePath: CHROMIUM_EXE });
  let allOk = true;

  const viewports = [
    { w: 600, h: 960, label: "竖屏 600x960（板端逻辑视口）" },
    { w: 960, h: 600, label: "横屏 960x600" },
  ];

  for (const vp of viewports) {
    const page = await browser.newPage({ viewport: { width: vp.w, height: vp.h } });
    await seedEmptyDraft(browser);
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
    const logoCount = await page.locator(".login-card .logo-lockup img").count();
    const logoAlts = await page.locator(".login-card .logo-lockup img").evaluateAll((els) =>
      els.map((e) => e.getAttribute("alt") || ""),
    );
    // 只数元素个数会漏掉「元素存在但尺寸为 0」的情况（曾因此漏掉 logo 不可见的缺陷），
    // 所以这里必须断言真实渲染尺寸。
    const logoBoxes = await page.locator(".login-card .logo-lockup img").evaluateAll((els) =>
      els.map((e) => {
        const r = e.getBoundingClientRect();
        return { w: Math.round(r.width), h: Math.round(r.height) };
      }),
    );
    const logosRendered = logoBoxes.length === 2 && logoBoxes.every((b) => b.w > 20 && b.h > 10);
    const hasFsLogo = logoAlts.some((a) => a.includes("特种设备"));
    const hasFosuLogo = logoAlts.some((a) => a.includes("佛山大学"));
    const loginTitle = (await page.locator(".login-h").innerText()).trim();
    const loginSub = (await page.locator(".login-sub").innerText()).trim();
    const loginFoot = (await page.locator(".login-foot").innerText()).trim();
    const placeholders = await page
      .locator(".login-card .form-input")
      .evaluateAll((els) => els.map((e) => e.placeholder));
    // 退出系统按钮：保守策略——探针不可用时（本机无 pgrep）仍然显示，
    // 宁可多一个按钮，也不能让操作员被锁在系统里
    const exitBtnCount = await page.locator(".login-x").count();

    // 计算样式断言：确认登录页样式与旧版一致，而不是"看起来差不多"
    const styleFacts = await page.evaluate(() => {
      const card = document.querySelector(".login-card");
      const view = document.querySelector(".login-view");
      const cs = getComputedStyle(card);
      const vs = getComputedStyle(view);
      return {
        radius: cs.borderRadius,
        maxWidth: cs.maxWidth,
        cardBg: cs.backgroundColor,
        viewBg: vs.backgroundImage.slice(0, 40),
        font: cs.fontFamily.slice(0, 16),
      };
    });
    const styleOk =
      styleFacts.radius === "16px" &&
      styleFacts.maxWidth === "340px" &&
      styleFacts.cardBg === "rgb(255, 255, 255)" &&
      styleFacts.viewBg.includes("linear-gradient") &&
      styleFacts.font.includes("Noto Sans SC");

    const loginPageOk =
      splashSeen &&
      styleOk &&
      logosRendered &&
      logoCount === 2 &&
      hasFsLogo &&
      hasFosuLogo &&
      loginTitle === "电梯安全评估系统" &&
      loginSub.includes("请使用您的账号登录") &&
      loginFoot.includes("广东省特种设备检测研究院佛山检测院") &&
      loginFoot.includes("佛山大学") &&
      placeholders.includes("请输入用户名") &&
      placeholders.includes("请输入口令") &&
      // 保守策略：探针不可用时显示退出入口（本机无 pgrep，故为 1）
      exitBtnCount === 1;

    await page.fill(".login-card .form-input[type=text]", USERNAME);
    await page.fill(".login-card .form-input[type=password]", PASSWORD);
    await page.click("button[type=submit]");
    await page.waitForSelector(".items tbody tr", { timeout: 20000 });

    const rows = await page.locator(".items tbody tr").count();
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
    // 未填行的底色必须在填表之前取，否则所有行都已被置为「符合」
    const unfilledBg = await page.evaluate(() => {
      const el = document.querySelector("#row-1-9 td");
      return el ? getComputedStyle(el).backgroundColor : "(无)";
    });

    // 左侧可折叠导航：默认 260px，点折叠按钮收成 50px，再点展开
    const sidebarWidth = () =>
      page.evaluate(() => {
        const el = document.querySelector(".sidebar");
        return el ? Math.round(el.getBoundingClientRect().width) : -1;
      });
    const mainMargin = () =>
      page.evaluate(() => {
        const el = document.querySelector(".main");
        return el ? Math.round(parseFloat(getComputedStyle(el).marginLeft)) : -1;
      });
    // 窄屏（≤900px）侧边栏为 186px，宽屏为 260px
    const sidebarExpandedWidth = vp.w <= 900 ? 186 : 260;
    const sidebarExpanded = await sidebarWidth();
    const mainMarginExpanded = await mainMargin();
    await page.click(".sidebar-toggle");
    await page.waitForTimeout(450);
    const sidebarCollapsed = await sidebarWidth();
    const mainMarginCollapsed = await mainMargin();
    await page.click(".sidebar-toggle");
    await page.waitForTimeout(450);
    const sidebarReopened = await sidebarWidth();
    const sidebarOk =
      sidebarExpanded === sidebarExpandedWidth &&
      mainMarginExpanded === sidebarExpandedWidth &&
      sidebarCollapsed === 50 &&
      mainMarginCollapsed === 50 &&
      sidebarReopened === sidebarExpandedWidth;

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

    // 主题统一性：业务页面的令牌必须与登录页同源（旧版 :root）
    const theme = await page.evaluate(() => {
      const body = getComputedStyle(document.body);
      const sheet = getComputedStyle(document.querySelector(".sheet"));
      const btn = getComputedStyle(document.querySelector(".actionbar .btn"));
      return {
        bg: body.backgroundColor,
        font: body.fontFamily.slice(0, 13),
        sheetRadius: sheet.borderRadius,
        btnRadius: btn.borderRadius,
      };
    });
    const themeOk =
      theme.bg === "rgb(244, 248, 250)" &&
      // 与设计稿一致：白卡 10px、控件 6px（直角风格已否决）
      theme.sheetRadius === "10px" &&
      theme.btnRadius === "6px" &&
      theme.font.includes("Noto Sans SC");

    // 暖色检查：全站不得出现暖色（米 / 褐 / 粉底）。
    // 设计口径是「白色 + 蓝青色」，浅色填充一律用冷中性色。
    // 注意要扫描所有元素的所有颜色属性，只看选出来的几个容器会漏。
    const warmHits = await page.evaluate(() => {
      const isWarm = (s) => {
        const m = String(s).match(/rgba?\((\d+),\s*(\d+),\s*(\d+)/);
        if (!m) return false;
        const [R, G, B] = [+m[1], +m[2], +m[3]];
        // R ≥ G ≥ B 且 R 与 B 有可感差距 → 暖色；上限排除饱和橙红
        // 暖色（米 / 褐）的特征是 G > B；粉色的 G≈B 属于语义红，不算暖色
        return R >= G && G - B >= 2 && R - B >= 4 && R - Math.min(G, B) <= 70;
      };
      const hits = [];
      const props = [
        "color",
        "backgroundColor",
        "borderTopColor",
        "borderRightColor",
        "borderBottomColor",
        "borderLeftColor",
      ];
      document.querySelectorAll("*").forEach((el) => {
        const cs = getComputedStyle(el);
        props.forEach((prop) => {
          if (isWarm(cs[prop])) {
            hits.push(
              `${el.tagName.toLowerCase()}.${String(el.className).split(" ")[0]} ${prop}=${cs[prop]}`,
            );
          }
        });
      });
      return [...new Set(hits)];
    });
    const warmOk = warmHits.length === 0;

    // 评价结果行底色规则：
    //   未填 → 白底 ｜ 符合 / 无此项 → 冷浅底 ｜ 不符合 → 红底
    // 此时 1.9 未填、1.11 为符合、2.1 为不符合（上面的填表步骤已设定）
    const rowColors = await page.evaluate(() => {
      const bg = (sel) => {
        const el = document.querySelector(sel);
        return el ? getComputedStyle(el).backgroundColor : "(无)";
      };
      return {
        unfilled: "(已在上方取)",
        done: bg("#row-1-11 td"),
        unfit: bg("#row-2-1 td"),
      };
    });
    rowColors.unfilled = unfilledBg;
    const isWhite = (c) => c === "rgba(0, 0, 0, 0)" || c === "rgb(255, 255, 255)";
    const rowColorOk =
      isWhite(rowColors.unfilled) &&
      rowColors.done === "rgb(246, 248, 250)" &&
      rowColors.unfit === "rgb(254, 240, 240)";

    // 字段名（委托单位名称 等）必须使用黑体
    const labelFont = await page.evaluate(() => {
      const el = document.querySelector(".info th");
      return el ? getComputedStyle(el).fontFamily : "";
    });
    const labelFontOk = /黑体|SimHei/.test(labelFont);

    // 条款编号（a) b) 1) …）只在模板里存在，录入页与报告里都不该出现。
    // 数据源保持原文，归一化在前端，所以这里必须按渲染结果断言。
    const clauseLeak = await page.evaluate(() => {
      const marked = (s) => /^\s*[A-Za-z0-9]{1,2}[)）]/.test(s || "");
      const bad = [];
      document.querySelectorAll(".items tbody tr .item-req div").forEach((d) => {
        if (marked(d.textContent)) bad.push(d.textContent.trim().slice(0, 30));
      });
      // 不符合情形的选项文字同样不能带编号
      document.querySelectorAll(".items tbody tr .reasons .chk span").forEach((s) => {
        if (marked(s.textContent)) bad.push(s.textContent.trim().slice(0, 30));
      });
      return [...new Set(bad)];
    });
    const clauseOk = clauseLeak.length === 0;

    // 窄屏把一行拆成三段后，三态按钮最容易溢出/被裁切，这里固化检查。
    const clipped = await page.evaluate(() => {
      const bad = [];
      document.querySelectorAll(".items tbody tr").forEach((tr) => {
        const seg = tr.querySelector(".seg");
        const cell = tr.querySelector("td:nth-child(4)");
        if (!seg || !cell) return;
        if (seg.getBoundingClientRect().width > cell.clientWidth + 1) {
          bad.push(`${tr.id} 的 seg 超出单元格`);
        }
        seg.querySelectorAll("label").forEach((l) => {
          if (l.scrollWidth > l.clientWidth + 1) bad.push(`${tr.id} 的「${l.textContent}」被裁切`);
        });
      });
      return [...new Set(bad)];
    });
    const clippedOk = clipped.length === 0;

    // 边框线：窄屏适配曾把单元格 border 置 0、只留极浅的 --c-line-soft，
    // 白底上几乎看不见，表现为「线不见了」。这里固化检查线必须存在且用主线色。
    const borderFacts = await page.evaluate(() => {
      const hasLine = (el) => {
        const cs = getComputedStyle(el);
        return ["Top", "Right", "Bottom", "Left"].some(
          (s) => parseFloat(cs["border" + s + "Width"]) > 0,
        );
      };
      const infoCells = [...document.querySelectorAll(".info th, .info td")];
      const itemCells = [...document.querySelectorAll(".items td")];
      const rows = [...document.querySelectorAll(".items tbody tr")];
      const boxed = (el) =>
        ["Top", "Right", "Bottom", "Left"].every(
          (s) => parseFloat(getComputedStyle(el)["border" + s + "Width"]) > 0,
        );
      const faint = [...document.querySelectorAll(".info th, .info td, .items td")]
        .filter((el) => {
          const cs = getComputedStyle(el);
          return ["Top", "Right", "Bottom", "Left"].some(
            (s) =>
              parseFloat(cs["border" + s + "Width"]) > 0 &&
              cs["border" + s + "Color"] === "rgb(224, 234, 239)", // --c-line-soft
          );
        }).length;
      return {
        infoCells: infoCells.length,
        infoLines: infoCells.filter(hasLine).length,
        itemCells: itemCells.length,
        itemLines: itemCells.filter(hasLine).length,
        rows: rows.length,
        boxedRows: rows.filter(boxed).length,
        faint,
      };
    });
    // 窄屏是"卡片式"布局：行自身成框、单元格有内部线；
    // 宽屏是真表格：每个单元格四边都有线（与设计稿一致）。
    const narrow = vp.w <= 900;
    const borderOk =
      borderFacts.faint === 0 &&
      borderFacts.infoLines >= borderFacts.infoCells - 2 &&
      (narrow
        ? borderFacts.boxedRows === borderFacts.rows &&
          borderFacts.itemLines >= Math.ceil(borderFacts.itemCells * 0.7)
        : borderFacts.itemLines === borderFacts.itemCells);

    // 像素级外框检查：表格 + border + overflow:hidden + border-radius 时，
    // 浏览器会把表格自身的边框整条裁掉 —— 计算样式完全看不出来（border 仍是 1px），
    // 只有看像素才发现。这里截一条上边缘，统计"没画线"的比例。
    const edgeGap = async (selector) => {
      const loc = page.locator(selector).first();
      await loc.evaluate((e) => {
        e.scrollIntoView({ block: "start" });
        const sc = e.closest(".main") || document.scrollingElement;
        if (sc) sc.scrollTop -= 80; // 让开 52px 吸顶栏
      });
      await page.waitForTimeout(200);
      const box = await loc.boundingBox();
      if (!box) return 1;
      const clipX = Math.max(0, Math.floor(box.x) - 4);
      const clipY = Math.max(0, Math.floor(box.y) - 4);
      const clipW = Math.min(500, Math.ceil(box.width) + 8);
      const clipH = Math.min(60, Math.ceil(box.height) + 8);
      const b64 = (
        await page.screenshot({ clip: { x: clipX, y: clipY, width: clipW, height: clipH } })
      ).toString("base64");
      return page.evaluate(
        async ({ b64, rect }) => {
          const img = new Image();
          img.src = "data:image/png;base64," + b64;
          await img.decode();
          const cv = document.createElement("canvas");
          cv.width = img.width;
          cv.height = img.height;
          const ctx = cv.getContext("2d");
          ctx.drawImage(img, 0, 0);
          const d = ctx.getImageData(0, 0, cv.width, cv.height).data;
          const W = cv.width;
          const y = Math.round(rect.y);
          let blank = 0;
          let total = 0;
          for (let x = Math.round(rect.x) + 10; x <= Math.round(rect.x + rect.width) - 10; x++) {
            if (x < 0 || x >= cv.width || y < 0 || y >= cv.height) continue;
            const i = (y * W + x) * 4;
            total++;
            if (d[i] > 246 && d[i + 1] > 246 && d[i + 2] > 246) blank++;
          }
          return total ? blank / total : 1;
        },
        {
          b64,
          rect: {
            x: box.x - clipX,
            y: box.y - clipY,
            width: Math.min(box.width, clipW - 8),
          },
        },
      );
    };
    const infoEdgeGap = await edgeGap(".info");
    const itemsEdgeGap = narrow ? 0 : await edgeGap(".items");
    const outlineOk = infoEdgeGap < 0.05 && itemsEdgeGap < 0.05;

    await page.click(".actionbar .btn-primary");
    await page.locator(".paper").first().waitFor({ state: "visible", timeout: 12000 });
    const papers = await page.locator(".paper").count();
    const bodyText = await page.locator(".report-wrap").innerText();
    const overflowReport = await page.evaluate(
      () => document.documentElement.scrollWidth - window.innerWidth,
    );
    // 报告预览里的「评价内容与要求」列也不能带编号
    const reportClauseLeak = await page.evaluate(() => {
      const marked = (s) => /^\s*[A-Za-z0-9]{1,2}[)）]/.test(s || "");
      const bad = [];
      document.querySelectorAll(".paper table td").forEach((td) => {
        td.querySelectorAll("div").forEach((d) => {
          if (marked(d.textContent)) bad.push(d.textContent.trim().slice(0, 30));
        });
      });
      return [...new Set(bad)];
    });
    const reportClauseOk = reportClauseLeak.length === 0;
    const grade4 = bodyText.includes("四级");
    const score0 = bodyText.includes("综合安全状况得分：0");
    const hasAppendix = bodyText.includes("降低风险措施");
    const hasAppendixA = bodyText.includes("附录A");
    const filled = bodyText.includes("44786091");

    // 报告页的导出按钮已移到悬浮岛（底部操作条）
    const exportBtn = page.locator(".actionbar .btn-primary").first();
    const exportBtnText = (await exportBtn.innerText()).trim();
    const exportBtnBg = await exportBtn.evaluate((el) => getComputedStyle(el).backgroundColor);
    const generateBtnGone = (await page.locator(".actionbar").innerText()).includes("校验并生成报告");
    await exportBtn.click();
    await page.waitForTimeout(2500);
    const toast = (await page.locator(".toast").count())
      ? await page.locator(".toast").innerText()
      : "";
    const exportOk = await page.locator(".export-float").count()
      ? await page.locator(".export-float").isVisible().catch(() => false)
      : false;
    const actionbarOk =
      exportBtnText.includes("导出 PDF") && !generateBtnGone && exportBtnBg === "rgb(27, 94, 122)";

    const pass =
      loginPageOk && themeOk && warmOk && rowColorOk && labelFontOk && clauseOk &&
      reportClauseOk && clippedOk && borderOk && outlineOk && sidebarOk && actionbarOk &&
      rows === 66 && overflow <= 0 && alertVisible && alertCount > 0 &&
      focusedId.startsWith("f-") && counters.includes("未填 0 项") &&
      papers === 4 && overflowReport <= 0 && grade4 && score0 &&
      hasAppendix && hasAppendixA && filled &&
      (exportOk || toast.length > 0) && errs.length === 0;
    allOk = allOk && pass;

    console.log(`══ ${vp.label} ══`);
    console.log(`  启动页              ${splashSeen ? "出现" : "未捕获"}`);
    console.log(`  登录页要素          联合logo=${logoCount}（特检院=${hasFsLogo} 佛山大学=${hasFosuLogo}）`);
    console.log(
      `  logo 实际渲染尺寸   ${logoBoxes.map((b) => `${b.w}x${b.h}`).join(" / ")}  ${logosRendered ? "✓ 可见" : "✗ 尺寸异常"}`,
    );
    console.log(`                     标题「${loginTitle}」/「${loginSub}」`);
    console.log(`                     页脚含机构署名=${loginFoot.includes("广东省特种设备检测研究院佛山检测院")}`);
    console.log(`                     退出按钮（非一体机应无）=${exitBtnCount}`);
    console.log(
      `  样式还原            圆角${styleFacts.radius} 最大宽${styleFacts.maxWidth} 卡片底色=${styleFacts.cardBg} 背景=渐变:${styleFacts.viewBg.includes("linear-gradient")} 字体=${styleFacts.font}`,
    );
    console.log(`  条目行数        ${rows}`);
    console.log(
      `  主题统一        底色=${theme.bg} 卡片圆角=${theme.sheetRadius} 按钮圆角=${theme.btnRadius} 字体=${theme.font} ${themeOk ? "✓" : "✗"}`,
    );
    console.log(
      `  暖色(褐/米)残留  ${warmHits.length} 处 ${warmOk ? "✓" : "✗ " + warmHits.slice(0, 3).join(" | ")}`,
    );
    console.log(
      `  行底色规则      未填=${rowColors.unfilled} 符合=${rowColors.done} 不符合=${rowColors.unfit} ${rowColorOk ? "✓" : "✗"}`,
    );
    console.log(`  字段名字体      ${labelFont.slice(0, 34)} ${labelFontOk ? "✓ 黑体" : "✗ 非黑体"}`);
    console.log(
      `  条款编号清理    录入页 ${clauseLeak.length} 处 / 报告页 ${reportClauseLeak.length} 处 ${clauseOk && reportClauseOk ? "✓" : "✗ " + [...clauseLeak, ...reportClauseLeak].slice(0, 3).join(" | ")}`,
    );
    console.log(
      `  窄屏三态按钮    溢出/裁切 ${clipped.length} 处 ${clippedOk ? "✓" : "✗ " + clipped.slice(0, 3).join(" | ")}`,
    );
    console.log(
      `  边框线          信息表 ${borderFacts.infoLines}/${borderFacts.infoCells} · 条目行成框 ${borderFacts.boxedRows}/${borderFacts.rows} · 条目单元格 ${borderFacts.itemLines}/${borderFacts.itemCells} · 极浅线 ${borderFacts.faint} ${borderOk ? "✓" : "✗"}`,
    );
    console.log(
      `  外框像素        上边缘缺线 信息表 ${(infoEdgeGap * 100).toFixed(1)}% · 条目表 ${narrow ? "(窄屏无整表外框)" : (itemsEdgeGap * 100).toFixed(1) + "%"} ${outlineOk ? "✓" : "✗"}`,
    );
    console.log(
      `  侧边栏          展开=${sidebarExpanded}/${mainMarginExpanded} 折叠=${sidebarCollapsed}/${mainMarginCollapsed} 再展开=${sidebarReopened} ${sidebarOk ? "✓" : "✗"}`,
    );
    console.log(`  横向溢出        主页面 ${overflow} px / 报告页 ${overflowReport} px`);
    console.log(`  必填拦截        ${alertVisible}，清单 ${alertCount} 条`);
    console.log(`  跳转定位        ${focusedId}`);
    console.log(`  计数栏          ${counters}`);
    console.log(`  报告页数        ${papers}`);
    console.log(`  内容校验        四级=${grade4} 得分0=${score0} 附页=${hasAppendix} 附录A=${hasAppendixA} 抬头=${filled}`);
    console.log(`  导出            ${exportOk ? "成功" : "失败可见 → " + toast.slice(0, 70)}`);
    console.log(
      `  悬浮岛按钮      「${exportBtnText}」底色=${exportBtnBg} 已移除校验并生成报告=${!generateBtnGone} ${actionbarOk ? "✓" : "✗"}`,
    );
    console.log(`  页面错误        ${errs.length}${errs.length ? " " + errs.slice(0, 3).join(" | ") : ""}`);
    console.log(`  结论            ${pass ? "通过" : "未通过"}`);
    await page.close();
  }

  // ── 启动兜底回归 ─────────────────────────────────────────────────
  // 前端资源加载失败时页面曾变成"一片纯背景色、没有任何文字"（实测复现）。
  // 这里让入口 JS 请求失败，断言必须出现可读的提示面板与「重新加载」出口。
  {
    const page = await browser.newPage({ viewport: { width: 1364, height: 653 } });
    await page.route("**/assets/index-*.js", (r) => r.abort());
    await page.route("**/assets/LoginView-*.js", (r) => r.abort());
    await page.route("**/assets/ReportView-*.js", (r) => r.abort());
    await page.goto(BASE + "/#/login", { waitUntil: "load" });
    const panelShown = await page
      .waitForSelector("#boot-fallback:not([hidden])", { timeout: 12000 })
      .then(() => true)
      .catch(() => false);
    const panelText = (await page.locator("#boot-fallback").innerText().catch(() => ""))
      .replace(/\s+/g, " ")
      .trim();
    const bootOk =
      panelShown &&
      panelText.includes("系统未能启动") &&
      panelText.includes("重新加载") &&
      panelText.length > 20;
    console.log("══ 启动兜底（入口资源加载失败）══");
    console.log(`  提示面板        ${panelShown ? "出现" : "未出现"}`);
    console.log(`  文案            ${panelText.slice(0, 60)}`);
    console.log(`  结论            ${bootOk ? "通过（不是空白页）" : "未通过"}`);
    allOk = allOk && bootOk;
    await page.close();
  }

  await browser.close();
  console.log();
  console.log(allOk ? "全部通过（含两个视口与启动兜底）" : "存在未通过项");
  process.exit(allOk ? 0 : 1);
})();
