<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { afterPaint, beginInteraction } from '@/utils/performance'
import InfoTable from '@/components/report/InfoTable.vue'
import ItemTable from '@/components/report/ItemTable.vue'
import MissingList from '@/components/report/MissingList.vue'
import ReportDocument from '@/components/report/ReportDocument.vue'
import AppDialog from '@/components/AppDialog.vue'
import { overviewText, countByCategory } from '@/domain/riskScore'
import { buildAppendixRows, overviewNarrative } from '@/domain/reportResult'
import { modelStatus } from '@/domain/modelStatus'
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
const confirmNew = ref(false)
const newBusy = ref(false)
const confirmExport = ref<'pdf' | 'docx' | null>(null)
const reportWrap = ref<HTMLElement | null>(null)
const locked = computed(() => ['filed', 'void'].includes(store.status) || store.exportUncertain)

/* 侧栏 / 顶栏已上移到 AppShell，本页只管内容。
   侧栏点「评估报告录入 / 报告预览」可能是①本页已挂载（立即切）或
   ②从账号页跳过来（本页刚挂载，事件已过去）——所以看 shell.requested 待办标记。 */
function consumeShellRequest(): void {
  const want = shell.requested
  if (!want) return
  shell.requested = ''
  if (want === 'report') {
    void showPreview()
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
watch([() => store.form, () => store.states], () => store.scheduleSave(), { deep: true, flush: 'sync' })

/* 页面切到后台/被关闭时，尽量把防抖里还压着的改动写下去。
   防抖窗口（800ms）内掉电仍可能丢最后一次改动，所以悬浮岛会显示保存状态。 */
function flushOnHide(): void {
  if (document.visibilityState === 'hidden') flushOnPageHide()
}
function flushOnPageHide(): void {
  // The store retains the failure; lifecycle events have no caller to catch it.
  void store.flush().catch(() => undefined)
}
document.addEventListener('visibilitychange', flushOnHide)
window.addEventListener('pagehide', flushOnPageHide)

const saveHint = computed(() => {
  if (store.saveState === 'saving') return '保存中…'
  if (store.saveState === 'error') return '保存失败'
  return store.savedAt ? `已保存 ${store.savedAt.slice(11, 16)}` : ''
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', fitPapers)
  document.removeEventListener('visibilitychange', flushOnHide)
  window.removeEventListener('pagehide', flushOnPageHide)
})

/* 风险值只使用服务端专家查表结果，不用演示值填补未确认数据。 */
const riskRows = computed(() =>
  store.items
    .filter((item) => store.stateOf(item.no).result === '不符合')
    .map((item) => ({
      item,
      state: store.stateOf(item.no),
      risk: store.generated?.risks?.[item.no],
    })),
)

const riskByNo = computed(() => store.generated?.risks ?? {})

const categories = computed(() => Object.values(riskByNo.value).map(risk => risk.category))
const g = computed(() => store.generated?.score ?? null)
const grade = computed(() => store.generated?.grade ?? null)
const assessmentIssues = computed(() => store.generated?.assessment_issues ?? [])
const modelNotice = computed(() => modelStatus(store.generated))
/* 模板统计 + 已校验概况。新策略的规则兜底也保留最高风险，故障提示不进入纸张。 */
const overview = computed(() => {
  const count = countByCategory(categories.value)
  const base = g.value === null
    ? `1、存在Ⅰ类风险 ${count['Ⅰ类']} 项，Ⅱ类风险 ${count['Ⅱ类']} 项。\n2、综合评定暂不可用，详见评定提示。`
    : overviewText(categories.value, g.value)
  const narrative = overviewNarrative(store.generated)
  return narrative ? `${base}\n${narrative}` : base
})
const conclusion = computed(() => `综合安全状况等级：${grade.value ?? '待确认'}`)
const appendixRows = computed(() => buildAppendixRows(store.items, store.stateOf, riskByNo.value))

function requestExport(fmt: 'pdf' | 'docx'): void {
  if (assessmentIssues.value.length) return
  if (store.generated?.other_matches.length) confirmExport.value = fmt
  else void exp.run(fmt)
}

function approveExport(): void {
  const fmt = confirmExport.value
  confirmExport.value = null
  if (fmt) void exp.run(fmt)
}

/* ── 交互 ── */
/** 滚动容器是 .main（body 不滚动），因此回到顶部要滚它而不是 window */
function scrollToTop(): void {
  const main = document.querySelector('.main')
  if (main) main.scrollTo({ top: 0, behavior: 'smooth' })
}

async function saveNow(): Promise<void> {
  try {
    if (locked.value) {
      show('这份报告已归档或作废，原内容已保留；修改请在报告管理中复制为新建')
      return
    }
    await store.save()
    show('草稿已保存')
  } catch (err) {
    show(err instanceof Error ? err.message : '保存失败')
  }
}

/* ── 新建评估 ──
   现场真实需要：上一条电梯录完（或录到一半）要开下一条。
   录入页以前只会「没有草稿就建、有草稿就续录」，用户既找不到入口，
   也分不清眼前这张表是新的还是上次没填完的。 */
const hasProgress = computed(
  () =>
    store.counters.done > 0 ||
    ['clientName', 'userName', 'deviceCategory', 'productNo'].some(
      (key) => !!(store.form[key] || '').trim(),
    ),
)

async function startNewReport(): Promise<void> {
  if (generating.value || newBusy.value) return
  // 空白表直接新建；已经填了东西才提醒一句，避免误点丢掉现场进度
  if (hasProgress.value) {
    confirmNew.value = true
    return
  }
  await doNewReport()
}

async function doNewReport(): Promise<void> {
  confirmNew.value = false
  newBusy.value = true
  try {
    await store.createNew()
    view.value = 'input'
    showAlert.value = false
    show('已新建一份评估')
    scrollToTop()
  } catch (err) {
    show(err instanceof Error ? err.message : '新建失败')
  } finally {
    newBusy.value = false
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
  const timing = beginInteraction('report_generate')
  generating.value = true
  try {
    await store.generate(timing)
    await timing.measure('render', async () => {
      view.value = 'report'
      await nextTick()
      fitPapers()
      await afterPaint()
    })
    timing.finish('ok')
  } catch (err) {
    timing.finish('error')
    show(err instanceof Error ? err.message : '生成失败')
  } finally {
    generating.value = false
  }
}

async function showPreview(): Promise<void> {
  if (!store.generated) {
    await generate()
    return
  }
  await store.ensurePreview()
  view.value = 'report'
  nextTick(fitPapers)
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
  /* 只把焦点给「要打字」的控件：radio/checkbox 拿到焦点会让板端弹软键盘，
     而且它们本身不需要光标。条目行只做高亮 + 滚动定位就够了。 */
  const isTextControl = (node: Element | null): boolean =>
    node instanceof HTMLTextAreaElement ||
    (node instanceof HTMLInputElement && node.type !== 'radio' && node.type !== 'checkbox')
  const focusable = isTextControl(el)
    ? el
    : (el.querySelector('input:not([type="radio"]):not([type="checkbox"]), textarea') as HTMLElement | null)
  if (focusable) focusable.focus({ preventScroll: true })
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

          <fieldset v-else :disabled="locked || exp.busy.value" style="border: 0; padding: 0; margin: 0; min-width: 0">
            <div v-if="locked" class="notes" role="status">{{ store.exportUncertain
              ? '导出状态待确认，暂时只读；恢复连接后请重试导出或重新打开报告。'
              : '这份报告已归档或作废，只读查看；修改请在报告管理中复制为新建。' }}</div>
            <InfoTable />
            <div style="margin-top: 14px">
              <ItemTable />
            </div>
          </fieldset>
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
                JTE-09-R02-3.00　不符合 {{ riskRows.length }} 项　综合安全状况等级 {{ grade ?? '待确认' }}
              </span>
            </div>
            <div v-if="modelNotice" class="notes model-status" role="status">{{ modelNotice }}</div>
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
          />
        </div>
      </section>

      <div class="actionbar">
        <div class="bar-top">
          <span class="count">
            共 <b>{{ store.counters.total }}</b> 项　已评 <b>{{ store.counters.done }}</b> 项　不符合
            <span class="bad">{{ store.counters.unfit }}</span> 项　未填
            <span class="bad">{{ store.counters.miss }}</span> 项
          </span>
          <span v-if="saveHint" class="save-hint">{{ saveHint }}</span>
        </div>

        <div class="bar-bottom">
          <button
            class="new-btn"
            type="button"
            :disabled="generating || newBusy"
            @click="startNewReport"
          >
            ＋ 新建评估
          </button>
          <button
            class="btn btn-lg btn-save"
            type="button"
            :disabled="store.saveState === 'saving' || locked || exp.busy.value"
            @click="saveNow"
          >
            保存草稿
          </button>
          <div class="bar-actions">
            <button
              v-if="view === 'input'"
              class="btn btn-lg btn-primary"
              type="button"
              :disabled="generating || locked || exp.busy.value"
              @click="generate"
            >
              {{ generating ? '生成中…' : '校验并生成报告' }}
            </button>
            <template v-else>
              <button
                class="btn btn-lg btn-primary"
                type="button"
                :disabled="exp.busy.value || assessmentIssues.length > 0"
                @click="requestExport('pdf')"
              >
                {{ exp.busy.value ? '导出中…' : '导出 PDF' }}
              </button>
              <button
                class="btn btn-lg btn-primary"
                type="button"
                :disabled="exp.busy.value || assessmentIssues.length > 0"
                @click="requestExport('docx')"
              >
                导出 Word
              </button>
            </template>
          </div>
        </div>
      </div>

      <AppDialog
        :open="confirmNew"
        title="新建评估"
        confirm-text="新建"
        :busy="newBusy"
        @close="confirmNew = false"
        @confirm="doNewReport"
      >
        <p class="dialog-p">
          当前这份评估已填 <b>{{ store.counters.done }}</b> 项。
        </p>
        <p class="dialog-p">
          新建后它不会丢，仍留在「报告管理」里，随时可以点「继续编辑」接着填。
        </p>
        <p class="dialog-p">确定新建一份空白评估吗？</p>
      </AppDialog>
      <AppDialog :open="confirmExport !== null" title="核对自然语言匹配" confirm-text="确认并导出"
        @close="confirmExport = null" @confirm="approveExport">
        <p v-for="match in store.generated?.other_matches ?? []" :key="match.no" class="dialog-p">
          项目 {{ match.no }} 原文：{{ match.original_text }}<br />
          匹配风险：{{ match.risks.join('；') }}
        </p>
        <p class="dialog-p">请核对匹配风险及附页措施。存在错误时返回录入页修改。</p>
      </AppDialog>
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
