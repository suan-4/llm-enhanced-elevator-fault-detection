/* PR #2 browser regressions: disposable localhost server only. */
const assert = require('assert/strict')
const fs = require('fs')
const path = require('path')
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'C:/Users/何/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright')
const BASE = process.env.BASE || 'http://127.0.0.1:8094'
if (!/^http:\/\/127\.0\.0\.1:(8094|18094|18087)$/.test(BASE)) throw new Error('disposable PR2 server only')
const OUT = path.resolve('output/playwright/pr2-fixes')
fs.mkdirSync(OUT, { recursive: true })

;(async () => {
  const browser = await chromium.launch({ executablePath: process.env.CHROMIUM_EXE || 'C:/Users/何/AppData/Local/ms-playwright/chromium-1228/chrome-win64/chrome.exe' })
  const results = []
  try {
    for (const viewport of [{ width: 600, height: 960 }, { width: 1200, height: 1920 }]) {
      const page = await browser.newPage({ viewport })
      const errors = []
      page.on('pageerror', e => errors.push(e.message))
      await page.goto(BASE + '/#/login')
      await page.locator('.login-card .form-input[type=text]').fill(process.env.ELEVATOR_USER || 'reviewer')
      await page.locator('.login-card .form-input[type=password]').fill(process.env.ELEVATOR_PASSWORD || 'Review2026!')
      await page.locator('button[type=submit]').click()
      await page.locator('.group-toggle').first().waitFor()
      assert.equal(await page.locator('.group-toggle').count(), 17)

      const no = await page.evaluate(() => {
        const store = document.querySelector('#app').__vue_app__.config.globalProperties.$pinia._s.get('report')
        store.hydrate({ form: { clientName: 'PR2验收委托', userName: 'PR2验收使用', deviceVariety: '曳引驱动乘客电梯', productNo: 'FIX-PR2' },
          version: store.version, status: 'draft', items: store.items.map((i, index) => ({ no: i.no,
            result: index === 0 ? 'unfit' : 'fit', reasons: [], other_text: '' })) })
        return store.items[0].no
      })
      await page.locator('.group-toggle').first().click()
      const row = page.locator('#row-' + no.replace('.', '-'))
      assert.equal(await row.count(), 0)
      await page.getByRole('button', { name: '校验并生成报告', exact: true }).click()
      await row.waitFor({ state: 'visible' })
      assert.equal(await page.locator('.group-toggle').first().getAttribute('aria-expanded'), 'true')
      assert.match(await row.getAttribute('class'), /row-mark/)

      await page.evaluate(() => {
        const store = document.querySelector('#app').__vue_app__.config.globalProperties.$pinia._s.get('report')
        store.saveBaseInfoProfile('PR2 持久化验收')
      })
      await page.getByRole('button', { name: '＋ 新建评估', exact: true }).click()
      await page.locator('.dialog-mask').getByRole('button', { name: '新建', exact: true }).click()
      await page.waitForFunction(() => document.querySelector('.toast')?.textContent.includes('已新建'))
      assert.equal(await page.locator('#f-clientName').inputValue(), 'PR2验收委托')
      await page.reload()
      await page.locator('#f-clientName').waitFor()
      assert.equal(await page.locator('#f-clientName').inputValue(), 'PR2验收委托')

      // Exercise the visible failure path, not only the store's return value.
      await page.getByRole('button', { name: '保存新方案…', exact: true }).click()
      await page.locator('.baseinfo-name').fill('不应误报保存成功')
      await page.evaluate(() => {
        window.__originalStorageSet = Storage.prototype.setItem
        Storage.prototype.setItem = () => { throw new DOMException('quota exceeded', 'QuotaExceededError') }
      })
      await page.locator('.dialog-mask').getByRole('button', { name: '保存', exact: true }).click()
      assert.match(await page.locator('.toast').innerText(), /无法保存/)
      assert.equal(await page.locator('.dialog-mask').isVisible(), true)
      await page.evaluate(() => { Storage.prototype.setItem = window.__originalStorageSet })
      await page.locator('.dialog-mask').getByRole('button', { name: '取消', exact: true }).click()

      await page.locator('.settings-fab').click()
      await page.locator('.config-save').waitFor()
      const apiChecks = await page.evaluate(async () => {
        const key = Object.keys(localStorage).find(k => /token/i.test(k))
        const headers = { Authorization: 'Bearer ' + localStorage.getItem(key), 'Content-Type': 'application/json' }
        const get = () => fetch('/api/system/config', { headers }).then(r => r.json())
        const before = await get()
        const original = before.items.find(i => i.key === 'institution_name').value
        const originalDir = before.items.find(i => i.key === 'export_dir').value
        const invalid = await fetch('/api/system/config', { method: 'PUT', headers, body: JSON.stringify({ values: { export_dir: '/' } }) })
        const rejected = invalid.status
        const afterInvalid = await get()
        const unchanged = afterInvalid.items.find(i => i.key === 'export_dir').value === originalDir
        const valid = await fetch('/api/system/config', { method: 'PUT', headers,
          body: JSON.stringify({ values: { institution_name: 'PR2 配置验证' } }) })
        const after = await get()
        const saved = after.items.find(i => i.key === 'institution_name').value === 'PR2 配置验证'
        await fetch('/api/system/config', { method: 'PUT', headers, body: JSON.stringify({ values: { institution_name: original } }) })
        return { rejected, unchanged, saved, saveStatus: valid.status }
      })
      assert.deepEqual(apiChecks, { rejected: 400, unchanged: true, saved: true, saveStatus: 200 })
      await page.screenshot({ path: path.join(OUT, `settings-${viewport.width}.png`) })
      assert.deepEqual(errors, [])
      results.push({ viewport, groups: 17, missingItemExpanded: true, copiedFormSurvivesRefresh: true,
        profileStorageFailureVisible: true, apiChecks, errors })
      await page.close()
    }
    fs.writeFileSync(path.join(OUT, 'results.json'), JSON.stringify(results, null, 2))
    console.log(JSON.stringify(results, null, 2))
  } finally { await browser.close() }
})().catch(e => { console.error(e); process.exitCode = 1 })
