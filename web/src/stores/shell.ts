import { defineStore } from 'pinia'
import { ref } from 'vue'

/* 外壳（侧栏 + 顶栏）的共享状态。
   - collapsed：侧栏是否折叠（窄屏点击正文会自动收起）
   - active：侧栏高亮项（录入页/预览页由页面自己回报，账号页由路由决定）
   - requested：侧栏请求录入页切到哪个视图（input / report），由录入页消费后清空。
     用"待办标记"而不是事件，是因为从账号页点过来时录入页还没挂载，
     事件会丢；标记会在挂载时被读到。 */
export const useShell = defineStore('shell', () => {
  /* 窄屏（板端 600x960 逻辑视口）默认收起侧栏：一登录就展开的菜单会横在
     正文左侧挡内容，操作员还得先手动收一次。宽屏保持展开，与旧版习惯一致。 */
  const NARROW_MAX_WIDTH = 900
  const collapsed = ref(
    typeof window !== 'undefined' && window.innerWidth > 0 && window.innerWidth <= NARROW_MAX_WIDTH,
  )
  const active = ref('input')
  const requested = ref<'' | 'input' | 'report'>('')

  function requestView(view: 'input' | 'report'): void {
    requested.value = view
  }

  return { collapsed, active, requested, requestView }
})
