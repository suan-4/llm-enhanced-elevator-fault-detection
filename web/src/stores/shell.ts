import { defineStore } from 'pinia'
import { ref } from 'vue'

/* 外壳（侧栏 + 顶栏）的共享状态。
   - collapsed：侧栏是否折叠（窄屏点击正文会自动收起）
   - active：侧栏高亮项（录入页/预览页由页面自己回报，账号页由路由决定）
   - requested：侧栏请求录入页切到哪个视图（input / report），由录入页消费后清空。
     用"待办标记"而不是事件，是因为从账号页点过来时录入页还没挂载，
     事件会丢；标记会在挂载时被读到。 */
export const useShell = defineStore('shell', () => {
  const collapsed = ref(false)
  const active = ref('input')
  const requested = ref<'' | 'input' | 'report'>('')

  function requestView(view: 'input' | 'report'): void {
    requested.value = view
  }

  return { collapsed, active, requested, requestView }
})
