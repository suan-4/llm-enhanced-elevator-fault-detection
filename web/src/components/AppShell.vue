<script setup lang="ts">
/* 应用外壳：左侧项目进度导航 + 顶部标题栏 + 内容槽 + 右下角设置入口。

   为什么要单独抽出来：页面从 2 个变成多个之后，侧栏和顶栏不能再长在
   某一个页面里（否则每加一页都要复制一份）。外壳由 App.vue 决定要不要显示：
   登录页 / 初始化向导 / 忘记口令这三页是"空白页"，不套外壳。

   导航口径（2026-10 调整）：
   - 侧栏只负责「一台电梯的录入进度」：项目进度 + 三个滚动锚点；
   - 报告管理 / 账号管理已并入系统设置，入口是右下角的齿轮 icon；
   - 设置页自带左侧树状导航，因此设置页不显示这根侧栏（.main.no-nav）。 */
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import AppSidebar, { type NavItem } from '@/components/AppSidebar.vue'
import ExportResult from '@/components/report/ExportResult.vue'
import { useAuthStore } from '@/stores/auth'
import { useReportStore } from '@/stores/report'
import { useShell } from '@/stores/shell'
import { useKiosk } from '@/utils/kiosk'
import { useToast } from '@/utils/toast'

const NAV: NavItem[] = [
  { key: 'info', label: '基础信息' },
  { key: 'items', label: '检测项目填写' },
  { key: 'report', label: '所生成报告' },
]

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const report = useReportStore()
const shell = useShell()
const kiosk = useKiosk()
const { show } = useToast()

const isSettings = computed(() => route.name === 'settings')

/** 侧栏高亮：只看录入页的三个锚点 */
const active = computed(() => (isSettings.value ? '' : shell.active))

/** 侧栏「项目进度」：当前这份评估的填写进度 */
const progress = computed(() => ({
  done: report.counters.done,
  total: report.counters.total,
  unfit: report.counters.unfit,
}))

function onNavigate(key: string): void {
  const anchor = key as 'info' | 'items' | 'report'
  if (route.path !== '/') {
    void router.push('/').then(() => shell.requestView(anchor))
    return
  }
  shell.requestView(anchor)
}

/** 与旧版一致：点右侧内容区自动收起侧栏，把宽度让给正文 */
function onMainClick(e: MouseEvent): void {
  if (!shell.collapsed && !(e.target as HTMLElement).closest('.sidebar-toggle')) {
    shell.collapsed = true
  }
}

async function signOut(): Promise<void> {
  await auth.signOut()
  shell.active = 'info'
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
      v-if="!isSettings"
      :collapsed="shell.collapsed"
      :items="NAV"
      :active="active"
      :user-name="auth.user?.display_name || auth.user?.username || ''"
      user-role="检验员"
      :show-exit="kiosk.showExit()"
      :progress="progress"
      @toggle="shell.collapsed = !shell.collapsed"
      @navigate="onNavigate"
      @logout="signOut"
      @exit-system="exitSystem"
    />

    <div
      class="main"
      :class="{ expanded: shell.collapsed, 'no-nav': isSettings }"
      @click="onMainClick"
    >
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

    <ExportResult v-if="!isSettings" />

    <!-- 系统设置入口：右下角单个 icon（报告管理 / 账号管理都收进设置页） -->
    <button
      v-if="!isSettings"
      class="settings-fab"
      type="button"
      title="系统设置"
      aria-label="系统设置"
      @click="router.push('/settings')"
    >
      <svg
        viewBox="0 0 24 24"
        width="21"
        height="21"
        fill="none"
        stroke="currentColor"
        stroke-width="1.7"
        stroke-linecap="round"
        stroke-linejoin="round"
        aria-hidden="true"
      >
        <circle cx="12" cy="12" r="3.1" />
        <path
          d="M19.4 15a1.7 1.7 0 0 0 .34 1.87l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.7 1.7 0 0 0-1.87-.34 1.7 1.7 0 0 0-1.03 1.56V21a2 2 0 1 1-4 0v-.09A1.7 1.7 0 0 0 8.9 19.3a1.7 1.7 0 0 0-1.87.34l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06A1.7 1.7 0 0 0 4.7 15a1.7 1.7 0 0 0-1.56-1.03H3a2 2 0 1 1 0-4h.09A1.7 1.7 0 0 0 4.7 8.9a1.7 1.7 0 0 0-.34-1.87l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06A1.7 1.7 0 0 0 8.9 4.7a1.7 1.7 0 0 0 1.03-1.56V3a2 2 0 1 1 4 0v.09A1.7 1.7 0 0 0 15 4.7a1.7 1.7 0 0 0 1.87-.34l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.7 1.7 0 0 0-.34 1.87 1.7 1.7 0 0 0 1.56 1.03H21a2 2 0 1 1 0 4h-.09a1.7 1.7 0 0 0-1.56 1.03z"
        />
      </svg>
    </button>
  </div>
</template>

<style scoped>
.settings-fab {
  position: fixed;
  right: 20px;
  /* 让开底部操作条（宽屏单行约 84px） */
  bottom: 100px;
  width: 44px;
  height: 44px;
  border-radius: 50%;
  border: 1px solid var(--c-line);
  background: var(--c-panel);
  color: var(--c-primary);
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  box-shadow: var(--shadow-lg);
  /* 低于导出结果卡（40），导出成功时卡片会盖住齿轮，关掉卡片即可见 */
  z-index: 30;
  transition: all 0.2s;
}

.settings-fab:hover {
  background: var(--c-primary);
  border-color: var(--c-primary);
  color: #fff;
}

@media (max-width: 900px) {
  /* 板端底部操作条是两行，齿轮再往上让一点 */
  .settings-fab {
    right: 14px;
    bottom: 152px;
    width: 46px;
    height: 46px;
  }
}
</style>
