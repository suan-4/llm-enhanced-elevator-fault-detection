<script setup lang="ts">
/* 应用外壳：左侧项目进度导航 + 顶部标题栏 + 内容槽 + 右下角设置入口。

   为什么要单独抽出来：页面从 2 个变成多个之后，侧栏和顶栏不能再长在
   某一个页面里（否则每加一页都要复制一份）。外壳由 App.vue 决定要不要显示：
   登录页 / 初始化向导 / 忘记口令这三页是"空白页"，不套外壳。

   导航口径（2026-10 调整）：
   - 侧栏只负责「一台电梯的录入进度」：项目进度 + 三个滚动锚点；
   - 报告管理 / 账号管理已并入系统设置，入口是右下角的齿轮 icon；
   - 设置页自带左侧树状导航，因此设置页不显示这根侧栏（.main.no-nav）。 */
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { systemConfig } from '@/api/system'
import AppSidebar, { type NavItem } from '@/components/AppSidebar.vue'
import ExportResult from '@/components/report/ExportResult.vue'
import { useAuthStore } from '@/stores/auth'
import { useReportStore } from '@/stores/report'
import { useGenerationStore } from '@/stores/generation'
import { useShell } from '@/stores/shell'
import { useKiosk } from '@/utils/kiosk'
import { useToast } from '@/utils/toast'

const manualKgSelection = ref(true)
const NAV = computed<NavItem[]>(() => {
  const items: NavItem[] = [
    { key: 'info', label: '基础信息' },
    { key: 'items', label: '检测项目填写' },
  ]
  if (manualKgSelection.value) items.push({ key: 'confirm', label: '人工确认' })
  items.push({ key: 'reports', label: '报告管理' })
  return items
})

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const report = useReportStore()
const generation = useGenerationStore()
const shell = useShell()
const kiosk = useKiosk()
const { show } = useToast()

/* 系统设置自带左侧树，不显示项目侧栏 */
const isFullPage = computed(() => route.name === 'settings')
const isSettings = computed(() => route.name === 'settings')

/** 侧栏高亮：只看录入页的三个锚点 */
const active = computed(() => (isFullPage.value ? '' : shell.active))

/** 侧栏「项目进度」：当前这份评估的填写进度 */
const progress = computed(() => ({
  done: report.counters.done,
  total: report.counters.total,
  unfit: report.counters.unfit,
}))

function onNavigate(key: string): void {
  if (generation.generating) {
    show('报告生成中，请稍候', 2500)
    return
  }
  if (key === 'confirm') {
    // 与「校验并生成报告」共用同一套前置提示：漏填/没有不符合项时不要静默跳转
    if (report.ready && report.missing.length) {
      show(`还有 ${report.missing.length} 项未填写`, 3000, 'danger')
      return
    }
    if (report.ready && report.counters.unfit === 0) {
      show('当前没有不符合项，无需人工确认', 3000)
      return
    }
    shell.active = 'confirm'
    if (route.path !== '/kg-confirm') void router.push('/kg-confirm')
    return
  }
  const anchor = key as 'info' | 'items' | 'reports'
  // 先同步高亮并把目标锚点挂起，再由 ReportView 挂载时消费；
  // 不要等 router.push().then 才设置，否则会先按滚动位置闪到别的项。
  shell.active = anchor
  shell.requestView(anchor)
  if (route.path !== '/') {
    void router.push('/')
    return
  }
  shell.requestView(anchor)
}

async function loadManualSelection(): Promise<void> {
  try {
    const cfg = await systemConfig()
    const item = cfg.items.find((row) => row.key === 'manual_kg_selection')
    manualKgSelection.value = item ? item.value !== false : true
  } catch {
    manualKgSelection.value = true
  }
}

onMounted(loadManualSelection)
watch(() => route.fullPath, loadManualSelection)
watch(() => route.name, (name) => {
  if (name === 'kg-confirm') shell.active = 'confirm'
})

/** 与旧版一致：点右侧内容区自动收起侧栏，把宽度让给正文 */
function onMainClick(e: MouseEvent): void {
  if (!shell.collapsed && !(e.target as HTMLElement).closest('.sidebar-toggle')) {
    shell.collapsed = true
  }
}

function goSettings(): void {
  void router.push('/settings')
}

function backFromFullPage(): void {
  void router.push('/').then(() => shell.requestView('info'))
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
      v-if="!isFullPage"
      :collapsed="shell.collapsed"
      :items="NAV"
      :active="active"
      :user-name="auth.user?.display_name || auth.user?.username || ''"
      :show-exit="kiosk.showExit()"
      :progress="progress"
      @toggle="shell.collapsed = !shell.collapsed"
      @navigate="onNavigate"
      @logout="signOut"
      @settings="goSettings"
      @exit-system="exitSystem"
    />

    <div
      class="main"
      :class="{ expanded: shell.collapsed, 'no-nav': isFullPage }"
      @click="onMainClick"
    >
      <header class="topbar">
        <button
          v-if="isFullPage"
          class="topbar-back"
          type="button"
          title="返回评估"
          aria-label="返回评估"
          @click="backFromFullPage"
        >
          <svg
            viewBox="0 0 24 24"
            width="16"
            height="16"
            fill="none"
            stroke="currentColor"
            stroke-width="2"
            stroke-linecap="round"
            stroke-linejoin="round"
            aria-hidden="true"
          >
            <path d="M15 18l-6-6 6-6" />
          </svg>
        </button>
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


  </div>
</template>

<style scoped>
.topbar-back {
  flex: 0 0 auto;
  width: 34px;
  height: 34px;
  margin-right: 2px;
  padding: 0;
  border: 1px solid var(--c-line);
  border-radius: 9px;
  background: var(--c-panel);
  color: var(--c-primary);
  font-size: 17px;
  line-height: 1;
  cursor: pointer;
}

.settings-fab {
  position: fixed;
  right: 22px;
  /* 让开底部操作条（宽屏单行约 84px） */
  bottom: 104px;
  width: 56px;
  height: 56px;
  border-radius: 50%;
  border: 1px solid rgba(27, 94, 122, 0.9);
  background: linear-gradient(135deg, #2d8ab5 0%, #1b5e7a 100%);
  color: #fff;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  box-shadow:
    0 10px 24px rgba(27, 94, 122, 0.42),
    0 2px 6px rgba(0, 0, 0, 0.18);
  /* 低于导出结果卡（40），导出成功时卡片会盖住齿轮，关掉卡片即可见 */
  z-index: 30;
  transition:
    transform 0.18s,
    box-shadow 0.18s,
    filter 0.18s;
}

.settings-fab:hover {
  transform: scale(1.06);
  filter: brightness(1.08);
  box-shadow:
    0 14px 30px rgba(27, 94, 122, 0.5),
    0 3px 8px rgba(0, 0, 0, 0.2);
}

.settings-fab:active {
  transform: scale(0.98);
}

@media (max-width: 900px) {
  /* 板端底部操作条是两行，齿轮再往上让一点 */
  .settings-fab {
    right: 14px;
    bottom: 158px;
    width: 60px;
    height: 60px;
    box-shadow:
      0 12px 26px rgba(27, 94, 122, 0.46),
      0 2px 6px rgba(0, 0, 0, 0.18);
  }
}

/* 横屏矮视口（板端 960×600）：操作条压到 55px，齿轮跟着缩小并贴近底部 */
@media (min-width: 901px) and (max-height: 700px) {
  .settings-fab {
    right: 14px;
    bottom: 72px;
    width: 44px;
    height: 44px;
    box-shadow:
      0 8px 18px rgba(27, 94, 122, 0.4),
      0 2px 6px rgba(0, 0, 0, 0.18);
  }

  .settings-fab svg {
    width: 20px;
    height: 20px;
  }
}
</style>
