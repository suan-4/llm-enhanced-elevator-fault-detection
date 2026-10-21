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
      await page.locator('.items tbody tr').first().waitFor();
      const token = await page.evaluate(() => localStorage.getItem('elevator_token'));
      const headers = { Authorization: `Bearer ${token}` };
      const catalog = (await (await context.request.get(BASE+'/api/report/jte-items', { headers })).json()).items;
      const created = await context.request.post(BASE+'/api/reports', { headers, data: {} });
      const draft = (await created.json()).report;
      const saved = await context.request.put(BASE+'/api/reports/'+draft.id, { headers, data: {
        version: draft.version,
        form: { clientName: '浏览器导出验收', userName: '独立测试数据', deviceCategory: '曳引驱动电梯',
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
      assert.equal(await page.getByRole('button', { name: '保存草稿', exact: true }).isDisabled(), true);
      const status = (await (await context.request.get(BASE+`/api/reports/${draft.id}`, { headers })).json()).report;
      assert.equal(status.status, 'filed');
      assert.equal(status.files.length, 1);
      assert.match(status.files[0].sha256, /^[0-9a-f]{64}$/);
      const geom = await page.locator('.export-float').boundingBox();
      assert(geom.x >= 0 && geom.x + geom.width <= viewport.width + 1);
      await page.screenshot({ path: path.join(OUT, `archived-${viewport.width}.png`), fullPage: false });
      await page.getByRole('button', { name: '＋ 新建评估', exact: true }).click();
      const dialog = page.locator('.dialog-mask');
      await dialog.getByRole('button', { name: '新建', exact: true }).click();
      await page.waitForFunction(() => {
        const el = document.querySelector('#f-clientName');
        return el && el.value === '' && !el.disabled;
      });
      assert.equal(errors.length, 0, errors.join('\n'));
      results.push({ viewport, responseLost: viewport.width === 600, archived: true,
        newAssessment: true, pageErrors: errors, file: status.files[0] });
      await context.close();
    }
    fs.writeFileSync(path.join(OUT, 'results.json'), JSON.stringify(results, null, 2));
    console.log(JSON.stringify(results, null, 2));
  } finally { await browser.close(); }
})().catch(e => { console.error(e); process.exitCode = 1; });
