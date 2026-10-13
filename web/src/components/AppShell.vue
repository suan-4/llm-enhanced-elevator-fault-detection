<script setup lang="ts">
/* 应用外壳：左侧可折叠导航 + 顶部标题栏 + 内容槽。

   为什么要单独抽出来：页面从 2 个变成多个之后，侧栏和顶栏不能再长在
   某一个页面里（否则每加一页都要复制一份）。外壳由 App.vue 决定要不要显示：
   登录页 / 初始化向导 / 忘记口令这三页是"空白页"，不套外壳。 */
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import AppSidebar, { type NavItem } from '@/components/AppSidebar.vue'
import ExportResult from '@/components/report/ExportResult.vue'
import { useAuthStore } from '@/stores/auth'
import { useShell } from '@/stores/shell'
import { useKiosk } from '@/utils/kiosk'
import { useToast } from '@/utils/toast'

const NAV: NavItem[] = [
  { key: 'input', label: '评估报告录入' },
  { key: 'report', label: '报告预览' },
  { key: 'accounts', label: '账号管理' },
]

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const shell = useShell()
const kiosk = useKiosk()
const { show } = useToast()

/** 账号页由路由决定高亮；录入/预览由页面自己回报 */
const active = computed(() => (route.name === 'accounts' ? 'accounts' : shell.active))

function onNavigate(key: string): void {
  if (key === 'accounts') {
    void router.push('/accounts')
    return
  }
  if (route.path !== '/') void router.push('/')
  // 交给录入页消费：'input' 切回录入，'report' 触发生成并切到预览
  shell.requestView(key === 'report' ? 'report' : 'input')
}

/** 与旧版一致：点右侧内容区自动收起侧栏，把宽度让给正文 */
function onMainClick(e: MouseEvent): void {
  if (!shell.collapsed && !(e.target as HTMLElement).closest('.sidebar-toggle')) {
    shell.collapsed = true
  }
}

async function signOut(): Promise<void> {
  await auth.signOut()
  shell.active = 'input'
  shell.requested = ''
  await router.replace({ name: 'login' })
}

async function exitSystem(): Promise<void> {
  try {
    await kiosk.exit()
    show('已退出系统，正在返回桌面')
  } catch (err) {
    show(err instanceof Error ? err.message : '退出失败')
  }
}
</script>

<template>
  <div class="app-shell">
    <AppSidebar
      :collapsed="shell.collapsed"
      :items="NAV"
      :active="active"
      :user-name="auth.user?.display_name || auth.user?.username || ''"
      user-role="检验员"
      :show-exit="kiosk.showExit()"
      @toggle="shell.collapsed = !shell.collapsed"
      @navigate="onNavigate"
      @logout="signOut"
      @exit-system="exitSystem"
    />

    <div class="main" :class="{ expanded: shell.collapsed }" @click="onMainClick">
      <header class="topbar">
        <div class="brand">
          <span class="brand-mark">GDSEI</span>
          <span class="brand-text">在用曳引驱动电梯安全评估系统</span>
        </div>
        <span class="topbar-sep" />
        <div class="topbar-meta">质量体系文件编号：GDSEI/JTE-09-R02-3.00</div>
      </header>

      <slot />
    </div>

    <ExportResult />
  </div>
</template>
