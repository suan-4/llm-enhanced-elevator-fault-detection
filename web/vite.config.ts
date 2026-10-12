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
    emptyOutDir: true,
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
