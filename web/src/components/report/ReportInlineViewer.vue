<script setup lang="ts">
/* 内嵌报告查看：在主页面右侧区域就地显示，不跳路由。
   顶部工具条含返回（回报告管理）/ 报告信息 / 导出；右边缘抽屉只读展示当时的填写内容。
   打开前由主页面暂存录入现场，切回录入锚点时由主页面恢复。 */
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import ReportDocument from '@/components/report/ReportDocument.vue'
import ReportEvaluationDrawer from '@/components/report/ReportEvaluationDrawer.vue'
import { overviewText, countByCategory } from '@/domain/riskScore'
import { buildAppendixRows } from '@/domain/reportResult'
import { useReportStore } from '@/stores/report'
import { useGenerationStore } from '@/stores/generation'
import { useExport } from '@/utils/export'
import { ApiError } from '@/utils/http'

const props = defineProps<{
  reportId: string
  generating?: boolean
  streamText?: string
}>()
const emit = defineEmits<{ back: [] }>()

const store = useReportStore()
const generationStore = useGenerationStore()
const exp = useExport()

/* 父组件在切换前已经把报告装进 store：这种情况下首帧直接渲染报告，
   不用再经历一次"加载中"的闪屏。 */
const preloaded = props.generating
  ? true
  : (store.reportId === props.reportId && store.ready)
const loading = ref(!preloaded)
const loadError = ref('')
/* 纸张要先按 A4 原尺寸渲染、再由 fitPapers() 等比缩放；
   在缩放完成前先藏起来，避免"完整宽度闪一下再缩回去"。 */
const fitted = ref(false)
const reportWrap = ref<HTMLElement | null>(null)
const panelOpen = ref(!!props.generating && window.innerWidth >= 701)
const panelShift = ref(0)
watch(() => props.generating, (active) => {
  // 横屏生成时自动打开侧栏，方便和不合格项对照；竖屏不自动占满屏幕。
  if (active) panelOpen.value = window.innerWidth >= 701
})

function computePanelShift(): void {
  if (!panelOpen.value || window.innerWidth < 701) {
    panelShift.value = 0
    return
  }
  const paper = document.querySelector('.report-wrap .paper') as HTMLElement | null
  if (!paper) return
  const drawerLeft = window.innerWidth - Math.min(430, window.innerWidth)
  // 纸张当前可能已经左移；只补足仍被抽屉压住的宽度，避免来回累积。
  const needed = Math.max(0, paper.getBoundingClientRect().right - drawerLeft + 16)
  if (needed > 1) panelShift.value = Math.min(panelShift.value + needed, 560)
}

watch(panelOpen, async () => {
  if (!panelOpen.value) panelShift.value = 0
  await nextTick()
  computePanelShift()
})
// 侧栏展开/收起只做 transform 位移，纸张尺寸不变；不要再重算缩放，
// 否则滚动条/布局测量会让纸张看起来忽大忽小。
const typingText = ref('')
const typing = ref(false)
let typingTimer: number | undefined


const STATUS_TEXT: Record<string, string> = {
  draft: '草稿',
  generated: '已生成',
  filed: '已归档',
  void: '已作废',
}
const STATUS_CLASS: Record<string, string> = {
  draft: 'draft',
  generated: 'on',
  filed: 'on',
  void: 'off',
}
const statusText = computed(() => STATUS_TEXT[store.status] || store.status || '—')
const statusClass = computed(() => STATUS_CLASS[store.status] || '')
const canExport = computed(
  () => ['generated', 'filed'].includes(store.status) && !!store.generated?.result_digest,
)

const riskRows = computed(() =>
  store.items
    .filter((item) => store.stateOf(item.no).result === '不符合')
    .map((item) => ({ item, state: store.stateOf(item.no) })),
)
const riskByNo = computed(() => store.generated?.risks ?? {})
const categories = computed(() => Object.values(riskByNo.value).map((risk) => risk.category))
const g = computed(() => store.generated?.score ?? null)
const grade = computed(() => store.generated?.grade ?? null)
const assessmentIssues = computed(() => store.generated?.assessment_issues ?? [])
const overview = computed(() => {
  const count = countByCategory(categories.value)
  const base = g.value === null
    ? `1、存在Ⅰ类风险 ${count['Ⅰ类']} 项，Ⅱ类风险 ${count['Ⅱ类']} 项。\n2、综合评定暂不可用，详见评定提示。`
    : overviewText(categories.value, g.value)
  return base
})
const conclusion = computed(() => `综合安全状况等级：${grade.value ?? '待确认'}`)
const appendixRows = computed(() => buildAppendixRows(store.items, store.stateOf, riskByNo.value))
const analysisText = computed(() => store.generated?.analysis_text ?? '')

function stopTyping(): void {
  if (typingTimer !== undefined) {
    window.clearInterval(typingTimer)
    typingTimer = undefined
  }
  typing.value = false
}

function startTyping(text: string): void {
  stopTyping()
  typingText.value = ''
  if (!text) return
  typing.value = true
  let cursor = 0
  typingTimer = window.setInterval(() => {
    cursor = Math.min(text.length, cursor + 2)
    typingText.value = text.slice(0, cursor)
    if (cursor >= text.length) {
      stopTyping()
      typingText.value = text
    }
  }, 18)
}

/* A4 宽度（210mm @96dpi），报告页按视口等比缩放 */
const PAPER_WIDTH = 793.7
let paperObserver: ResizeObserver | undefined
let layoutObserver: MutationObserver | undefined

const followStream = ref(true)
let autoScrolling = false
let followTimer: number | undefined

function analysisPageTop(): number | null {
  const main = document.querySelector('.main') as HTMLElement | null
  const holder = document.querySelector('.report-wrap .analysis-paper')?.closest('.paper-holder') as HTMLElement | null
  if (!main || !holder) return null
  const mainRect = main.getBoundingClientRect()
  const holderRect = holder.getBoundingClientRect()
  const bar = document.querySelector('.report-viewer .viewer-bar') as HTMLElement | null
  // 顶栏/查看工具条是 sticky 的，页面顶端必须让开它们，否则标题会被遮住。
  const inset = bar ? Math.max(60, bar.getBoundingClientRect().bottom - mainRect.top + 12) : 60
  return Math.max(0, main.scrollTop + holderRect.top - mainRect.top - inset)
}

/** 用户主动移动后暂停自动跟随；回到分析页顶部再恢复。 */
function onMainScroll(): void {
  if (autoScrolling) return
  const main = document.querySelector('.main') as HTMLElement | null
  const target = analysisPageTop()
  if (!main || target === null) return
  followStream.value = Math.abs(main.scrollTop - target) < 96
}

function scrollToAnalysisPageTop(): void {
  const main = document.querySelector('.main') as HTMLElement | null
  const target = analysisPageTop()
  if (!main || target === null) return
  autoScrolling = true
  main.scrollTo({ top: target, behavior: 'auto' })
  window.clearTimeout(followTimer)
  followTimer = window.setTimeout(() => { autoScrolling = false }, 80)
}

watch([() => props.streamText, () => props.generating], () => {
  if (!props.generating || !followStream.value) return
  void nextTick(() => {
    fitPapers()
    scrollToAnalysisPageTop()
  })
})

// props.generating 在组件已挂载后才变 true 时，也立即滚到分析页。
watch(() => props.generating, (active) => {
  if (!active) return
  followStream.value = true
  void nextTick(() => {
    fitPapers()
    scrollToAnalysisPageTop()
  })
})

function onResize(): void {
  fitPapers()
  computePanelShift()
}

function fitPapers(): void {
  const host = reportWrap.value
  if (!host) return
  const style = getComputedStyle(host)
  const padding = parseFloat(style.paddingLeft) + parseFloat(style.paddingRight)
  const available = host.clientWidth - padding - 1
  let scale = Math.min(1, Math.max(available, 0) / PAPER_WIDTH)
  /* 横屏矮视口（板端 960×600）：宽度与高度同时约束，整页 A4 能一屏看全 */
  if (window.innerHeight <= 700) {
    const hostTop = host.getBoundingClientRect().top
    const actionbar = document.querySelector('.actionbar')
    const bottom = actionbar
      ? Math.max(0, window.innerHeight - actionbar.getBoundingClientRect().top)
      : 12
    const maxHeight = window.innerHeight - hostTop - bottom - 16
    const firstPaper = host.querySelector<HTMLElement>('.paper')
    if (firstPaper && firstPaper.offsetHeight > 0 && maxHeight > 0) {
      scale = Math.min(scale, maxHeight / firstPaper.offsetHeight)
    }
  }
  host.querySelectorAll<HTMLElement>('.paper').forEach((paper) => {
    const holder = paper.parentElement
    paper.style.transform = scale === 1 ? '' : `scale(${scale})`
    if (holder) {
      holder.style.width = `${PAPER_WIDTH * scale}px`
      holder.style.height = `${paper.offsetHeight * scale}px`
    }
  })
}

function observePapers(): void {
  const host = reportWrap.value
  if (!host) return
  paperObserver?.disconnect()
  paperObserver = new ResizeObserver(fitPapers)
  paperObserver.observe(host)
  host.querySelectorAll('.paper').forEach((paper) => paperObserver?.observe(paper))
  // 生成中分析页/新纸张是动态插入的；插入后立即缩放并对齐，
  // 不能等第一个 token 到达才做，否则会先看到未缩放的大白页。
  layoutObserver?.disconnect()
  layoutObserver = new MutationObserver(() => {
    fitPapers()
    if (props.generating && followStream.value) scrollToAnalysisPageTop()
  })
  layoutObserver.observe(host, { childList: true, subtree: true })
}

onMounted(async () => {
  if (!preloaded && !props.generating) {
    try {
      await store.loadItems()
      await store.openReport(props.reportId)
    } catch (err) {
      loadError.value = err instanceof ApiError ? err.detail : (err instanceof Error ? err.message : '报告加载失败')
    } finally {
      loading.value = false
    }
  }
  await nextTick()
  observePapers()
  fitPapers()
  computePanelShift()
  fitted.value = true
  if (generationStore.consumeReplay(props.reportId)) {
    panelOpen.value = true
    await nextTick()
    startTyping(analysisText.value)
  }
  window.addEventListener('resize', onResize)
  document.querySelector('.main')?.addEventListener('scroll', onMainScroll, { passive: true })
  void document.fonts?.ready.then(fitPapers)
  if (props.generating) {
    await nextTick()
    // 生成页首次布局时纸张/分析页可能还没完成，延迟再测一次；
    // 否则会误判为“取不到分析页”，直到第一个 token 才滚动。
    scrollToAnalysisPageTop()
    for (const delay of [60, 160, 320, 600]) {
      window.setTimeout(() => {
        fitPapers()
        if (followStream.value) scrollToAnalysisPageTop()
      }, delay)
    }
  }
})

onBeforeUnmount(() => {
  paperObserver?.disconnect()
  layoutObserver?.disconnect()
  stopTyping()
  window.removeEventListener('resize', onResize)
  document.querySelector('.main')?.removeEventListener('scroll', onMainScroll)
  window.clearTimeout(followTimer)
})
</script>

<template>
  <section
    class="report-viewer"
    :class="{ 'panel-open': panelOpen }"
    :style="{ '--panel-shift': `${panelShift}px` }"
  >
    <div class="viewer-bar">
      <button
        class="viewer-back"
        type="button"
        title="返回报告管理"
        aria-label="返回报告管理"
        @click="emit('back')"
      >
        <svg
          viewBox="0 0 24 24"
          width="18"
          height="18"
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
      <div v-if="!loading && !loadError" class="viewer-head">
        <b class="viewer-no">{{ store.generated?.report_no || '（未生成）' }}</b>
        <span class="status-tag" :class="statusClass">{{ statusText }}</span>
        <span class="report-meta">
          <span class="meta-template">JTE-09-R02-3.00　</span>
          <span class="meta-unfit">不符合 {{ riskRows.length }} 项　</span>
          <span class="meta-score">得分 {{ g ?? '待确认' }}　</span>
          <span class="meta-grade">等级 {{ grade ?? '待确认' }}</span>
        </span>
      </div>
      <div v-if="!loading && !loadError" class="viewer-actions">
        <button
          class="btn btn-primary"
          type="button"
          :disabled="!canExport || exp.busy.value"
          @click="exp.run('pdf')"
        >
          {{ exp.busy.value ? '导出中…' : '导出 PDF' }}
        </button>
        <button
          class="btn btn-primary"
          type="button"
          :disabled="!canExport || exp.busy.value"
          @click="exp.run('docx')"
        >
          导出 Word
        </button>
      </div>
    </div>

    <div v-if="loading" class="state-tip">正在加载报告…</div>
    <div v-else-if="loadError" class="state-tip">{{ loadError }}</div>
    <div v-else ref="reportWrap" class="report-wrap" :class="{ 'is-fitting': !fitted }">
      <div
        v-if="assessmentIssues.length || (store.generated?.other_matches ?? []).length"
        class="sheet report-toolbar"
      >
        <div v-if="assessmentIssues.length" class="notes" role="status">
          <b>待确认预览，尚不能作为正式报告导出。</b>
          <div v-for="issue in assessmentIssues" :key="issue">{{ issue }}</div>
        </div>
        <div v-for="match in store.generated?.other_matches ?? []" :key="match.no" class="notes">
          项目 {{ match.no }} 其他原文：{{ match.original_text }}<br />
          模型匹配：{{ match.risks.join('；') }}。请核对后采用。
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
        :analysis-text="analysisText"
        :stream-text="props.generating ? (props.streamText || '') : ''"
        :streaming="!!props.generating"
      />
    </div>

    <!-- 右边缘抽屉把手：单 icon，紧贴侧边 -->
    <button
      v-if="!loading && !loadError"
      class="viewer-panel-fab"
      :class="{ on: panelOpen }"
      type="button"
      :aria-expanded="panelOpen"
      :title="panelOpen ? '收起填写内容' : '查看填写内容（只读）'"
      aria-label="填写内容"
      @click="panelOpen = !panelOpen"
    >
      <svg
        viewBox="0 0 24 24"
        width="17"
        height="17"
        fill="none"
        stroke="currentColor"
        stroke-width="1.8"
        stroke-linecap="round"
        stroke-linejoin="round"
        aria-hidden="true"
      >
        <rect x="3" y="4" width="18" height="16" rx="2" />
        <path d="M9 4v16" />
      </svg>
    </button>

    <ReportEvaluationDrawer
      :open="panelOpen && !loading && !loadError"
      :analysis-text="props.generating ? '' : analysisText"
      :typing="typing"
      :typing-text="typingText"
      :auto-scroll="false"
      @close="panelOpen = false"
    />
  </section>
</template>

<style scoped>
.report-viewer {
  min-height: 100%;
  background: var(--c-bg);
  padding: 12px;
  /* 侧栏展开时避免出现/消失滚动条改变白页宽度 */
  scrollbar-gutter: stable;
}

/* 就地查看：工具条吸附在正文顶部（让开 52px 全局顶栏），返回/导出永远可见 */
.viewer-bar {
  position: sticky;
  top: 52px;
  z-index: 20;
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
  max-width: 1080px;
  margin: 0 auto 10px;
  padding: 8px 12px;
  background: var(--c-panel);
  border: 1px solid var(--c-line);
  border-radius: var(--radius);
  box-shadow: var(--shadow);
}

.viewer-back {
  flex: 0 0 auto;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 38px;
  height: 38px;
  padding: 0;
  border: 1px solid var(--c-line);
  border-radius: 9px;
  background: #fff;
  color: var(--c-primary);
  cursor: pointer;
  transition: background 0.15s, border-color 0.15s;
}

.viewer-back:hover {
  border-color: var(--c-primary);
  background: var(--c-primary-soft);
}

.viewer-head {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: nowrap;
  min-width: 0;
}

.viewer-no {
  color: var(--c-text);
  font-family: var(--font-bold);
  font-size: 14px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.viewer-actions {
  margin-left: auto;
  display: flex;
  gap: 8px;
  flex-wrap: nowrap;
  align-items: center;
  flex: 0 0 auto;
}

.state-tip {
  padding: 40px 0;
  color: var(--c-muted);
  text-align: center;
}

.report-wrap.is-fitting {
  visibility: hidden;
}

/* 横屏矮视口（板端 960×600）：查看页工具条与纸张容器收紧 */
@media (min-width: 901px) and (max-height: 700px) {
  .report-viewer {
    padding: 8px;
  }

  .viewer-bar {
    gap: 8px;
    padding: 5px 8px;
    margin-bottom: 8px;
  }

  .viewer-back {
    width: 30px;
    height: 30px;
  }

  .viewer-back svg {
    width: 16px;
    height: 16px;
  }

  .viewer-head {
    gap: 6px;
  }

  .viewer-no {
    font-size: 12.5px;
  }

  .report-meta {
    font-size: 11px;
  }

  .meta-template {
    display: none;
  }

  .viewer-actions {
    gap: 6px;
  }

  .viewer-actions .btn {
    height: 28px;
    padding: 0 10px;
    font-size: 12px;
  }

  .report-wrap {
    padding: 6px 8px;
  }

  .paper-holder {
    margin-bottom: 8px;
  }

  .state-tip {
    padding: 20px 0;
  }
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
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  min-width: 0;
}

.viewer-panel-fab {
  position: fixed;
  right: 0;
  top: 50%;
  transform: translateY(-50%);
  z-index: 40;
  display: flex;
  align-items: center;
  justify-content: center;
  width: 36px;
  height: 68px;
  padding: 0;
  border: 1px solid var(--c-line);
  border-right: 0;
  border-radius: 10px 0 0 10px;
  background: var(--c-panel);
  color: var(--c-primary);
  box-shadow: -4px 0 14px rgba(0, 0, 0, 0.12);
  cursor: pointer;
  transition: background 0.15s, border-color 0.15s, color 0.15s;
}

.viewer-panel-fab:hover,
.viewer-panel-fab.on {
  border-color: var(--c-primary);
  background: var(--c-primary-soft);
}

@media (max-width: 900px) {
  .report-viewer {
    padding: 6px;
  }

  .viewer-bar {
    gap: 8px;
    padding: 8px;
  }

  .viewer-head {
    gap: 6px;
  }

  .viewer-no {
    font-size: 11.5px;
    max-width: 132px;
  }

  .report-meta {
    font-size: 10.5px;
  }

  .meta-template,
  .meta-unfit,
  .meta-grade {
    display: none;
  }

  .viewer-actions {
    gap: 6px;
  }

  .viewer-actions .btn {
    height: 34px;
    padding: 0 9px;
    font-size: 12px;
  }

  .ref-body {
    padding: 10px 10px 24px;
  }



  .ref-head {
    padding: 10px 12px;
  }

  .ref-head b {
    font-size: 13px;
  }

  .ref-items {
    font-size: 11.5px;
  }

  .ref-items th,
  .ref-items td {
    padding: 4px 5px;
  }

  /* 让只读基础信息表与录入页「评估填写」保持同一比例（行高/内边距/字号） */
  .ref-info :deep(th),
  .ref-info :deep(td) {
    display: table-cell;
    width: auto;
    height: 29px;
    padding: 2px 4px;
    border: 1px solid var(--c-line);
    font-size: 12px;
    line-height: 16px;
    white-space: normal;
  }

  .ref-info :deep(.signature-row td) {
    height: 28px;
  }

  .ref-info :deep(.signature-seal) {
    font-size: 10px;
    line-height: 16px;
  }

  .ref-info :deep(.computed-field) {
    color: var(--c-secondary);
  }

  .ref-reasons-list {
    font-size: 11.5px;
  }
}
.analysis-paper h1 {
  margin-top: 0;
}
.analysis-note {
  color: var(--c-muted);
  font-size: 12px;
  margin: 6px 0 14px;
}
.analysis-body {
  white-space: pre-wrap;
  line-height: 1.9;
  font-size: 14px;
  color: #222;
}
/* 抽屉展开时只把报告纸张整体往左移，不改变纸张尺寸。 */
.report-wrap {
  transition: transform 0.28s ease;
  box-sizing: border-box;
}
@media (min-width: 701px) {
  .report-viewer.panel-open .report-wrap {
    transform: translateX(calc(-1 * var(--panel-shift, 0px)));
  }
}
</style>
