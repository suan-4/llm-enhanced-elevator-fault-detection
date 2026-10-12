import { createApp } from 'vue'
import { createPinia } from 'pinia'
import App from './App.vue'
import router from './router'
import './styles/tokens.css'
import './styles/base.css'
import './styles/report.css'

const app = createApp(App)

/* 渲染/生命周期里抛出的异常若不接住，界面会停在半渲染状态甚至整片空白
   （板端没有开发者工具，操作员无从判断）。这里统一交给启动兜底面板，
   给出可读原因与「重新加载」出口。 */
app.config.errorHandler = (err, _instance, info) => {
  const show = (window as unknown as { __BOOT_FAIL__?: (r: string, d?: string, f?: boolean) => void })
    .__BOOT_FAIL__
  const detail = err instanceof Error ? `${err.message}\n${info}` : `${String(err)}\n${info}`
  if (typeof show === 'function') show('界面渲染出错。', detail, true)
  console.error('[app error]', err, info)
}

app.use(createPinia()).use(router).mount('#app')

/* 供 index.html 的启动兜底脚本判断"应用是否真的起来了" */
;(window as unknown as { __APP_MOUNTED__?: boolean }).__APP_MOUNTED__ = true

/* 兜底面板若只是"启动超时"误报（应用其实起来了），撤掉它，
   否则会把已经可用的界面盖住。资源加载类错误不撤 —— 那种情况
   应用确实没起来，面板必须留着。 */
const bootFallback = document.getElementById('boot-fallback')
if (bootFallback && !bootFallback.hidden && bootFallback.dataset.kind === 'timeout') {
  bootFallback.hidden = true
}
