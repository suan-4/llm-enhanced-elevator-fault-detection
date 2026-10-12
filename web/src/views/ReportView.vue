<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import AppSidebar, { type NavItem } from '@/components/AppSidebar.vue'
import InfoTable from '@/components/report/InfoTable.vue'
import ItemTable from '@/components/report/ItemTable.vue'
import MissingList from '@/components/report/MissingList.vue'
import ReportDocument from '@/components/report/ReportDocument.vue'
import ExportResult from '@/components/report/ExportResult.vue'
import type { AppendixRow } from '@/types/report'
import { assignRiskDemo, type RiskValue } from '@/domain/riskAssign'
import { computeG, gradeOf, overviewText } from '@/domain/riskScore'
import { reasonsText } from '@/domain/validation'
import { useAuthStore } from '@/stores/auth'
import { useReportStore } from '@/stores/report'
import { useExport } from '@/utils/export'
import { useKiosk } from '@/utils/kiosk'
import { useToast } from '@/utils/toast'

const router = useRouter()
const auth = useAuthStore()
const store = useReportStore()
const kiosk = useKiosk()
const exp = useExport()
const { show } = useToast()

const view = ref<'input' | 'report'>('input')
const collapsed = ref(false)
const showAlert = ref(false)
const reportWrap = ref<HTMLElement | null>(null)

const NAV: NavItem[] = [
  { key: 'input', label: '评估报告录入' },
  { key: 'report', label: '报告预览' },
]

/** A4 宽度（210mm @96dpi），用于按视口等比缩放报告页 */
const PAPER_WIDTH = 793.7

onMounted(async () => {
  await store.loadItems()
  window.addEventListener('resize', fitPapers)
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', fitPapers)
})

/* ── 风险评定值（占位：规则待确认，见 domain/riskAssign.ts） ── */
const riskRows = computed(() =>
  store.items
    .filter((item) => store.stateOf(item.no).result === '不符合')
    .map((item, index) => ({ item, state: store.stateOf(item.no), risk: assignRiskDemo(index) })),
)

const riskByNo = computed(() => {
  const map: Record<string, RiskValue> = {}
  for (const row of riskRows.value) map[row.item.no] = row.risk
  return map
})

const categories = computed(() => riskRows.value.map((row) => row.risk.category))
const g = computed(() => computeG(categories.value))
const grade = computed(() => gradeOf(g.value))
const overview = computed(() => overviewText(categories.value, g.value))
const conclusion = computed(() => `综合安全状况等级：${grade.value}`)
const appendixRows = computed<AppendixRow[]>(() =>
  riskRows.value.map((row) => ({ no: row.item.no, risk: row.risk, text: reasonsText(row.state) })),
)

/* ── 交互 ── */
/** 滚动容器是 .main（body 不滚动），因此回到顶部要滚它而不是 window */
function scrollToTop(): void {
  const main = document.querySelector('.main')
  if (main) main.scrollTo({ top: 0, behavior: 'smooth' })
}

function generate(): void {
  if (store.missing.length) {
    showAlert.value = true
    show(`有 ${store.missing.length} 项未填写，请见页面顶部清单`)
    scrollToTop()
    return
  }
  showAlert.value = false
  view.value = 'report'
  nextTick(fitPapers)
}

function navigate(key: string): void {
  if (key === view.value) return
  if (key === 'report') {
    generate()
  } else {
    view.value = 'input'
  }
}

/** 与旧版一致：点击右侧内容区自动收起侧边栏，把宽度让给正文 */
function onMainClick(e: MouseEvent): void {
  if (!collapsed.value && !(e.target as HTMLElement).closest('.sidebar-toggle')) {
    collapsed.value = true
  }
}

function jump(key: string, kind: 'field' | 'item'): void {
  const el =
    kind === 'field'
      ? document.getElementById(`f-${key}`)
      : document.getElementById(`row-${key.replace('.', '-')}`)
  if (!el) return
  el.scrollIntoView({ behavior: 'smooth', block: 'center' })
  el.classList.remove('row-mark')
  void (el as HTMLElement).offsetWidth
  el.classList.add('row-mark')
  const focusable = el.matches('input') ? el : el.querySelector('input, textarea')
  if (focusable instanceof HTMLElement) focusable.focus({ preventScroll: true })
}

/** 报告页整体等比缩放：竖屏下也完整可见，不重排 */
function fitPapers(): void {
  const host = reportWrap.value
  if (!host) return
  const style = getComputedStyle(host)
  const padding = parseFloat(style.paddingLeft) + parseFloat(style.paddingRight)
  const available = host.clientWidth - padding - 1
  const scale = Math.min(1, Math.max(available, 0) / PAPER_WIDTH)
  host.querySelectorAll<HTMLElement>('.paper').forEach((paper) => {
    const holder = paper.parentElement
    paper.style.transform = scale === 1 ? '' : `scale(${scale})`
    if (holder) {
      holder.style.width = `${PAPER_WIDTH * scale}px`
      holder.style.height = `${paper.offsetHeight * scale}px`
    }
  })
}

async function signOut(): Promise<void> {
  await auth.signOut()
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
      :collapsed="collapsed"
      :items="NAV"
      :active="view"
      :user-name="auth.user?.display_name || auth.user?.username || ''"
      :user-role="auth.user?.role === 'admin' ? '管理员' : '检验员'"
      :show-exit="kiosk.showExit()"
      @toggle="collapsed = !collapsed"
      @navigate="navigate"
      @logout="signOut"
      @exit-system="exitSystem"
    />

    <div class="main" :class="{ expanded: collapsed }" @click="onMainClick">
      <header class="topbar">
        <div class="brand">
          <span class="brand-mark">GDSEI</span>
          <span class="brand-text">在用曳引驱动电梯安全评估系统</span>
        </div>
        <span class="topbar-sep" />
        <div class="topbar-meta">质量体系文件编号：GDSEI/JTE-09-R02-3.00</div>
      </header>

      <MissingList v-if="showAlert && store.missing.length" @jump="jump" />

      <section v-show="view === 'input'">
        <div class="sheet">
          <h1 class="doc-title">在用曳引驱动电梯安全评估报告</h1>

          <div v-if="store.itemsLoading" class="state-tip">正在加载评价条目…</div>
          <div v-else-if="store.itemsError" class="state-tip">
            {{ store.itemsError }}
            <button class="btn" type="button" style="margin-left: 10px" @click="store.loadItems()">
              重试
            </button>
          </div>

          <template v-else>
            <InfoTable />
            <div style="margin-top: 14px">
              <ItemTable />
            </div>
          </template>
        </div>
      </section>

      <section v-show="view === 'report'">
        <div ref="reportWrap" class="report-wrap">
          <div class="sheet report-toolbar">
            <div style="display: flex; align-items: center; gap: 12px">
              <b style="color: var(--c-text)">报告预览</b>
              <span class="report-meta">
                JTE-09-R02-3.00　不符合 {{ riskRows.length }} 项　综合安全状况等级 {{ grade }}
              </span>
            </div>
          </div>

          <ReportDocument
            :overview="overview"
            :conclusion="conclusion"
            :risk-by-no="riskByNo"
            :appendix-rows="appendixRows"
            :categories="categories"
            :g="g"
            :grade="grade"
          />
        </div>
      </section>

      <div class="actionbar">
        <span class="count">
          共 <b>{{ store.counters.total }}</b> 项　已评 <b>{{ store.counters.done }}</b> 项　不符合
          <span class="bad">{{ store.counters.unfit }}</span> 项　未填
          <span class="bad">{{ store.counters.miss }}</span> 项
        </span>
        <span class="spacer" />
        <button class="btn btn-lg" type="button" @click="show('草稿已保存')">保存草稿</button>
        <button
          v-if="view === 'input'"
          class="btn btn-lg btn-primary"
          type="button"
          @click="generate"
        >
          校验并生成报告
        </button>
        <template v-else>
          <button
            class="btn btn-lg btn-primary"
            type="button"
            :disabled="exp.busy.value"
            @click="exp.run('pdf')"
          >
            {{ exp.busy.value ? '导出中…' : '导出 PDF' }}
          </button>
          <button
            class="btn btn-lg btn-primary"
            type="button"
            :disabled="exp.busy.value"
            @click="exp.run('docx')"
          >
            导出 Word
          </button>
        </template>
      </div>
    </div>

    <ExportResult />
  </div>
</template>

<style scoped>
.state-tip {
  padding: 20px 0;
  color: var(--c-muted);
  text-align: center;
}

.report-toolbar {
  width: var(--paper-width);
  max-width: calc(100% - 12px);
  margin: 0 auto 10px;
  padding: 10px 12px;
}

.report-meta {
  color: var(--c-muted);
  font-size: 12.5px;
}

@media (max-width: 900px) {
  .report-meta {
    display: none;
  }
}
</style>
