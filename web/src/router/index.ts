import { createRouter, createWebHashHistory } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { useSetupStore } from '@/stores/setup'

/* 用 hash 模式：板端 FastAPI 只需伺服 / 与 /assets，无需 SPA 回退规则 */
const router = createRouter({
  history: createWebHashHistory(),
  routes: [
    {
      path: '/setup',
      name: 'setup',
      component: () => import('@/views/SetupView.vue'),
    },
    {
      path: '/login',
      name: 'login',
      component: () => import('@/views/LoginView.vue'),
    },
    {
      path: '/login/forgot',
      name: 'forgot',
      component: () => import('@/views/ForgotPasswordView.vue'),
    },
    {
      path: '/',
      name: 'report',
      component: () => import('@/views/ReportView.vue'),
      meta: { requiresAuth: true },
    },
    {
      path: '/accounts',
      name: 'accounts',
      component: () => import('@/views/AccountListView.vue'),
      meta: { requiresAuth: true },
    },
    { path: '/:pathMatch(.*)*', redirect: '/' },
  ],
})

/* 守卫里先把"登录态 + 是否已初始化"两件事问清楚再放行：
   ① 未初始化 → 一律进初始化向导（不可绕过）；
   ② 未登录 → 进登录页；
   ③ 已登录访问登录页 → 回到主页面（这样刷新页面不会掉回登录页）。 */
router.beforeEach(async (to) => {
  const auth = useAuthStore()
  const setup = useSetupStore()

  await Promise.all([
    auth.restoreOnce(),
    setup.loaded ? Promise.resolve() : setup.load(),
  ])

  if (!setup.initialized && to.name !== 'setup') {
    return { name: 'setup' }
  }
  if (setup.initialized && to.name === 'setup') {
    return { name: auth.user ? 'report' : 'login' }
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
