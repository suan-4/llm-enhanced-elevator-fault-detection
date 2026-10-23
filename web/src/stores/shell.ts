import { defineStore } from 'pinia'
import { ref } from 'vue'

/* 外壳（侧栏 + 顶栏）的共享状态。
   - collapsed：侧栏是否折叠（窄屏点击正文会自动收起）
   - active：侧栏高亮项。主页面三个导航：基础信息 / 检测项目填写 / 报告管理
     （报告管理是就地切换的区域，不跳路由）。
   - reportsView：主页面当前是否停留在「报告管理/查看」区域（用于隐藏设置入口）。
   - requested：侧栏请求主页面切到哪个区域，由主页面消费后清空。
     用"待办标记"而不是事件，是因为从设置页点过来时主页面还没挂载，
     事件会丢；标记会在挂载时被读到。 */
export type AnchorKey = 'info' | 'items' | 'reports'

export const useShell = defineStore('shell', () => {
  /* 窄屏（板端 600x960 逻辑视口）默认收起侧栏：一登录就展开的菜单会横在
     正文左侧挡内容，操作员还得先手动收一次。宽屏保持展开，与旧版习惯一致。 */
  const NARROW_MAX_WIDTH = 900
  const collapsed = ref(
    typeof window !== 'undefined' && window.innerWidth > 0 && window.innerWidth <= NARROW_MAX_WIDTH,
  )
  const active = ref<AnchorKey>('info')
  const requested = ref<'' | AnchorKey>('')
  const reportsView = ref(false)

  function requestView(view: AnchorKey): void {
    requested.value = view
  }

  return { collapsed, active, requested, reportsView, requestView }
})
