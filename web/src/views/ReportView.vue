<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import InfoTable from '@/components/report/InfoTable.vue'
import ItemTable from '@/components/report/ItemTable.vue'
import MissingList from '@/components/report/MissingList.vue'
import ReportDocument from '@/components/report/ReportDocument.vue'
import type { AppendixRow } from '@/types/report'
import { assignRiskDemo, type RiskValue } from '@/domain/riskAssign'
import { computeG, gradeOf, overviewText } from '@/domain/riskScore'
import { reasonsText } from '@/domain/validation'
import { useReportStore } from '@/stores/report'
import { useShell } from '@/stores/shell'
import { useExport } from '@/utils/export'
import { useToast } from '@/utils/toast'

const store = useReportStore()
const shell = useShell()
const exp = useExport()
const { show } = useToast()

const view = ref<'input' | 'report'>('input')
const showAlert = ref(false)
const generating = ref(false)
const reportWrap = ref<HTMLElement | null>(null)

/* 侧栏 / 顶栏已上移到 AppShell，本页只管内容。
   侧栏点「评估报告录入 / 报告预览」可能是①本页已挂载（立即切）或
   ②从账号页跳过来（本页刚挂载，事件已过去）——所以看 shell.requested 待办标记。 */
function consumeShellRequest(): void {
  const want = shell.requested
  if (!want) return
  shell.requested = ''
  if (want === 'report') {
    generate()
  } else {
    view.value = 'input'
  }
}

watch(() => shell.requested, consumeShellRequest)
watch(view, (v) => {
  shell.active = v
})

/** A4 宽度（210mm @96dpi），用于按视口等比缩放报告页 */
const PAPER_WIDTH = 793.7

onMounted(async () => {
  await store.loadItems()
  await startDraft()
  window.addEventListener('resize', fitPapers)
  consumeShellRequest()
})

/** 准备当前评估（没有就新建、有草稿就续录）；失败时页面给重试入口 */
async function startDraft(): Promise<void> {
  try {
    await store.ensureDraft()
  } catch (err) {
    show(err instanceof Error ? err.message : '无法开始新的评估')
  }
}

/* 改动后防抖自动保存：现场最怕录了半天，一刷新或一掉电全没了。
   store.ready 之前不保存 —— 否则刚读回来的内容会被立刻写回去。 */
watch([() => store.form, () => store.states], () => store.scheduleSave(), { deep: true })

/* 页面切到后台/被关闭时，尽量把防抖里还压着的改动写下去。
   防抖窗口（800ms）内掉电仍可能丢最后一次改动，所以悬浮岛会显示保存状态。 */
function flushOnHide(): void {
  if (document.visibilityState === 'hidden') void store.flush()
}
document.addEventListener('visibilitychange', flushOnHide)
window.addEventListener('pagehide', () => void store.flush())

const saveHint = computed(() => {
  if (store.saveState === 'saving') return '保存中…'
  if (store.saveState === 'error') return '保存失败'
  return store.savedAt ? `已保存 ${store.savedAt.slice(11, 16)}` : ''
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', fitPapers)
  document.removeEventListener('visibilitychange', flushOnHide)
})

/* ── 风险评定值与得分：以**服务端生成结果**为准 ──
   还没生成过时用本地占位值（domain/riskAssign）保证预览不空；
   生成之后一律用后端返回的值 —— 报告上的数字必须与服务端一致。 */
const riskRows = computed(() =>
  store.items
    .filter((item) => store.stateOf(item.no).result === '不符合')
    .map((item, index) => ({
      item,
      state: store.stateOf(item.no),
      risk: store.generated?.risks?.[item.no] ?? assignRiskDemo(index),
    })),
)

const riskByNo = computed(() => {
  const map: Record<string, RiskValue> = {}
  for (const row of riskRows.value) map[row.item.no] = row.risk
  return map
})

const categories = computed(() => riskRows.value.map((row) => row.risk.category))
const g = computed(() => store.generated?.score ?? computeG(categories.value))
const grade = computed(() => store.generated?.grade ?? gradeOf(g.value))
/* 评估概况 = 模板要求的两行（风险分布 + 得分）+ 大模型写的那段说明。
   规则摘要兜底的那版不往报告上打印 —— 它逐条罗列，附页已经列过了，
   塞进概况会把单元格撑得很长（放哪由 PRD Q7 定，这里先按建议默认放概况）。 */
const overview = computed(() => {
  const base = overviewText(categories.value, g.value)
  const ai = store.generated?.llm_used ? store.generated.narrative.trim() : ''
  return ai ? `${base}\n${ai}` : base
})
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

async function saveNow(): Promise<void> {
  try {
    await store.save()
    show('草稿已保存')
  } catch (err) {
    show(err instanceof Error ? err.message : '保存失败')
  }
}

async function generate(): Promise<void> {
  if (store.missing.length) {
    showAlert.value = true
    show(`有 ${store.missing.length} 项未填写，请见页面顶部清单`)
    scrollToTop()
    return
  }
  showAlert.value = false
  if (generating.value) return
  generating.value = true
  try {
    await store.generate()
    view.value = 'report'
    nextTick(fitPapers)
  } catch (err) {
    show(err instanceof Error ? err.message : '生成失败')
  } finally {
    generating.value = false
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

</script>

<template>
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
          <!-- 草稿没读完之前不给录入：否则读回来的内容会把刚输入的东西冲掉 -->
          <div v-else-if="store.draftError" class="state-tip">
            {{ store.draftError }}
            <button
              class="btn"
              type="button"
              style="margin-left: 10px"
              @click="startDraft"
            >
              重试
            </button>
          </div>
          <div v-else-if="!store.ready" class="state-tip">正在准备评估…</div>

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
                <template v-if="store.generated?.report_no">
                  报告编号 {{ store.generated.report_no }}　
                </template>
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
        <span v-if="saveHint" class="save-hint">{{ saveHint }}</span>
        <span class="spacer" />
        <button
          class="btn btn-lg"
          type="button"
          :disabled="store.saveState === 'saving'"
          @click="saveNow"
        >
          保存草稿
        </button>
        <button
          v-if="view === 'input'"
          class="btn btn-lg btn-primary"
          type="button"
          :disabled="generating"
          @click="generate"
        >
          {{ generating ? '生成中…' : '校验并生成报告' }}
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
