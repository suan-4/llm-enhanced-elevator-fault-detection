/**
 * 清理 dist 里过期的历史构建产物。
 *
 * 背景：vite.config.ts 里 emptyOutDir 被显式关掉了。因为浏览器或一体机
 * WebView 可能还停在上一版 index.html 上，它引用的 hash 文件一旦被清掉，
 * 页面就会变成整片空白而且没有任何提示（实测已复现）。
 * 代价是产物会累积，所以这里按时间清理：
 *   - 当前 index.html 引用到的文件永不删；
 *   - 其余保留最近 KEEP_DAYS 天（给"页面停留期间系统更新"留出重载窗口）。
 *
 * 用法：npm run build 会自动调用（见 package.json）。
 */
import { readFileSync, readdirSync, statSync, rmSync, existsSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const KEEP_DAYS = 14
const webDir = dirname(dirname(fileURLToPath(import.meta.url)))
const distDir = join(webDir, 'dist')
const assetsDir = join(distDir, 'assets')
const indexPath = join(distDir, 'index.html')

if (!existsSync(assetsDir) || !existsSync(indexPath)) {
  console.log('[prune] 跳过：dist 尚未构建')
  process.exit(0)
}

const indexHtml = readFileSync(indexPath, 'utf8')
const cutoff = Date.now() - KEEP_DAYS * 24 * 60 * 60 * 1000
let removed = 0
let kept = 0

for (const name of readdirSync(assetsDir)) {
  const file = join(assetsDir, name)
  if (indexHtml.includes(name)) {
    kept++
    continue
  }
  if (statSync(file).mtimeMs > cutoff) {
    kept++
    continue
  }
  rmSync(file, { force: true })
  removed++
}

console.log(`[prune] 保留 ${kept} 个，清理 ${removed} 个（>${KEEP_DAYS} 天且当前未引用）`)
