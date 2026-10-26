/* Real Vue/handwriting worker, isolated business DB only. Voice transport is controlled. */
const assert = require('assert/strict')
const fs = require('fs')
const path = require('path')
const { chromium } = require('C:/Users/何/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright')
const BASE = process.env.BASE || 'http://127.0.0.1:8087'
if (!/^http:\/\/127\.0\.0\.1:(8087|18087)$/.test(BASE)) throw Error('Isolated input server only')
const OUT = path.resolve(__dirname, '../../output/terminal-ui-acceptance/keyboard')
fs.mkdirSync(OUT, { recursive: true })
;(async () => {
  const browser = await chromium.launch({ executablePath: 'C:/Users/何/AppData/Local/ms-playwright/chromium-1228/chrome-win64/chrome.exe' })
  const results = []
  try {
    for (const viewport of [{ width: 600, height: 960 }, { width: 960, height: 600 }]) {
      const page = await browser.newPage({ viewport })
      const errors = [], external = []
      let canceled = 0
      page.on('pageerror', error => errors.push(error.message))
      page.on('request', req => { if (!req.url().startsWith(BASE) && !req.url().startsWith('blob:') && !req.url().startsWith('data:')) external.push(req.url()) })
      await page.route('**/api/input/**', async route => {
        const url = new URL(route.request().url())
        if (url.pathname.endsWith('/status')) return route.fulfill({ json: { keyboard: true, pinyin: true, voice: true, offline: true } })
        if (url.pathname.endsWith('/pinyin')) {
          if (process.env.REAL_IME === '1') return route.continue()
          const actions = route.request().postDataJSON().actions
          return route.fulfill({ json: { candidates: actions.some(a => a.candidate) ? [] : ['制动器', '制动'], committed: actions.some(a => a.candidate) ? '制动器' : '', has_next: false } })
        }
        if (url.pathname.endsWith('/voice/start')) return route.fulfill({ json: { id: 'a'.repeat(32), max_seconds: 30 } })
        if (url.pathname.endsWith('/voice/stop')) return route.fulfill({ json: { text: '制动器未完全打开', duration_seconds: 3, recognition_ms: 300 } })
        if (url.pathname.endsWith('/voice/cancel')) { canceled++; return route.fulfill({ json: { success: true } }) }
        return route.continue()
      })
      await page.goto(BASE + '/#/login')
      const username = page.locator('.login-card input[type=text]')
      await username.fill('acceptance')
      const password = page.locator('.login-card input[type=password]')
      await password.fill('Acceptance2026!')
      const panel = page.locator('[data-offline-keyboard]')
      await panel.waitFor()
      assert(await panel.getByRole('button', { name: '手写', exact: true }).isDisabled())
      assert(await panel.getByRole('button', { name: '语音', exact: true }).isDisabled())
      await page.waitForTimeout(100)
      assert((await password.boundingBox()).y + (await password.boundingBox()).height <= (await panel.boundingBox()).y, 'Focused login field stays above keyboard')
      await panel.getByRole('button', { name: '收起键盘', exact: true }).click()
      await page.locator('button[type=submit]').click()
      await page.locator('#f-clientName').waitFor()
      const field = page.locator('#f-clientName')
      await field.fill('')
      await panel.waitFor()
      for (const letter of 'zhidongqi') await panel.locator('.keyboard-rows').getByRole('button', { name: letter, exact: true }).click()
      await panel.locator('.keyboard-candidates').getByRole('button', { name: '制动器', exact: true }).click()
      await page.waitForFunction(() => document.querySelector('#f-clientName').value === '制动器')
      await page.screenshot({ path: path.join(OUT, `keyboard-${viewport.width}.png`) })
      await field.evaluate(el => { el.setSelectionRange(1, 2); document.dispatchEvent(new Event('selectionchange')) })
      await panel.locator('.keyboard-bottom').getByRole('button', { name: '中', exact: true }).click()
      await panel.locator('.keyboard-rows').getByRole('button', { name: 'a', exact: true }).click()
      assert.equal(await field.inputValue(), '制a器')
      await panel.getByRole('button', { name: '手写', exact: true }).click()
      const canvas = panel.locator('canvas'), box = await canvas.boundingBox()
      async function stroke(points) {
        await page.mouse.move(box.x + points[0][0] * box.width, box.y + points[0][1] * box.height)
        await page.mouse.down()
        for (const p of points.slice(1)) await page.mouse.move(box.x + p[0] * box.width, box.y + p[1] * box.height, { steps: 10 })
        await page.mouse.up()
      }
      await stroke([[.2, .45], [.8, .45]])
      await stroke([[.5, .15], [.5, .85]])
      const ten = panel.locator('.handwriting-candidates').getByRole('button', { name: '十', exact: true })
      await ten.waitFor()
      await page.screenshot({ path: path.join(OUT, `handwriting-${viewport.width}.png`) })
      await ten.click()
      assert((await field.inputValue()).includes('十'))
      await panel.getByRole('button', { name: '语音', exact: true }).click()
      const beforeVoice = await field.inputValue()
      await panel.getByRole('button', { name: '开始语音输入', exact: true }).click()
      await panel.getByRole('button', { name: '停止录音并识别', exact: true }).click()
      await panel.locator('.voice-result').waitFor()
      assert.equal(await field.inputValue(), beforeVoice, 'Speech must wait for explicit insertion')
      await page.screenshot({ path: path.join(OUT, `voice-${viewport.width}.png`) })
      await panel.getByRole('button', { name: '填入文字', exact: true }).click()
      assert((await field.inputValue()).includes('制动器未完全打开'))
      await panel.getByRole('button', { name: '语音', exact: true }).click()
      await panel.getByRole('button', { name: '开始语音输入', exact: true }).click()
      await panel.getByRole('button', { name: '停止录音并识别', exact: true }).waitFor()
      await page.locator('#f-userName').focus()
      await page.waitForTimeout(150)
      assert.equal(canceled, 1, 'Changing target must cancel microphone recording')
      const numeric = page.locator('#f-ratedLoad')
      await numeric.fill('')
      await panel.getByRole('button', { name: '1', exact: true }).click()
      assert.equal(await numeric.inputValue(), '1')
      const metrics = await panel.evaluate(el => {
        const r = el.getBoundingClientRect(), keys = [...el.querySelectorAll('.key')]
        return { left: r.left, right: r.right, bottom: r.bottom, height: r.height,
          viewport: [innerWidth, innerHeight], minKeyHeight: Math.min(...keys.map(k => k.getBoundingClientRect().height)) }
      })
      assert(metrics.left >= 0 && metrics.right <= viewport.width && metrics.bottom <= viewport.height)
      assert(metrics.minKeyHeight >= 40)
      await panel.getByRole('button', { name: '收起键盘', exact: true }).click()
      await panel.waitFor({ state: 'hidden' })
      assert.deepEqual(errors, [])
      assert.deepEqual(external, [])
      results.push({ viewport, pinyin: true, handwriting: true, speechConfirmation: true, recordingCanceled: canceled, metrics, errors, external })
      await page.close()
    }
    fs.writeFileSync(path.join(OUT, 'browser-results.json'), JSON.stringify(results, null, 2))
    console.log(JSON.stringify(results))
  } finally { await browser.close() }
})().catch(error => { console.error(error); process.exit(1) })
