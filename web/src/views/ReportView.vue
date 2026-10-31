<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { beginInteraction } from '@/utils/performance'
import InfoTable from '@/components/report/InfoTable.vue'
import ItemTable from '@/components/report/ItemTable.vue'
import AppDialog from '@/components/AppDialog.vue'
import ReportCenter from '@/components/report/ReportCenter.vue'
import { defaultProfileName } from '@/domain/baseInfo'
import { useReportStore } from '@/stores/report'
import { useGenerationStore } from '@/stores/generation'
import { useShell } from '@/stores/shell'
import { useToast } from '@/utils/toast'
import { systemConfig } from '@/api/system'
import ReportEvaluationDrawer from '@/components/report/ReportEvaluationDrawer.vue'
import { fetchKgCandidates, fetchKgRecommendation, fetchKgRecommendationBatch, selectKgPath,
  type KgCandidatesResponse, type KgRecommendation } from '@/api/kg'
import type { KgSelection } from '@/api/reports'

const store = useReportStore()
const generationStore = useGenerationStore()
const route = useRoute()
const router = useRouter()
const shell = useShell()
const { show } = useToast()

/* input = 录入；reports = 报告管理/查看（就地切换，不跳路由） */
const view = ref<'input' | 'reports'>('input')
const reportCenter = ref<InstanceType<typeof ReportCenter> | null>(null)
/** 进报告区域前暂存录入现场，切回录入锚点时恢复 */
let stashedForReports = false
/* 恢复现场（切回录入、继续编辑草稿、首次续录）时给 store 赋 form/states
   会触发自动保存；若当前恢复的是「已生成」的报告，保存会把状态改回草稿、
   报告从已生成列表消失。恢复期间先压住自动保存，用户真正改动时再保存。 */
let restoringSession = false

async function withAutosavePaused<T>(fn: () => Promise<T> | T): Promise<T> {
  restoringSession = true
  try {
    return await fn()
  } finally {
    restoringSession = false
  }
}
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
const streamText = ref('')
const manualKgSelection = ref(true)
const confirmNew = ref(false)
const newBusy = ref(false)
const itemTable = ref<InstanceType<typeof ItemTable> | null>(null)
/* 已归档 / 已作废的报告统一在报告查看页阅读，不再复用录入页置灰；
   录入页只剩「导出状态待确认」这一种临时只读。 */
const locked = computed(() => store.exportUncertain)

/* 侧栏是「项目进度 + 三个区域」：基础信息 / 检测项目填写 / 报告管理。
   前两个是滚动锚点，第三个就地切换到报告管理/查看区域。
   从别的页面点过来时本页可能还没挂载，所以用 shell.requested 待办标记，
   挂载后消费；本页已挂载时 watch 立即消费。 */
const SECTION_IDS = { info: 'sec-info', items: 'sec-items' } as const

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

/** 进「报告管理」区域：先把当前录入现场暂存起来（查看历史报告会占用 store） */
let inputScrollTop = 0

async function enterReports(reportId?: string): Promise<void> {
  if (view.value !== 'reports') {
    inputScrollTop = mainEl()?.scrollTop ?? 0
    store.stashSession()
    stashedForReports = true
  }
  // 先把要显示的内容准备好（列表刷新 / 重新装回正在查看的报告），再切区域
  if (reportId) await reportCenter.value?.showReport(reportId)
  else await reportCenter.value?.prepareEnter()
  view.value = 'reports'
  shell.active = 'reports'
  shell.reportsView = true
  await nextTick()
  mainEl()?.scrollTo({ top: 0 })
}

/** 从报告区域回到录入页：恢复离开前的现场 */
async function leaveReports(): Promise<void> {
  shell.reportsView = false
  const hadStash = stashedForReports
  stashedForReports = false
  if (hadStash) {
    if (!store.restoreStashedSession()) {
      store.clearSession()
      await withAutosavePaused(() => startDraft())
    }
  }
  view.value = 'input'
  await nextTick()
  updateActiveByScroll()
  // 恢复到离开录入页时的滚动位置（报告区域可能把主容器滚到了顶部）
  mainEl()?.scrollTo({ top: inputScrollTop })
}

async function showAnchor(anchor: 'info' | 'items'): Promise<void> {
  if (view.value === 'reports') await leaveReports()
  view.value = 'input'
  await nextTick()
  shell.active = anchor
  scrollToSection(SECTION_IDS[anchor])
}

/** 侧栏「报告管理」：已在报告区域就保持原状态（查看页继续看，不退回列表） */
async function showReportsSection(): Promise<void> {
  if (view.value === 'reports') return
  await enterReports()
}

/** 列表里点「继续编辑」：恢复现场并打开该草稿 */
async function editDraft(id: string): Promise<void> {
  if (view.value === 'reports') {
    await leaveReports()
  }
  try {
    await withAutosavePaused(() => store.openReport(id))
    shell.active = 'items'
    await nextTick()
    scrollToSection(SECTION_IDS.items)
  } catch (err) {
    show(err instanceof Error ? err.message : '无法继续编辑这份草稿')
  }
}

function consumeShellRequest(): void {
  const want = shell.requested
  if (!want) return
  shell.requested = ''
  if (want === 'reports') void showReportsSection()
  else if (want === 'confirm') void router.push('/kg-confirm')
  else void showAnchor(want)
}

watch(() => shell.requested, consumeShellRequest)

/* 录入视图内按滚动位置高亮侧栏锚点；报告区域固定高亮第三项 */
function updateActiveByScroll(): void {
  if (view.value === 'reports') {
    shell.active = 'reports'
    return
  }
  const main = mainEl()
  const items = document.getElementById(SECTION_IDS.items)
  if (!main || !items) return
  const offset = items.getBoundingClientRect().top - main.getBoundingClientRect().top
  shell.active = offset < 160 ? 'items' : 'info'
}

watch(view, (v) => {
  if (v === 'reports') shell.active = 'reports'
  else void nextTick(updateActiveByScroll)
})

async function loadSelectionMode(): Promise<void> {
  try {
    const cfg = await systemConfig()
    const item = cfg.items.find((row) => row.key === 'manual_kg_selection')
    manualKgSelection.value = item ? item.value !== false : true
  } catch {
    manualKgSelection.value = true
  }
}

onMounted(async () => {
  await loadSelectionMode()
  await store.loadItems()
  store.ensureBaseInfoLoaded()
  refreshSelectedProfile()
  await withAutosavePaused(() => startDraft())
  const pendingSelections = generationStore.consume()
  if (pendingSelections) {
    await nextTick()
    await runSelections(pendingSelections)
  }
  mainEl()?.addEventListener('scroll', updateActiveByScroll, { passive: true })
  document.addEventListener('click', onDocumentClick)
  consumeShellRequest()
  // 兜底：恢复的现场若仍指向已归档/已作废报告，直接进报告区域查看
  if (['filed', 'void'].includes(store.status) && store.reportId) {
    await enterReports(store.reportId)
    return
  }
  // 勾选完成生成后带 ?report=id 回到报告区域
  if (route.query.report) await enterReports(String(route.query.report))
  // 旧地址 /#/reports 会带到 ?section=reports
  else if (route.query.section === 'reports') await enterReports()
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
   store.ready 之前不保存 —— 否则刚读回来的内容会被立刻写回去。
   报告区域里 store 装的是"正在查看的历史报告"，不能触发自动保存。 */
watch([() => store.form, () => store.states], () => {
  if (view.value === 'reports' || restoringSession) return
  store.scheduleSave()
}, { deep: true, flush: 'sync' })

/* 页面切到后台/被关闭时，尽量把防抖里还压着的改动写下去。
   防抖窗口（800ms）内掉电仍可能丢最后一次改动，所以悬浮岛会显示保存状态。 */
function flushOnHide(): void {
  if (document.visibilityState === 'hidden') flushOnPageHide()
}
function flushOnPageHide(): void {
  if (view.value === 'reports') return
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
  // 若正停留在报告区域（例如点齿轮去设置页），把录入现场恢复回来再卸载
  if (stashedForReports) {
    stashedForReports = false
    if (!store.restoreStashedSession()) store.clearSession()
  }
  shell.reportsView = false
  mainEl()?.removeEventListener('scroll', updateActiveByScroll)
  document.removeEventListener('click', onDocumentClick)
  document.removeEventListener('visibilitychange', flushOnHide)
  window.removeEventListener('pagehide', flushOnPageHide)
})

/* ── 交互 ── */
/** 滚动容器是 .main（body 不滚动），因此回到顶部要滚它而不是 window */
function scrollToTop(): void {
  const main = document.querySelector('.main')
  if (main) main.scrollTo({ top: 0, behavior: 'smooth' })
}

async function saveNow(): Promise<void> {
  try {
    if (locked.value) {
      show('导出状态待确认，暂时只读；恢复连接后请重试导出或重新打开报告')
      return
    }
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
  if (profile) {
    saveProfileOpen.value = false
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
  if (store.applyBaseInfoProfile(id)) show('已应用常用信息：' + profile.name)
  else show('本机无法保存方案选择，尚未应用，请检查浏览器存储后重试', 3500, 'danger')
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
  if (!store.deleteBaseInfoProfile(deleteProfileId.value)) {
    show('删除失败：无法写入浏览器存储，请重试', 3500, 'danger')
    return
  }
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
    // 新建即新的录入现场，旧的暂存作废
    stashedForReports = false
    shell.reportsView = false
    view.value = 'input'
    show('已新建一份评估')
    scrollToTop()
  } catch (err) {
    show(err instanceof Error ? err.message : '新建失败')
  } finally {
    newBusy.value = false
  }
}

function top3Audit(candidates: KgCandidatesResponse['candidates']) {
  return candidates.map((c) => ({
    rank: c.rank, path_id: c.path_id, path_summary: c.path_summary,
    component: c.component, system: c.system, score: c.score,
  }))
}

async function autoSelectKg(unfitItems: { no: string; name: string }[]): Promise<KgSelection[]> {
  /* 关闭「人工选择」后：每项先取 Top3，再由 AI 从 Top3 中自动判断。
     前端不再进入 /kg-confirm；仍写 kg_selection 审计。 */
  const prepared = await Promise.all(unfitItems.map(async (item) => {
    const state = store.states[item.no]
    try {
      const res = await fetchKgCandidates({
        item_no: item.no,
        item_name: item.name,
        reasons: state?.reasons || [],
        other_text: state?.otherText || '',
        top_k: 3,
      })
      return { item, res }
    } catch {
      return { item, res: null as KgCandidatesResponse | null }
    }
  }))

  const recByNo = new Map<string, KgRecommendation>()
  const withCandidates = prepared.filter((p) => p.res && (p.res.candidates || []).length > 0)
  for (let i = 0; i < withCandidates.length; i += 3) {
    const group = withCandidates.slice(i, i + 3)
    try {
      const batch = await fetchKgRecommendationBatch(group.map(({ item }) => ({
        item_no: item.no,
        item_name: item.name,
        reasons: store.states[item.no]?.reasons || [],
        other_text: store.states[item.no]?.otherText || '',
        top_k: 3,
      })))
      if (!batch.success) throw new Error(batch.error || '批量推荐失败')
      for (const row of batch.recommendations) recByNo.set(row.item_no, row.recommendation)
    } catch {
      for (const { item } of group) {
        try {
          const one = await fetchKgRecommendation({
            item_no: item.no,
            item_name: item.name,
            reasons: store.states[item.no]?.reasons || [],
            other_text: store.states[item.no]?.otherText || '',
            top_k: 3,
          })
          if (one.recommendation) recByNo.set(item.no, one.recommendation)
        } catch { /* 这一项降级为无候选 */ }
      }
    }
  }

  const selections: KgSelection[] = prepared.map(({ item, res }) => {
    const rec = recByNo.get(item.no)
    const selected = rec && !rec.none && rec.path_id ? rec : null
    return {
      item_no: item.no,
      path_id: selected?.path_id || null,
      decision: selected ? 'selected' : 'no_candidate',
      rank: selected?.rank ?? null,
      query: res?.query || '',
    }
  })

  // 审计：自动模式同样记录 Top3 和最终选择
  await Promise.all(selections.map(async (sel) => {
    const found = prepared.find((p) => p.item.no === sel.item_no)
    if (!found) return
    const rec = recByNo.get(sel.item_no)
    await selectKgPath({
      report_id: store.reportId,
      item_no: sel.item_no,
      item_name: found.item.name,
      query: sel.query || '',
      path_id: sel.path_id,
      decision: sel.decision,
      rank: sel.rank,
      top3: top3Audit(found.res?.candidates || []),
      selection_source: rec?.source === 'rule' ? 'rule' : 'model',
      model_path_id: rec?.path_id || null,
      model_reason: rec?.reason || '',
    }).catch(() => null)
  }))
  return selections
}

async function runSelections(selections: KgSelection[]): Promise<void> {
  const timing = beginInteraction('report_generate')
  generating.value = true
  streamText.value = ''
  view.value = 'reports'
  shell.active = 'reports'
  shell.reportsView = true
  await nextTick()
  try {
    const report = await store.generate(timing, selections, (text) => {
      streamText.value += text
    })
    timing.finish('ok')
    generating.value = false
    await nextTick()
    await enterReports(report.id)
  } catch (err) {
    timing.finish('error')
    generating.value = false
    view.value = 'input'
    shell.active = 'items'
    shell.reportsView = false
    show(err instanceof Error ? err.message : '生成失败')
  }
}

async function generate(): Promise<void> {
  /* 漏填不再罗列清单：直接滚到第一处并给红色短提示（提示内容不宜过长）。
     jump() 会滚动 + 高亮，字段类还会把光标放进输入框，方便直接补填。 */
  if (store.missing.length) {
    const first = store.missing[0]
    await jump(first.key, first.kind)
    show(`还有 ${store.missing.length} 项未填写`, 3000, 'danger')
    return
  }
  if (generating.value) return
  /* 有不符合项：人工模式跳确认页；自动模式让 AI 从 Top3 中判断后直接生成 */
  const unfitItems = store.items.filter((it) => store.states[it.no]?.result === '不符合')
  if (unfitItems.length) {
    if (manualKgSelection.value) {
      try {
        await store.save()
        await router.push({ name: 'kg-confirm' })
      } catch (err) {
        show(err instanceof Error ? err.message : '保存草稿失败')
      }
      return
    }
    generating.value = true
    streamText.value = 'AI 正在从 Top3 候选中判断故障路径…'
    view.value = 'reports'
    shell.active = 'reports'
    shell.reportsView = true
    try {
      await store.save()
      const selections = await autoSelectKg(unfitItems)
      await runSelections(selections)
    } catch (err) {
      generating.value = false
      view.value = 'input'
      show(err instanceof Error ? err.message : '生成失败')
    }
    return
  }
  await runSelections([])
}

async function jump(key: string, kind: 'field' | 'item'): Promise<void> {
  view.value = 'input'
  await nextTick()
  if (kind === 'item') {
    itemTable.value?.expandItem(key)
    await nextTick()
  }
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

          <fieldset v-else :disabled="locked" style="border: 0; padding: 0; margin: 0; min-width: 0">
            <div v-if="locked" class="notes" role="status">
              导出状态待确认，暂时只读；恢复连接后请重试导出或重新打开报告。
            </div>
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
              <ItemTable ref="itemTable" />
            </div>
          </fieldset>
        </div>
      </section>

      <!-- 报告管理 + 查看：在右侧区域内就地切换，不跳路由 -->
      <section v-show="view === 'reports'">
        <div v-if="generating" class="gen-view">
          <div class="gen-top">
            <b>报告生成中</b>
            <span>正在生成文本分析报告，右侧为评估填写内容</span>
          </div>
          <div class="gen-main">
            <div class="gen-paper">
              <div class="gen-placeholder">正在生成报告…</div>
            </div>
            <div class="gen-drawer">
              <ReportEvaluationDrawer
                :open="true"
                :analysis-text="streamText"
                :typing="true"
                :typing-text="streamText"
                inline
                :closable="false"
              />
            </div>
          </div>
        </div>
        <ReportCenter v-else ref="reportCenter" @continue-edit="editDraft" />
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
            :disabled="store.saveState === 'saving' || locked || view === 'reports'"
            @click="saveNow"
          >
            保存草稿
          </button>
          <div class="bar-actions">
            <button
              class="btn btn-lg btn-primary"
              type="button"
              :disabled="generating || locked || view === 'reports'"
              @click="generate"
            >
              {{ generating ? '生成中…' : '校验并生成报告' }}
            </button>
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
          新建后它不会丢，仍留在左侧「报告管理」里，随时可以点「继续编辑」接着填。
        </p>
        <p class="dialog-p">确定新建一份空白评估吗？</p>
      </AppDialog>
</template>

<style scoped>
.gen-view {
  height: calc(100vh - 52px);
  box-sizing: border-box;
  display: flex;
  flex-direction: column;
  padding: 10px 14px 12px;
  overflow: hidden;
}
.gen-top {
  flex: 0 0 auto;
  display: flex;
  align-items: baseline;
  gap: 12px;
  padding: 8px 12px;
  margin-bottom: 10px;
  background: var(--c-panel);
  border: 1px solid var(--c-line);
  border-radius: var(--radius);
  color: var(--c-primary);
}
.gen-top b { font-size: 16px; }
.gen-top span { font-size: 12px; color: var(--c-muted); }
.gen-main {
  flex: 1 1 auto;
  min-height: 0;
  display: flex;
  gap: 12px;
}
.gen-paper {
  flex: 1 1 auto;
  min-width: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  background: #fff;
  border: 1px solid var(--c-line);
  border-radius: var(--radius);
  box-shadow: var(--shadow);
}
.gen-placeholder { color: var(--c-muted); font-size: 14px; }
.gen-drawer {
  flex: 0 0 380px;
  min-height: 0;
  display: flex;
  flex-direction: column;
  background: var(--c-panel);
  border: 1px solid var(--c-line);
  border-radius: var(--radius);
  box-shadow: var(--shadow);
  overflow: hidden;
}
.gen-drawer-head {
  flex: 0 0 auto;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 14px;
  border-bottom: 1px solid var(--c-line);
  color: var(--c-secondary);
  font-size: 13px;
}
.gen-drawer-head span { font-size: 11px; color: var(--c-muted); }
.gen-drawer-body {
  flex: 1 1 auto;
  min-height: 0;
  overflow: auto;
  padding: 10px 14px 20px;
  scroll-behavior: smooth;
}
.gen-drawer-body h3 {
  margin: 12px 0 6px;
  color: var(--c-secondary);
  font-size: 12.5px;
}
.gen-analysis {
  margin-top: 16px;
  padding-top: 10px;
  border-top: 1px solid var(--c-line);
}
.gen-analysis .md { font-size: 13px; line-height: 1.75; color: #223; }
.gen-analysis .md :deep(p) { margin: 0 0 8px; }
.gen-analysis .md :deep(h1),
.gen-analysis .md :deep(h2),
.gen-analysis .md :deep(h3) { margin: 8px 0 6px; color: #1b5e7a; }
.gen-analysis .md :deep(ul),
.gen-analysis .md :deep(ol) { margin: 4px 0 8px; padding-left: 20px; }
@media (max-width: 760px) {
  .gen-drawer { flex-basis: 46%; }
}
.inline-stream {
  margin: 18px 0 110px;
  padding: 14px 16px;
  border: 1px solid #cfe3ea;
  border-radius: 10px;
  background: #f7fcfd;
  box-shadow: 0 2px 10px rgba(27, 94, 122, 0.08);
}
.inline-stream-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding-bottom: 8px;
  margin-bottom: 10px;
  border-bottom: 1px solid #dceef3;
  color: #1b5e7a;
  font-size: 13px;
}
.inline-stream-head span { color: #6b8b98; font-size: 11.5px; }
.inline-stream-body {
  max-height: 320px;
  overflow-y: auto;
  line-height: 1.8;
  font-size: 13.5px;
  color: #223;
}
.inline-stream-body.md :deep(h1),
.inline-stream-body.md :deep(h2),
.inline-stream-body.md :deep(h3) { margin: 8px 0 6px; color: #1b5e7a; }
.inline-stream-body.md :deep(p) { margin: 0 0 8px; }
.inline-stream-body.md :deep(ul),
.inline-stream-body.md :deep(ol) { margin: 4px 0 8px; padding-left: 22px; }
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

@media (min-width: 901px) and (max-height: 700px) {
  /* 横屏矮视口：基础信息区域收紧，保证整页一屏放得下 */
  .section-bar {
    margin-bottom: 3px;
    padding-bottom: 3px;
  }

  .section-title {
    font-size: 14px;
  }

  .baseinfo-trigger,
  .baseinfo-apply,
  .baseinfo-save {
    height: 30px;
    font-size: 12.5px;
  }
}

@media (max-width: 900px) {
  /* 窄屏也保持「基础信息 + 方案下拉 + 应用 / 保存新方案」同一行：
     标题不换行，下拉吃剩余宽度，按钮保持固定宽。 */
  .section-bar {
    flex-wrap: nowrap;
    gap: 6px;
  }

  /* 标题不允许被挤压换行：宽度不够时压缩下拉框而不是标题 */
  .section-title {
    flex: 0 0 auto;
    white-space: nowrap;
  }

  .baseinfo-controls {
    width: auto;
    flex: 1 1 auto;
    min-width: 0;
    margin-left: auto;
    flex-wrap: nowrap;
    justify-content: flex-end;
    gap: 6px;
  }

  .baseinfo-picker {
    flex: 1 1 auto;
    min-width: 0;
  }

  .baseinfo-trigger {
    width: 100%;
    height: 34px;
    font-size: 12px;
  }

  .baseinfo-apply,
  .baseinfo-save {
    flex: 0 0 auto;
    height: 34px;
    padding: 0 8px;
    font-size: 12px;
    white-space: nowrap;
  }

  .baseinfo-menu {
    width: 100%;
    min-width: 100%;
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
