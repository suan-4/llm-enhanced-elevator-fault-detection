/* Real-browser export/archive/lost-response regression. Disposable server only. */
const fs = require('fs');
const path = require('path');
const assert = require('assert/strict');
const { chromium } = require(process.env.PLAYWRIGHT_MODULE ||
  'C:/Users/何/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const BASE = process.env.BASE || 'http://127.0.0.1:8087';
if (!/^http:\/\/127\.0\.0\.1:(8087|18087)$/.test(BASE)) throw new Error('isolated test server only');
const OUT = path.resolve('output/playwright/native-export');
fs.mkdirSync(OUT, { recursive: true });

(async () => {
  const browser = await chromium.launch({
    executablePath: process.env.CHROMIUM_EXE ||
      'C:/Users/何/AppData/Local/ms-playwright/chromium-1228/chrome-win64/chrome.exe',
  });
  const results = [];
  try {
    for (const viewport of [{ width: 600, height: 960 }, { width: 1200, height: 1920 }]) {
      const context = await browser.newContext({ viewport });
      const page = await context.newPage();
      const errors = [];
      page.on('pageerror', e => errors.push(e.message));
      await page.goto(BASE + '/#/login');
      await page.locator('.login-card .form-input[type=text]').fill('acceptance');
      await page.locator('.login-card .form-input[type=password]').fill('Acceptance2026!');
      await page.locator('button[type=submit]').click();
      await page.locator('.group-toggle').first().waitFor();
      const token = await page.evaluate(() => localStorage.getItem('elevator_token'));
      const headers = { Authorization: `Bearer ${token}` };
      const catalog = (await (await context.request.get(BASE+'/api/report/jte-items', { headers })).json()).items;
      const created = await context.request.post(BASE+'/api/reports', { headers, data: {} });
      const draft = (await created.json()).report;
      const saved = await context.request.put(BASE+'/api/reports/'+draft.id, { headers, data: {
        version: draft.version,
        form: { clientName: '浏览器导出验收', userName: '独立测试数据', deviceCategory: '/',
          deviceVariety: '曳引驱动乘客电梯', floors: '10', stops: '', doors: '12',
          ratedLoad: '1000', ratedSpeed: '1.75',
          productNo: 'BROWSER-'+viewport.width, instruments: '/', basis: '/' },
        items: catalog.map(i => ({ no: i.no, result: 'fit', reasons: [], other_text: '' })),
      }});
      assert.equal(saved.status(), 200);
      const generated = await context.request.post(BASE+`/api/reports/${draft.id}/generate`, {
        headers, data: { use_llm: false },
      });
      assert.equal(generated.status(), 200);
      const report = (await generated.json()).report;
      await page.goto(BASE+'/#/reports');
      const row = page.locator('tbody tr').filter({ hasText: report.report_no });
      await row.getByRole('button', { name: '查看', exact: true }).click();
      await page.getByRole('button', { name: '导出 Word', exact: true }).waitFor();
      assert.equal(await page.locator('.report-viewer').count(), 1);
      assert.equal(await page.locator('.viewer-back').count(), 1);
      assert.equal(await page.locator('.report-cover').count(), 1);
      assert.equal(await page.locator('.report-notice').count(), 1);
      assert.equal(await page.locator('.paper-holder').count(), 6);
      // 查看页不渲染录入表单，也没有「保存草稿」这类置灰按钮
      assert.equal(await page.locator('#f-clientName').count(), 0);
      assert.equal(await page.getByRole('button', { name: '保存草稿', exact: true }).count(), 0);
      await page.waitForFunction(() => {
        const buttons = [...document.querySelectorAll('.viewer-actions button')].filter(b => !b.disabled);
        return buttons.every((b, i) => buttons.every((other, j) => {
          if (i === j) return true;
          const a = b.getBoundingClientRect(), c = other.getBoundingClientRect();
          return a.right <= c.left + 1 || c.right <= a.left + 1 || a.bottom <= c.top + 1 || c.bottom <= a.top + 1;
        }));
      });
      // Forward the real request, let the server commit, then lose its response.
      // Only the first viewport injects the fault; second verifies normal response.
      if (viewport.width === 600) {
        await page.route('**/api/report/export', async route => {
          const response = await route.fetch();
          assert.equal(response.status(), 200);
          await route.abort('connectionreset');
        }, { times: 1 });
      }
      await page.getByRole('button', { name: '导出 Word', exact: true }).click();
      await page.locator('.export-float').waitFor({ timeout: 30000 });
      const status = (await (await context.request.get(BASE+`/api/reports/${draft.id}`, { headers })).json()).report;
      assert.equal(status.status, 'filed');
      assert.equal(status.files.length, 1);
      assert.match(status.files[0].sha256, /^[0-9a-f]{64}$/);
      const geom = await page.locator('.export-float').boundingBox();
      assert(geom.x >= 0 && geom.x + geom.width <= viewport.width + 1);
      await page.screenshot({ path: path.join(OUT, `archived-viewer-${viewport.width}.png`), fullPage: false });
      // 「返回评估填写」：回到可编辑的录入现场，不再是只读表单
      await page.locator('.export-float .close').click();
      // 查看页返回按钮回报告管理列表；再点侧栏「检测项目填写」恢复录入现场
      await page.locator('.viewer-back').click();
      await page.waitForSelector('.data-table', { timeout: 15000 });
      await page.locator('.sidebar-nav li[data-anchor="items"]').click();
      await page.locator('.group-toggle').first().waitFor({ timeout: 15000 });
      await page.waitForFunction(() => {
        const el = document.querySelector('#f-clientName');
        return el && !el.disabled;
      });
      assert.equal(await page.locator('#f-clientName').isEditable(), true);
      assert.equal(errors.length, 0, errors.join('\n'));
      results.push({ viewport, responseLost: viewport.width === 600, archived: true,
        coverAndNotice: true, previewPages: 6, nonOverlappingActions: true,
        standaloneViewer: true, backToEditableEditor: true, pageErrors: errors, file: status.files[0] });
      await context.close();
    }
    fs.writeFileSync(path.join(OUT, 'results.json'), JSON.stringify(results, null, 2));
    console.log(JSON.stringify(results, null, 2));
  } finally { await browser.close(); }
})().catch(e => { console.error(e); process.exitCode = 1; });
