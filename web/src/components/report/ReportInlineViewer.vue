<script setup lang="ts">
/* 内嵌报告查看：在主页面右侧区域就地显示，不跳路由。
   顶部工具条含返回（回报告管理）/ 报告信息 / 导出；右边缘抽屉只读展示当时的填写内容。
   打开前由主页面暂存录入现场，切回录入锚点时由主页面恢复。 */
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import ReportDocument from '@/components/report/ReportDocument.vue'
import InfoTable from '@/components/report/InfoTable.vue'
import { itemGroupName } from '@/domain/itemGroups'
import { reasonList } from '@/domain/validation'
import { overviewText, countByCategory } from '@/domain/riskScore'
import { buildAppendixRows } from '@/domain/reportResult'
import { modelStatus } from '@/domain/modelStatus'
import { useReportStore } from '@/stores/report'
import { useExport } from '@/utils/export'
import { useToast } from '@/utils/toast'
import { ApiError } from '@/utils/http'
import type { JteItem } from '@/types/api'

const props = defineProps<{ reportId: string }>()
const emit = defineEmits<{ back: [] }>()

const store = useReportStore()
const exp = useExport()
const { show } = useToast()

/* 父组件在切换前已经把报告装进 store：这种情况下首帧直接渲染报告，
   不用再经历一次"加载中"的闪屏。 */
const preloaded = store.reportId === props.reportId && store.ready
const loading = ref(!preloaded)
const loadError = ref('')
/* 纸张要先按 A4 原尺寸渲染、再由 fitPapers() 等比缩放；
   在缩放完成前先藏起来，避免"完整宽度闪一下再缩回去"。 */
const fitted = ref(false)
const reportWrap = ref<HTMLElement | null>(null)
const panelOpen = ref(false)
const collapsed = reactive<Record<string, boolean>>({})

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
const modelNotice = computed(() => modelStatus(store.generated))
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

/* ── 只读填写内容（右边缘抽屉）───────────────────────── */
interface RefGroup {
  key: string
  name: string
  range: string
  items: JteItem[]
  total: number
  unfit: number
}
const refGroups = computed<RefGroup[]>(() => {
  const map = new Map<string, RefGroup>()
  for (const item of store.items) {
    const key = item.no.split('.')[0] || item.no
    let group = map.get(key)
    if (!group) {
      group = { key, name: itemGroupName(key), range: item.no, items: [], total: 0, unfit: 0 }
      map.set(key, group)
    }
    group.items.push(item)
    group.range = group.items.length === 1 ? item.no : group.items[0].no + '–' + item.no
    group.total += 1
    if (store.stateOf(item.no).result === '不符合') group.unfit += 1
  }
  return [...map.values()]
})

function toggleGroup(key: string): void {
  collapsed[key] = !collapsed[key]
}

function resultOf(no: string): string {
  return store.stateOf(no).result || '未填'
}

/** 不符合项明细：与录入页「不符合情形」同源（含「其他」自行填写内容） */
function detailsOf(no: string): string[] {
  const state = store.stateOf(no)
  if (state.result !== '不符合') return []
  return reasonList(state)
}

/** 风险评定值来自服务端的专家查表结果，与报告里的「风险评定值」列一致 */
function riskOf(no: string) {
  return store.generated?.risks?.[no]
}

/* A4 宽度（210mm @96dpi），报告页按视口等比缩放 */
const PAPER_WIDTH = 793.7
let paperObserver: ResizeObserver | undefined

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
}

onMounted(async () => {
  if (!preloaded) {
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
  fitted.value = true
  window.addEventListener('resize', fitPapers)
  void document.fonts?.ready.then(fitPapers)
  if (modelNotice.value) show(modelNotice.value, 5200)
})

onBeforeUnmount(() => {
  paperObserver?.disconnect()
  window.removeEventListener('resize', fitPapers)
})
</script>

<template>
  <section class="report-viewer">
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

    <!-- 右侧折叠侧栏：当时的填写页面（只读，不可编辑） -->
    <aside v-if="panelOpen && !loading && !loadError" class="ref-panel" aria-label="评估填写内容（只读）">
      <div class="ref-head">
        <button class="ref-close" type="button" title="收起" aria-label="收起" @click="panelOpen = false">
          ×
        </button>
        <b>评估填写内容</b>
        <span class="ref-tag">只读</span>
      </div>
      <div class="ref-body">
        <h3>基础信息</h3>
        <InfoTable readonly :show-computed="true" class="ref-info" />

        <h3>检测项目（{{ store.items.length }} 项 · 不符合 {{ riskRows.length }} 项）</h3>
        <table class="ref-items">
          <thead>
            <tr>
              <th rowspan="2" style="width: 56px">编号</th>
              <th rowspan="2">项目</th>
              <th rowspan="2" style="width: 62px">结果</th>
              <th colspan="3" class="ref-risk-head">风险评定值</th>
            </tr>
            <tr>
              <th style="width: 50px">严重程度</th>
              <th style="width: 50px">概率等级</th>
              <th style="width: 50px">风险类别</th>
            </tr>
          </thead>
          <tbody v-for="group in refGroups" :key="group.key">
            <tr class="ref-group">
              <td colspan="6">
                <button
                  class="ref-group-toggle"
                  type="button"
                  :aria-expanded="!collapsed[group.key]"
                  @click="toggleGroup(group.key)"
                >
                  <span class="caret" :class="{ open: !collapsed[group.key] }">▸</span>
                  <span class="ref-group-name">{{ group.key }} {{ group.name }}</span>
                  <span class="ref-group-range">{{ group.range }}</span>
                  <span class="ref-group-meta">{{ group.total }} 项 · 不符合 {{ group.unfit }}</span>
                </button>
              </td>
            </tr>
            <template v-if="!collapsed[group.key]">
              <template v-for="item in group.items" :key="item.no">
                <tr :class="{ 'ref-unfit': resultOf(item.no) === '不符合' }">
                  <td class="ref-no">{{ item.no }}</td>
                  <td>
                    {{ item.name }}<span v-if="item.sub" class="ref-sub">（{{ item.sub }}）</span>
                  </td>
                  <td class="ref-result" :class="{ unfit: resultOf(item.no) === '不符合' }">
                    {{ resultOf(item.no) }}
                  </td>
                  <template v-if="riskOf(item.no)">
                    <td class="ref-risk">{{ riskOf(item.no)?.severity ?? '待确认' }}</td>
                    <td class="ref-risk">{{ riskOf(item.no)?.probability ?? '待确认' }}</td>
                    <td class="ref-risk">{{ riskOf(item.no)?.category }}</td>
                  </template>
                  <template v-else>
                    <td class="ref-risk">—</td>
                    <td class="ref-risk">—</td>
                    <td class="ref-risk">—</td>
                  </template>
                </tr>
                <tr v-if="detailsOf(item.no).length" class="ref-reasons">
                  <td></td>
                  <td colspan="5">
                    <div class="ref-reasons-box">
                      <div class="ref-reasons-head">不符合项</div>
                      <ul class="ref-reasons-list">
                        <li v-for="(reason, i) in detailsOf(item.no)" :key="i">{{ reason }}</li>
                      </ul>
                    </div>
                  </td>
                </tr>
              </template>
            </template>
          </tbody>
        </table>
      </div>
    </aside>
  </section>
</template>

<style scoped>
.report-viewer {
  min-height: 100%;
  background: var(--c-bg);
  padding: 12px;
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

/* ── 右侧只读填写内容抽屉 ── */
.ref-panel {
  position: fixed;
  /* 横竖屏都保持右侧抽屉，统一贴顶；z-index 高于顶栏/侧栏，不会被裁切 */
  top: 0;
  right: 0;
  bottom: 0;
  width: min(560px, 100vw);
  display: flex;
  flex-direction: column;
  background: var(--c-panel);
  border-left: 1px solid var(--c-line);
  box-shadow: -8px 0 28px rgba(0, 0, 0, 0.16);
  z-index: 500;
}

.ref-head {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 12px 14px;
  border-bottom: 1px solid var(--c-line);
}

.ref-head b {
  font-family: var(--font-bold);
  font-size: 14px;
  color: var(--c-primary);
}

.ref-tag {
  padding: 0 6px;
  border-radius: 8px;
  background: var(--c-primary-soft);
  color: var(--c-primary);
  font-size: 10.5px;
  line-height: 16px;
}

.ref-close {
  flex: 0 0 auto;
  width: 32px;
  height: 32px;
  padding: 0;
  border: 1px solid var(--c-line);
  border-radius: 8px;
  background: #fff;
  color: var(--c-primary);
  font-size: 20px;
  line-height: 1;
  cursor: pointer;
}

.ref-close:hover {
  border-color: var(--c-primary);
  background: var(--c-primary-soft);
}

.ref-close:hover {
  color: var(--c-danger);
}

.ref-body {
  flex: 1;
  min-height: 0;
  overflow: auto;
  padding: 12px 14px 28px;
}

.ref-body h3 {
  margin: 16px 0 8px;
  font-family: var(--font-bold);
  font-size: 13px;
  color: var(--c-secondary);
}

.ref-body h3:first-child {
  margin-top: 0;
}

.ref-items {
  width: 100%;
  border-collapse: collapse;
  font-size: 12.5px;
}

/* 只读基础信息表：横竖屏都照搬录入页竖屏的紧凑排版 */
.ref-info :deep(th),
.ref-info :deep(td) {
  display: table-cell;
  width: auto;
  height: 30px;
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

.ref-info :deep(.info) {
  table-layout: fixed;
}

.ref-items th,
.ref-items td {
  border: 1px solid var(--c-line);
  padding: 5px 6px;
  text-align: left;
  vertical-align: top;
}

.ref-items thead th {
  background: var(--c-head);
  color: var(--c-text);
}

.ref-no {
  color: var(--c-secondary);
  white-space: nowrap;
}

.ref-result {
  white-space: nowrap;
}

.ref-result.unfit {
  color: var(--c-danger);
  font-weight: 700;
}

.ref-risk-head,
.ref-items thead tr:nth-child(2) th {
  text-align: center;
}

.ref-risk {
  text-align: center;
  color: var(--c-text);
  white-space: nowrap;
}

.ref-sub {
  color: var(--c-muted);
  font-size: 11.5px;
}

.ref-items tr.ref-unfit td {
  background: #fef0f0;
}

.ref-items tr.ref-reasons td {
  background: #fef7f7;
  color: var(--c-text);
  font-size: 12px;
  line-height: 1.7;
}

.ref-reasons-box {
  padding: 2px 0 4px;
}

.ref-reasons-head {
  margin-bottom: 4px;
  color: var(--c-danger);
  font-weight: 700;
  font-size: 12px;
}

.ref-reasons-list {
  margin: 0;
  padding: 0;
  list-style: none;
}

.ref-reasons-list li {
  padding: 1px 0 1px 2px;
}

.ref-reasons-list li + li {
  margin-top: 2px;
}

.ref-items .ref-group td {
  padding: 0;
  background: var(--c-head);
}

.ref-group-toggle {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  padding: 6px 8px;
  border: 0;
  background: none;
  color: var(--c-text);
  font: inherit;
  font-size: 12px;
  text-align: left;
  cursor: pointer;
}

.ref-group-toggle .caret {
  color: var(--c-primary);
  font-size: 10px;
  transition: transform 0.15s;
}

.ref-group-toggle .caret.open {
  transform: rotate(90deg);
}

.ref-group-name {
  font-weight: 700;
}

.ref-group-range {
  color: var(--c-muted);
  font-size: 11px;
}

.ref-group-meta {
  margin-left: auto;
  color: var(--c-secondary);
  font-size: 11px;
  white-space: nowrap;
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
</style>
