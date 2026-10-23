/* Verify the approved one-screen entry form and persisted new-report defaults. */
const assert = require('assert/strict')
const fs = require('fs')
const path = require('path')
const { chromium } = require('C:/Users/何/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright')
const BASE = process.env.BASE || 'http://127.0.0.1:8087'
if (!/^http:\/\/127\.0\.0\.1:(8087|18087)$/.test(BASE)) throw Error('Isolated acceptance server only')
const OUT = path.resolve(__dirname, '../../output/playwright/home')
fs.mkdirSync(OUT, { recursive: true })
;(async () => {
  const browser = await chromium.launch({ executablePath: 'C:/Users/何/AppData/Local/ms-playwright/chromium-1228/chrome-win64/chrome.exe' })
  const results = []
  try {
    for (const viewport of [{ width: 600, height: 960 }, { width: 1200, height: 1920 }]) {
      const context = await browser.newContext({ viewport })
      const page = await context.newPage()
      const errors = []
      page.on('pageerror', error => errors.push(error.message))
      // The desktop has no IME service; render the actual board-only button as well.
      let imeLabel = '英'
      await page.route('**/api/ime/status', route => route.fulfill({ json: { available: true, label: imeLabel } }))
      await page.route('**/api/ime/toggle', route => {
        imeLabel = imeLabel === '英' ? '中' : '英'
        return route.fulfill({ json: { available: true, label: imeLabel } })
      })
      await page.goto(BASE + '/#/login')
      await page.locator('.login-card .form-input[type=text]').fill('acceptance')
      await page.locator('.login-card .form-input[type=password]').fill('Acceptance2026!')
      await page.locator('button[type=submit]').click()
      await page.locator('.group-toggle').first().waitFor()
      assert.equal(await page.locator('.group-toggle[aria-expanded="true"]').count(), 0, 'Project groups initially stay collapsed')
      await page.locator('.group-toggle').first().click()
      assert.equal(await page.locator('.group-toggle').first().getAttribute('aria-expanded'), 'true')
      await page.getByRole('button', { name: '＋ 新建评估', exact: true }).click()
      await page.locator('.dialog-mask').getByRole('button', { name: '新建', exact: true }).click()
      await page.waitForFunction(() => document.querySelector('.toast')?.textContent.includes('已新建'))
      assert.equal(await page.locator('.group-toggle[aria-expanded="true"]').count(), 0, 'New assessment resets group expansion')
      await page.waitForFunction(() => document.querySelector('.sidebar').getBoundingClientRect().width <= 51 || innerWidth > 900)
      const token = await page.evaluate(() => localStorage.getItem('elevator_token'))
      const snapshot = await page.evaluate(() => {
        const store = document.querySelector('#app').__vue_app__.config.globalProperties.$pinia._s.get('report')
        document.querySelector('.main').scrollTop = 0
        return { id: store.reportId, results: store.items.map(i => store.stateOf(i.no).result) }
      })
      const persisted = (await (await context.request.get(BASE + '/api/reports/' + snapshot.id, { headers: { Authorization: 'Bearer ' + token } })).json()).report
      assert.equal(snapshot.results.length, 66)
      assert(snapshot.results.every(value => value === '符合'))
      assert.equal(persisted.items.length, 66)
      assert(persisted.items.every(item => item.result === 'fit'))
      await page.reload()
      await page.locator('.group-toggle').first().waitFor()
      assert.equal(await page.locator('.group-toggle[aria-expanded="true"]').count(), 0, 'Reload keeps the initial collapsed layout')
      assert.match(await page.locator('.draft-origin').innerText(), /已恢复上次草稿/)
      await page.evaluate(() => { document.querySelector('.main').scrollTop = 0 })
      const metrics = await page.evaluate(() => {
        const table = document.querySelector('#sec-info .info')
        const rect = table.getBoundingClientRect()
        const bar = document.querySelector('.actionbar').getBoundingClientRect()
        const settings = document.querySelector('.settings-fab').getBoundingClientRect()
        const ime = document.querySelector('.ime-toggle').getBoundingClientRect()
        const brand = document.querySelector('.brand').getBoundingClientRect()
        const fields = [...table.querySelectorAll('input')]
        return { tableTop: rect.top, tableBottom: rect.bottom, tableHeight: rect.height,
          actionbarTop: bar.top, viewportHeight: innerHeight,
          settingsCoversTable: settings.left < rect.right && settings.right > rect.left && settings.top < rect.bottom && settings.bottom > rect.top,
          settingsOverlapsIme: settings.left < ime.right && settings.right > ime.left && settings.top < ime.bottom && settings.bottom > ime.top,
          imeGap: ime.left - settings.right,
          settingsOverlapsBrand: settings.left < brand.right && settings.right > brand.left && settings.top < brand.bottom && settings.bottom > brand.top,
          cellDisplay: getComputedStyle(table.querySelector('td')).display,
          tableDisplay: getComputedStyle(table).display,
          rowDisplay: getComputedStyle(table.rows[0]).display,
          rowHeights: [...table.rows].map(row => [row.cells[0]?.textContent.trim().slice(0, 14), row.getBoundingClientRect().height]),
          sectionBarHeight: document.querySelector('.section-bar').getBoundingClientRect().height,
          cellStyles: [table.rows[0].cells[1], table.rows[9].cells[1], table.rows[18].cells[0]].map(cell => {
            const s = getComputedStyle(cell)
            return { width: cell.getBoundingClientRect().width, font: s.font, whiteSpace: s.whiteSpace,
              padding: s.padding, text: cell.textContent.trim() }
          }),
          fields: fields.length, fitsFirstScreen: rect.top >= 0 && rect.bottom <= bar.top,
          outsideInputs: fields.filter(field => {
            const f = field.getBoundingClientRect(), cell = field.closest('td').getBoundingClientRect()
            return f.left < cell.left - 1 || f.right > cell.right + 1
          }).map(field => field.id) }
      })
      const result = { viewport, collapsedGroups: await page.locator('.group-toggle[aria-expanded="false"]').count(), newDefaultFit: snapshot.results.length, storedDefaultFit: persisted.items.length, metrics, pageErrors: errors }
      results.push(result)
      console.log(JSON.stringify(result))
      await page.screenshot({ path: path.join(OUT, `home-${viewport.width}.png`) })
      assert(metrics.fitsFirstScreen, 'The complete information table must fit above the actionbar')
      assert.equal(metrics.settingsCoversTable, false, 'Settings must not cover the information table')
      assert.equal(metrics.settingsOverlapsIme, false, 'Settings must not overlap the board IME switch')
      assert.equal(metrics.settingsOverlapsBrand, false, 'Settings must not cover the title or logo')
      if (viewport.width <= 900) assert(metrics.imeGap >= 12, 'Keep a touch gap between settings and IME')
      assert.equal(metrics.cellDisplay, 'table-cell')
      assert.equal(metrics.tableDisplay, 'table')
      assert.equal(metrics.rowDisplay, 'table-row')
      assert.deepEqual(metrics.outsideInputs, [])
      await page.locator('.ime-toggle').click()
      await page.waitForFunction(() => document.querySelector('.ime-toggle')?.textContent.trim() === '中')
      await page.locator('.ime-toggle').click()
      await page.waitForFunction(() => document.querySelector('.ime-toggle')?.textContent.trim() === '英')
      await page.locator('.settings-fab').click()
      await page.waitForURL('**/#/settings')
      await page.locator('.config-save').waitFor()
      result.imeSwitchClickable = true
      result.settingsClickable = true
      assert.deepEqual(errors, [])
      await context.close()
    }
  } finally {
    fs.writeFileSync(path.join(OUT, 'results.json'), JSON.stringify(results, null, 2))
    await browser.close()
  }
})().catch(error => { console.error(error); process.exitCode = 1 })
