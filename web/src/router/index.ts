import { createRouter, createWebHashHistory } from 'vue-router'
import { useAuthStore } from '@/stores/auth'

/* 用 hash 模式：板端 FastAPI 只需伺服 / 与 /assets，无需 SPA 回退规则 */
const router = createRouter({
  history: createWebHashHistory(),
  routes: [
    {
      path: '/',
      name: 'report',
      component: () => import('@/views/ReportView.vue'),
      meta: { requiresAuth: true },
    },
    {
      path: '/login',
      name: 'login',
      component: () => import('@/views/LoginView.vue'),
    },
    { path: '/:pathMatch(.*)*', redirect: '/' },
  ],
})

let restored = false

router.beforeEach(async (to) => {
  const auth = useAuthStore()
  if (!restored) {
    await auth.restore()
    restored = true
  }
  if (to.meta.requiresAuth && !auth.user) {
    return { name: 'login' }
  }
  if (to.name === 'login' && auth.user) {
    return { name: 'report' }
  }
  return true
})

export default router
