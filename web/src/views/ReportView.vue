<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import InfoTable from '@/components/report/InfoTable.vue'
import ItemTable from '@/components/report/ItemTable.vue'
import ReportDocument from '@/components/report/ReportDocument.vue'
import AppDialog from '@/components/AppDialog.vue'
import { defaultProfileName } from '@/domain/baseInfo'
import { overviewText, countByCategory } from '@/domain/riskScore'
import { buildAppendixRows } from '@/domain/reportResult'
import { useReportStore } from '@/stores/report'
import { useShell } from '@/stores/shell'
import { useExport } from '@/utils/export'
import { useToast } from '@/utils/toast'

const store = useReportStore()
const shell = useShell()
const exp = useExport()
const { show } = useToast()

const view = ref<'input' | 'report'>('input')
/* 常用基础信息：本机可存多套（不同委托/使用单位），在这里选择或保存 */
const selectedProfileId = ref('')
const profileMenuOpen = ref(false)
const pickerRoot = ref<HTMLElement | null>(null)
const saveProfileOpen = ref(false)
const deleteProfileOpen = ref(false)
const deleteProfileId = ref('')
const profileName = ref('')
const profileBusy = ref(false)

const selectedProfileName = computed(
  () =>
    store.baseInfoProfiles.find((item) => item.id === selectedProfileId.value)?.name || '',
)
const generating = ref(false)
const confirmNew = ref(false)
const newBusy = ref(false)
const confirmExport = ref<'pdf' | 'docx' | null>(null)
const reportWrap = ref<HTMLElement | null>(null)

/* 侧栏是「项目进度 + 三个滚动锚点」：基础信息 / 检测项目填写 / 所生成报告。
   从别的页面点过来时本页可能还没挂载，所以用 shell.requested 待办标记，
   挂载后消费；本页已挂载时 watch 立即消费。 */
const SECTION_IDS = { info: 'sec-info', items: 'sec-items', report: 'sec-report' } as const

function mainEl(): HTMLElement | null {
  return document.querySelector('.main') as HTMLElement | null
}

/** 滚到某个锚点（让开 52px 吸顶栏） */
function scrollToSection(id: string): void {
  const main = mainEl()
  const el = document.getElementById(id)
  if (!main || !el) return
  const top = main.scrollTop + el.getBoundingClientRect().top - main.getBoundingClientRect().top - 64
  main.scrollTo({ top: Math.max(0, top), behavior: 'smooth' })
}

async function showAnchor(anchor: 'info' | 'items'): Promise<void> {
  view.value = 'input'
  await nextTick()
  shell.active = anchor
  scrollToSection(SECTION_IDS[anchor])
}

/** 「所生成报告」：没有就先生成；漏填时会留在录入页并已定位第一处 */
async function showReportSection(): Promise<void> {
  if (!store.generated) await generate()
  if (!store.generated) return
  view.value = 'report'
  await nextTick()
  fitPapers()
  shell.active = 'report'
  scrollToSection(SECTION_IDS.report)
}

function consumeShellRequest(): void {
  const want = shell.requested
  if (!want) return
  shell.requested = ''
  if (want === 'report') void showReportSection()
  else void showAnchor(want)
}

watch(() => shell.requested, consumeShellRequest)

/* 录入视图内按滚动位置高亮侧栏锚点；报告视图固定高亮第三项 */
function updateActiveByScroll(): void {
  if (view.value === 'report') {
    shell.active = 'report'
    return
  }
  const main = mainEl()
  const items = document.getElementById(SECTION_IDS.items)
  if (!main || !items) return
  const offset = items.getBoundingClientRect().top - main.getBoundingClientRect().top
  shell.active = offset < 160 ? 'items' : 'info'
}

watch(view, (v) => {
  if (v === 'report') shell.active = 'report'
  else void nextTick(updateActiveByScroll)
})

/** A4 宽度（210mm @96dpi），用于按视口等比缩放报告页 */
const PAPER_WIDTH = 793.7

onMounted(async () => {
  await store.loadItems()
  store.ensureBaseInfoLoaded()
  refreshSelectedProfile()
  await startDraft()
  window.addEventListener('resize', fitPapers)
  mainEl()?.addEventListener('scroll', updateActiveByScroll, { passive: true })
  document.addEventListener('click', onDocumentClick)
  consumeShellRequest()
  await nextTick()
  updateActiveByScroll()
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
  mainEl()?.removeEventListener('scroll', updateActiveByScroll)
  document.removeEventListener('click', onDocumentClick)
  document.removeEventListener('visibilitychange', flushOnHide)
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
/* 评估概况 = 模板要求的两行（风险分布 + 得分）+ 大模型写的那段说明。
   规则摘要兜底的那版不往报告上打印 —— 它逐条罗列，附页已经列过了，
   塞进概况会把单元格撑得很长（放哪由 PRD Q7 定，这里先按建议默认放概况）。 */
const overview = computed(() => {
  const count = countByCategory(categories.value)
  const base = g.value === null
    ? `1、存在Ⅰ类风险 ${count['Ⅰ类']} 项，Ⅱ类风险 ${count['Ⅱ类']} 项。\n2、综合评定暂不可用，详见评定提示。`
    : overviewText(categories.value, g.value)
  const ai = store.generated?.llm_used ? store.generated.narrative.trim() : ''
  return ai ? `${base}\n${ai}` : base
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
    await store.save()
    show('草稿已保存')
  } catch (err) {
    show(err instanceof Error ? err.message : '保存失败')
  }
}

/** 下拉框选中的方案被删除后，自动回退到最近使用/第一套 */
function refreshSelectedProfile(): void {
  if (!store.baseInfoProfiles.some((item) => item.id === selectedProfileId.value)) {
    selectedProfileId.value =
      store.lastBaseInfoProfileId || store.baseInfoProfiles[0]?.id || ''
  }
}

function openSaveProfile(): void {
  profileName.value = defaultProfileName(store.form)
  saveProfileOpen.value = true
}

function confirmSaveProfile(): void {
  if (profileBusy.value) return
  profileBusy.value = true
  const profile = store.saveBaseInfoProfile(profileName.value)
  profileBusy.value = false
  saveProfileOpen.value = false
  if (profile) {
    selectedProfileId.value = profile.id
    show('常用基础信息已保存：' + profile.name)
  } else {
    show('本机无法保存常用基础信息（浏览器存储不可用）', 3000, 'danger')
  }
}

function applyProfile(): void {
  const id = selectedProfileId.value
  const profile = store.baseInfoProfiles.find((item) => item.id === id)
  if (!id || !profile) return
  store.applyBaseInfoProfile(id)
  show('已应用常用信息：' + profile.name)
}

function toggleProfileMenu(): void {
  profileMenuOpen.value = !profileMenuOpen.value
}

function selectProfile(id: string): void {
  selectedProfileId.value = id
  profileMenuOpen.value = false
}

function askDeleteProfile(id: string): void {
  deleteProfileId.value = id
  deleteProfileOpen.value = true
}

function confirmDeleteProfile(): void {
  const profile = store.baseInfoProfiles.find((item) => item.id === deleteProfileId.value)
  store.deleteBaseInfoProfile(deleteProfileId.value)
  deleteProfileOpen.value = false
  deleteProfileId.value = ''
  refreshSelectedProfile()
  if (profile) show('已删除常用信息：' + profile.name)
}

/** 点页面其它地方收起常用信息菜单 */
function onDocumentClick(event: MouseEvent): void {
  if (!profileMenuOpen.value) return
  const root = pickerRoot.value
  if (root && !root.contains(event.target as Node)) profileMenuOpen.value = false
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
    show('已新建一份评估')
    scrollToTop()
  } catch (err) {
    show(err instanceof Error ? err.message : '新建失败')
  } finally {
    newBusy.value = false
  }
}

async function generate(): Promise<void> {
  /* 漏填不再罗列清单：直接滚到第一处并给红色短提示（提示内容不宜过长）。
     jump() 会滚动 + 高亮，字段类还会把光标放进输入框，方便直接补填。 */
  if (store.missing.length) {
    const first = store.missing[0]
    jump(first.key, first.kind)
    show(`还有 ${store.missing.length} 项未填写`, 3000, 'danger')
    return
  }
  if (generating.value) return
  generating.value = true
  try {
    await store.generate()
    view.value = 'report'
    shell.active = 'report'
    void nextTick(() => {
      fitPapers()
      scrollToSection(SECTION_IDS.report)
    })
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
            <div id="sec-info">
              <div class="section-bar">
                <b class="section-title">基础信息</b>
                <div class="baseinfo-controls">
                  <div ref="pickerRoot" class="baseinfo-picker">
                    <button
                      class="baseinfo-trigger"
                      type="button"
                      aria-haspopup="listbox"
                      :aria-expanded="profileMenuOpen"
                      @click="toggleProfileMenu"
                    >
                      <span class="baseinfo-trigger-text">
                        {{ selectedProfileName || '（未选择常用信息）' }}
                      </span>
                      <span class="baseinfo-caret" :class="{ open: profileMenuOpen }">▾</span>
                    </button>
                    <ul v-if="profileMenuOpen" class="baseinfo-menu" role="listbox">
                      <li
                        v-for="profile in store.baseInfoProfiles"
                        :key="profile.id"
                        class="baseinfo-menu-item"
                        :class="{ active: profile.id === selectedProfileId }"
                      >
                        <button
                          class="baseinfo-menu-name"
                          type="button"
                          @click="selectProfile(profile.id)"
                        >
                          {{ profile.name }}
                        </button>
                        <button
                          class="baseinfo-menu-del"
                          type="button"
                          title="删除这套常用信息"
                          aria-label="删除"
                          @click.stop="askDeleteProfile(profile.id)"
                        >
                          ×
                        </button>
                      </li>
                      <li v-if="!store.baseInfoProfiles.length" class="baseinfo-menu-empty">
                        还没有常用信息，点「保存为常用…」新建
                      </li>
                    </ul>
                  </div>
                  <button
                    class="btn baseinfo-apply"
                    type="button"
                    :disabled="!selectedProfileId"
                    @click="applyProfile"
                  >
                    应用
                  </button>
                  <button class="btn baseinfo-save" type="button" @click="openSaveProfile">
                    {{ store.baseInfoProfiles.length ? '保存新方案…' : '保存为常用…' }}
                  </button>
                </div>
              </div>
              <InfoTable />
            </div>
            <div id="sec-items" style="margin-top: 14px">
              <ItemTable />
            </div>
          </template>
        </div>
      </section>

      <section id="sec-report" v-show="view === 'report'">
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
            :disabled="store.saveState === 'saving'"
            @click="saveNow"
          >
            保存草稿
          </button>
          <div class="bar-actions">
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
        :open="saveProfileOpen"
        title="保存常用基础信息"
        confirm-text="保存"
        :busy="profileBusy"
        @close="saveProfileOpen = false"
        @confirm="confirmSaveProfile"
      >
        <div class="field">
          <label>方案名称</label>
          <input
            v-model="profileName"
            class="input baseinfo-name"
            placeholder="例如：XX 小区 1# 梯 / 某公司"
          />
        </div>
        <p class="dialog-p">保存后新建评估默认带入这套抬头；同名会覆盖。</p>
      </AppDialog>
      <AppDialog
        :open="deleteProfileOpen"
        title="删除常用基础信息"
        confirm-text="删除"
        danger
        :busy="profileBusy"
        @close="deleteProfileOpen = false"
        @confirm="confirmDeleteProfile"
      >
        <p class="dialog-p">
          确定删除「{{ store.baseInfoProfiles.find((item) => item.id === deleteProfileId)?.name || '这套常用信息' }}」？
          删除不影响当前已填写的内容。
        </p>
      </AppDialog>
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
          新建后它不会丢，仍留在「系统设置 → 报告管理」里，随时可以点「继续编辑」接着填。
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
.section-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  margin: 0 0 8px;
  border-bottom: 1px solid var(--c-line);
  padding-bottom: 8px;
}

.baseinfo-controls {
  margin-left: auto;
  display: flex;
  align-items: center;
  gap: 8px;
}

.baseinfo-picker {
  position: relative;
}

.baseinfo-trigger {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 260px;
  max-width: 100%;
  height: var(--h-control);
  padding: 0 10px;
  border: 1px solid var(--c-line);
  border-radius: var(--radius-sm);
  background: #fff;
  color: var(--c-text);
  font: inherit;
  font-size: 13.5px;
  text-align: left;
  cursor: pointer;
}

.baseinfo-trigger:hover {
  border-color: var(--c-primary);
}

.baseinfo-trigger-text {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.baseinfo-caret {
  flex: 0 0 auto;
  color: var(--c-muted);
  font-size: 11px;
  transition: transform 0.15s;
}

.baseinfo-caret.open {
  transform: rotate(180deg);
}

.baseinfo-menu {
  position: absolute;
  top: calc(100% + 4px);
  left: 0;
  width: 100%;
  min-width: 260px;
  max-height: 260px;
  overflow-y: auto;
  margin: 0;
  padding: 4px;
  list-style: none;
  background: var(--c-panel);
  border: 1px solid var(--c-line);
  border-radius: var(--radius-sm);
  box-shadow: var(--shadow-lg);
  z-index: 60;
}

.baseinfo-menu-item {
  display: flex;
  align-items: center;
  gap: 6px;
  border-radius: 5px;
}

.baseinfo-menu-item:hover,
.baseinfo-menu-item.active {
  background: var(--c-primary-soft);
}

.baseinfo-menu-name {
  flex: 1;
  min-width: 0;
  padding: 8px 8px;
  border: 0;
  background: none;
  color: var(--c-text);
  font: inherit;
  font-size: 12.5px;
  text-align: left;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  cursor: pointer;
}

.baseinfo-menu-del {
  flex: 0 0 auto;
  width: 20px;
  height: 20px;
  margin-right: 6px;
  padding: 0;
  border: 0;
  border-radius: 50%;
  background: #fdecec;
  color: var(--c-danger);
  font-size: 14px;
  line-height: 20px;
  text-align: center;
  cursor: pointer;
}

.baseinfo-menu-del:hover {
  background: var(--c-danger);
  color: #fff;
}

.baseinfo-menu-empty {
  padding: 8px;
  color: var(--c-muted);
  font-size: 12px;
}

@media (max-width: 900px) {
  .baseinfo-controls {
    width: 100%;
    justify-content: flex-end;
    flex-wrap: wrap;
  }

  .baseinfo-trigger {
    width: 210px;
  }

  .baseinfo-menu {
    min-width: 210px;
  }
}

.section-title {
  font-family: var(--font-bold);
  font-size: 15px;
  color: var(--c-primary);
}

.section-hint {
  color: var(--c-muted);
  font-size: 12px;
}

.section-actions {
  margin-left: auto;
  display: flex;
  gap: 8px;
}

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