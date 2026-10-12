import { fileURLToPath, URL } from 'node:url'
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// 构建产物推送到板端 /home/ubuntu/elevator/web/dist，
// 由 FastAPI 挂载 /assets 与 / 提供静态服务。
export default defineConfig({
  base: '/',
  plugins: [vue()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  build: {
    outDir: 'dist',
    // 必须保留历史产物：浏览器/一体机可能仍停在上一版 index.html 上，
    // 它引用的 hash 文件若被清掉就会变成"整片空白且无任何提示"。
    // 过期文件由 scripts/prune-dist.mjs 按时间清理。
    emptyOutDir: false,
    assetsDir: 'assets',
    // 板端 WebKit2GTK 2.44 支持 ES2020+，无需为旧内核降级
    target: 'es2020',
    sourcemap: false,
  },
  server: {
    port: 5173,
    proxy: {
      '/api': 'http://127.0.0.1:8081',
    },
  },
})
