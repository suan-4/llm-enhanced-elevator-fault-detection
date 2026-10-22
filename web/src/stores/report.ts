import { defineStore } from 'pinia'
import { computed, reactive, ref } from 'vue'
import * as reportApi from '@/api/report'
import * as flowApi from '@/api/reports'
import type { ItemAnswer, ReportSummary, RiskValue } from '@/api/reports'
import type { Grade } from '@/domain/riskScore'
import {
  collectMissing,
  countItems,
  createItemState,
  type ItemResult,
  type ItemState,
} from '@/domain/validation'
import { stripClauseMarker } from '@/domain/format'
import {
  baseInfoStorageKey,
  defaultProfileName,
  lastProfileStorageKey,
  mergeBaseInfo,
  pickBaseInfo,
  profilesStorageKey,
  removeProfile,
  sanitizeProfiles,
  upsertProfile,
  type BaseInfoProfile,
} from '@/domain/baseInfo'
import { useAuthStore } from '@/stores/auth'
import type { JteItem } from '@/types/api'

/** 界面用中文取值，接口用 code（见《数据库设计 v1》§7.2） */
const RESULT_TO_CODE: Record<string, string> = {
  符合: 'fit',
  不符合: 'unfit',
  无此项: 'na',
}
const CODE_TO_RESULT: Record<string, ItemResult> = {
  fit: '符合',
  unfit: '不符合',
  na: '无此项',
}

export interface GeneratedInfo {
  report_no: string | null
  score: number | null
  grade: Grade | null
  narrative: string
  /** 叙述文字是否真由大模型生成（false = 规则摘要兜底，报告里不打印） */
  llm_used: boolean
  risks: Record<string, RiskValue>
  generated_at: string
  assessment_issues: string[]
  other_matches: { no: string; original_text: string; risks: string[] }[]
}

/** 旧草稿只有 floorsStopsDoors 一个字符串（如「10 层　12 站　12 门」），
    新表单拆成三个数字框。读回时按数字顺序拆出来，避免历史草稿丢数据。 */
function migrateLegacyFloors(form: Record<string, string>): void {
  const legacy = form.floorsStopsDoors
  if (legacy === undefined) return
  const numbers = String(legacy).match(/\d+/g) ?? []
  if (!form.floors) form.floors = numbers[0] ?? ''
  if (!form.stops) form.stops = numbers[1] ?? ''
  if (!form.doors) form.doors = numbers[2] ?? ''
  delete form.floorsStopsDoors
}

/** 旧草稿把单位写在值里（「/ kg」「1000 kg」）；新表单单位固定、只存数字。
    读回时把旧字符串里的数字提出来，「无值」统一成空串。 */
function migrateLegacyUnits(form: Record<string, string>): void {
  for (const key of ['ratedLoad', 'ratedSpeed']) {
    const raw = String(form[key] ?? '').trim()
    if (!raw) {
      form[key] = ''
      continue
    }
    if (/^\d+(\.\d+)?$/.test(raw)) continue
    const match = raw.match(/\d+(?:\.\d+)?/)
    form[key] = match ? match[0] : ''
  }
}

/** 载入时去掉条款编号（a) b) 1) …），数据文件本身保持与模板一致 */
function normalize(items: JteItem[]): JteItem[] {
  return items.map((item) => ({
    ...item,
    req: item.req.map(stripClauseMarker),
    opts: item.opts.map(stripClauseMarker),
  }))
}

/** 抬头信息表默认值：四项必填留空，其余预填「/」 */
function createForm(): Record<string, string> {
  return {
    clientName: '',
    userName: '',
    installSite: '/',
    deviceCategory: '',
    deviceVariety: '/',
    model: '/',
    productNo: '',
    registerNo: '/',
    manufactureDate: '/',
    manufacturer: '/',
    retrofitUnit: '/',
    retrofitDate: '/',
    maintainUnit: '/',
    /* 额定载重/额定速度也只存数字：单位 kg、m/s 是固定标签，不再写进值里。
       旧草稿的「/ kg」「1000 kg」在 hydrate 时自动把数字提出来。 */
    ratedLoad: '',
    ratedSpeed: '',
    /* 层/站/门拆成三个数字框：单位字是固定文字，不是可删的输入内容。
       旧草稿里的 floorsStopsDoors 字符串在 hydrate 时自动拆回来。 */
    floors: '',
    stops: '',
    doors: '',
    controlMode: '/',
    /* 现场规则：除四个必填项（委托/使用单位名称、设备类别、产品编号），其余一律以「/」
       占位，意思是可填可不填。这两项以前直接照抄了设计稿 mockup 里的演示文案
       （一长串仪器清单 / 规范清单），打开就像已经填过，会误导操作员。 */
    instruments: '/',
    basis: '/',
    suggestion: '/',
    remark: '/',
    assessDate: '/',
  }
}

export const useReportStore = defineStore('report', () => {
  const items = ref<JteItem[]>([])
  const itemsLoading = ref(false)
  const itemsError = ref('')
  const form = ref<Record<string, string>>(createForm())
  const states = reactive<Record<string, ItemState>>({})

  /* ── 与服务端同步的状态 ─────────────────────────────── */
  const reportId = ref<string | null>(null)
  const version = ref(1)
  const status = ref('')
  const generated = ref<GeneratedInfo | null>(null)
  const saveState = ref<'idle' | 'saving' | 'saved' | 'error'>('idle')
  const savedAt = ref('')
  /** 装载完成前不触发自动保存，避免刚读回来的内容又被写回去 */
  const ready = ref(false)
  const draftError = ref('')
  let saveTimer: number | undefined

  function stateOf(no: string): ItemState {
    if (!states[no]) states[no] = createItemState()
    return states[no]
  }

  /* ── 常用基础信息（本机保存，可存多套并选择） ────────────
     现场常有多家委托/使用单位，需要保存多套抬头；新建评估默认带入
     最近使用的一套，也可以在基础信息栏的下拉框里切换/应用。 */
  const baseInfoProfiles = ref<BaseInfoProfile[]>([])
  const lastBaseInfoProfileId = ref('')
  let loadedProfileKey = ''

  function resetForm(next: Record<string, string>): void {
    // 必须就地改 form（InfoTable 在 setup 时抓住了它的引用），换对象会让抬头表变空
    for (const key of Object.keys(form.value)) delete form.value[key]
    Object.assign(form.value, next)
  }

  function profileStorage(userId: string | number | null | undefined) {
    return {
      list: profilesStorageKey(userId),
      last: lastProfileStorageKey(userId),
      legacy: baseInfoStorageKey(userId),
    }
  }

  function readStorage(key: string): string | null {
    try {
      return window.localStorage.getItem(key)
    } catch {
      return null
    }
  }

  function writeStorage(key: string, value: string): boolean {
    try {
      window.localStorage.setItem(key, value)
      return true
    } catch {
      return false
    }
  }

  function removeStorage(key: string): void {
    try {
      window.localStorage.removeItem(key)
    } catch {
      // ignore
    }
  }

  function persistProfiles(list: BaseInfoProfile[], lastId: string): boolean {
    const keys = profileStorage(useAuthStore().user?.id)
    const previous = readStorage(keys.list)
    if (!writeStorage(keys.list, JSON.stringify(list))) return false
    if (!writeStorage(keys.last, lastId)) {
      if (previous === null) removeStorage(keys.list)
      else writeStorage(keys.list, previous)
      return false
    }
    return true
  }

  /** 按当前登录账号加载常用信息列表（旧版单套快照自动迁移成一套方案） */
  function ensureBaseInfoLoaded(): void {
    const keys = profileStorage(useAuthStore().user?.id)
    if (loadedProfileKey === keys.list) return
    loadedProfileKey = keys.list
    let list: BaseInfoProfile[] = []
    try {
      const raw = readStorage(keys.list)
      list = sanitizeProfiles(raw ? JSON.parse(raw) : null)
    } catch {
      list = []
    }
    if (!list.length) {
      const legacyRaw = readStorage(keys.legacy)
      if (legacyRaw) {
        try {
          const merged = mergeBaseInfo(createForm(), JSON.parse(legacyRaw))
          const legacy = sanitizeProfiles([
            {
              id: 'legacy',
              name: defaultProfileName(merged),
              values: pickBaseInfo(merged, createForm()),
              updatedAt: new Date().toISOString(),
            },
          ])
          if (legacy.length) {
            list = legacy
            if (writeStorage(keys.list, JSON.stringify(list))) removeStorage(keys.legacy)
          }
        } catch {
          // 旧数据损坏就忽略
        }
      }
    }
    baseInfoProfiles.value = list
    const lastId = readStorage(keys.last)
    lastBaseInfoProfileId.value = list.some((item) => item.id === lastId)
      ? (lastId as string)
      : (list[0]?.id ?? '')
  }

  /** 新建评估的初始抬头：默认值 + 最近使用的那套常用信息 */
  function freshForm(): Record<string, string> {
    ensureBaseInfoLoaded()
    const profile =
      baseInfoProfiles.value.find((item) => item.id === lastBaseInfoProfileId.value) ||
      baseInfoProfiles.value[0]
    return profile ? mergeBaseInfo(createForm(), profile.values) : createForm()
  }

  /** 保存当前抬头为一套常用信息；同名视为覆盖 */
  function saveBaseInfoProfile(name: string): BaseInfoProfile | null {
    ensureBaseInfoLoaded()
    const values = pickBaseInfo(form.value, createForm())
    const finalName = (name || '').trim().slice(0, 40) || defaultProfileName(values)
    const existing = baseInfoProfiles.value.find((item) => item.name === finalName)
    const profile: BaseInfoProfile = {
      id: existing?.id ?? 'p' + Date.now().toString(36) + Math.random().toString(36).slice(2, 6),
      name: finalName,
      values,
      updatedAt: new Date().toISOString(),
    }
    const next = upsertProfile(baseInfoProfiles.value, profile)
    if (!persistProfiles(next, profile.id)) return null
    baseInfoProfiles.value = next
    lastBaseInfoProfileId.value = profile.id
    return profile
  }

  /** 把某套常用信息应用到当前抬头 */
  function applyBaseInfoProfile(id: string): boolean {
    ensureBaseInfoLoaded()
    const profile = baseInfoProfiles.value.find((item) => item.id === id)
    if (!profile) return false
    if (!persistProfiles(baseInfoProfiles.value, profile.id)) return false
    resetForm(mergeBaseInfo(createForm(), profile.values))
    lastBaseInfoProfileId.value = profile.id
    return true
  }

  function deleteBaseInfoProfile(id: string): boolean {
    ensureBaseInfoLoaded()
    const next = removeProfile(baseInfoProfiles.value, id)
    const lastId = lastBaseInfoProfileId.value === id ? (next[0]?.id ?? '') : lastBaseInfoProfileId.value
    if (!persistProfiles(next, lastId)) return false
    baseInfoProfiles.value = next
    lastBaseInfoProfileId.value = lastId
    return true
  }

  function hasSavedBaseInfo(): boolean {
    ensureBaseInfoLoaded()
    return baseInfoProfiles.value.length > 0
  }

  async function loadItems(): Promise<void> {
    if (items.value.length) return
    itemsLoading.value = true
    itemsError.value = ''
    try {
      const res = await reportApi.fetchJteItems()
      items.value = normalize(res.items)
      resetItemStates()
    } catch (err) {
      itemsError.value = err instanceof Error ? err.message : '条目加载失败'
    } finally {
      itemsLoading.value = false
    }
  }

  /** 只重置评价结果，不动抬头信息 */
  function resetItemStates(): void {
    for (const key of Object.keys(states)) delete states[key]
    for (const item of items.value) states[item.no] = createItemState()
  }

  function serializeItems(): ItemAnswer[] {
    return items.value.map((item) => {
      const state = stateOf(item.no)
      return {
        no: item.no,
        result: RESULT_TO_CODE[state.result] ?? '',
        reasons: state.reasons.slice(),
        other_text: state.other ? state.otherText.trim() : '',
      }
    })
  }

  function hydrate(draft: {
    form: Record<string, string>
    items: ItemAnswer[]
    version: number
    status: string
  }): void {
    const wasReady = ready.value
    ready.value = false
    /* 必须**就地改**这个对象，不能整体替换：
       报告预览里的只读信息表（InfoTable）在 setup 时就抓住了 form 的引用，
       换成新对象它还是渲染旧的那份，纸面上的抬头就会全空。 */
    const next = { ...createForm(), ...(draft.form || {}) }
    migrateLegacyFloors(next)
    migrateLegacyUnits(next)
    for (const key of Object.keys(form.value)) delete form.value[key]
    Object.assign(form.value, next)
    for (const item of items.value) {
      const saved = draft.items.find((i) => i.no === item.no)
      const state = createItemState()
      if (saved) {
        state.result = CODE_TO_RESULT[saved.result] ?? ''
        state.reasons = saved.reasons ?? []
        state.other = !!saved.other_text
        state.otherText = saved.other_text ?? ''
      }
      states[item.no] = state
    }
    version.value = draft.version
    status.value = draft.status
    ready.value = wasReady
  }

  /** 进页面时调用：没有当前报告就新建，有就续录 */
  /** 未完成草稿数（含当前这份），「新建评估」前用来决定要不要提醒 */
  async function countDrafts(): Promise<number> {
    try {
      const res = await flowApi.listReports({ status: 'draft', mine: true, size: 1 })
      return res.total
    } catch {
      // 数不出来就不吓唬用户：最多是少弹一次提醒
      return 0
    }
  }

  /** 悬浮岛「新建评估」：显式开一份空白评估。
      不碰当前这份草稿 —— 它仍在库里，去「报告管理」能继续编辑。 */
  async function createNew(): Promise<string> {
    await flush()
    const created = await flowApi.createReport()
    ready.value = false
    reportId.value = created.report.id
    version.value = created.report.version
    status.value = created.report.status
    generated.value = null
    saveState.value = 'idle'
    savedAt.value = ''
    // 新建评估带入本机保存的常用基础信息（没有再回退默认值）
    resetForm(freshForm())
    resetItemStates()
    ready.value = true
    await save()
    return created.report.id
  }

  async function ensureDraft(): Promise<'created' | 'resumed'> {
    if (reportId.value && !draftError.value) return 'resumed'
    draftError.value = ''
    try {
      if (reportId.value) {
        await save()
        return 'resumed'
      }
      // 先看有没有上次没做完的草稿 —— 现场经常是"录一半去下一台，回头接着录"
      const drafts = await flowApi.listReports({ status: 'draft', mine: true, size: 1 })
      if (drafts.items.length) {
        const id = drafts.items[0].id
        await openReport(id)
        return 'resumed'
      }
      const created = await flowApi.createReport()
      reportId.value = created.report.id
      version.value = created.report.version
      status.value = created.report.status
      // 首次进入且没有草稿：同样带入常用基础信息
      resetForm(freshForm())
      await save()
      return 'created'
    } catch (err) {
      draftError.value = err instanceof Error ? err.message : '无法准备评估'
      throw err
    } finally {
      // 只有真正就绪才允许自动保存；失败时保持 false，界面会显示错误与重试
      ready.value = !draftError.value
    }
  }

  /** 立即把待保存的改动写下去（页面隐藏/离开前调用） */
  async function flush(): Promise<void> {
    if (!ready.value || !reportId.value) return
    if (saveTimer === undefined) return
    await save().catch(() => undefined)
  }

  /** 保存当前全部状态（草稿保存的就是全部） */
  async function save(): Promise<void> {
    if (!reportId.value) return
    window.clearTimeout(saveTimer)
    saveTimer = undefined
    saveState.value = 'saving'
    try {
      const res = await flowApi.saveReport(reportId.value, {
        form: form.value,
        items: serializeItems(),
        version: version.value,
      })
      savedAt.value = res.saved_at
      version.value = res.version
      status.value = res.status
      saveState.value = 'saved'
    } catch (err) {
      saveState.value = 'error'
      throw err
    }
  }

  /** 改动后防抖保存：既保证不丢，又不至于每敲一个字写一次盘 */
  function scheduleSave(delay = 800): void {
    if (!ready.value || !reportId.value) return
    generated.value = null
    window.clearTimeout(saveTimer)
    saveTimer = window.setTimeout(() => {
      void save().catch(() => undefined)
    }, delay)
  }

  /** 生成报告：编号、风险评定值、得分等级都由服务端给 */
  async function generate(): Promise<ReportSummary> {
    if (!reportId.value) throw new Error('还没有正在编辑的报告')
    await save()
    const requestedId = reportId.value
    const inputSnapshot = JSON.stringify({ form: form.value, items: serializeItems() })
    // use_llm=true：模型可用就用模型写概况；不可用后端会自动降级，不影响出报告
    const res = await flowApi.generateReport(reportId.value, true)
    const report = res.report
    if (reportId.value !== requestedId || inputSnapshot !== JSON.stringify({ form: form.value, items: serializeItems() })) {
      generated.value = null
      throw new Error('生成期间输入已修改，请保存后重新生成；没有覆盖新输入')
    }
    version.value = report.version
    status.value = report.status
    generated.value = {
      report_no: report.report_no,
      score: report.score,
      grade: report.grade,
      narrative: report.narrative,
      llm_used: Boolean((report.provenance || {}).llm_used),
      risks: report.risks || {},
      generated_at: report.generated_at || '',
      assessment_issues: (report.provenance?.assessment_issues as string[]) || [],
      other_matches: (report.provenance?.other_matches as GeneratedInfo['other_matches']) || [],
    }
    return report
  }

  /** 打开某一份历史报告（报告管理页点「打开」） */
  async function openReport(id: string): Promise<ReportSummary> {
    await flush()
    await loadItems()
    const res = await flowApi.getReport(id)
    const report = res.report
    hydrate({
      form: report.form,
      items: report.items,
      version: report.version,
      status: report.status,
    })
    reportId.value = report.id
    ready.value = true
    generated.value =
      !report.generated_at || (report.status === 'draft' && report.provenance?.result_current !== true)
        ? null
        : {
            report_no: report.report_no,
            score: report.score,
            grade: report.grade,
            narrative: report.narrative,
            llm_used: Boolean((report.provenance || {}).llm_used),
            risks: report.risks || {},
            generated_at: report.generated_at || '',
            assessment_issues: (report.provenance?.assessment_issues as string[]) || [],
            other_matches: (report.provenance?.other_matches as GeneratedInfo['other_matches']) || [],
          }
    return report
  }

  /** 查看已有快照是只读动作，绝不隐式保存或重新评定历史报告。 */
  async function ensurePreview(): Promise<void> {
    if (!generated.value) await generate()
  }

  const counters = computed(() => countItems(items.value, stateOf))
  const missing = computed(() => collectMissing(form.value, items.value, stateOf))

  return {
    items,
    itemsLoading,
    itemsError,
    form,
    states,
    counters,
    missing,
    stateOf,
    loadItems,
    resetItemStates,
    /* 服务端同步 */
    reportId,
    version,
    status,
    generated,
    saveState,
    savedAt,
    ready,
    draftError,
    countDrafts,
    createNew,
    baseInfoProfiles,
    lastBaseInfoProfileId,
    ensureBaseInfoLoaded,
    saveBaseInfoProfile,
    applyBaseInfoProfile,
    deleteBaseInfoProfile,
    hasSavedBaseInfo,
    ensureDraft,
    flush,
    hydrate,
    serializeItems,
    save,
    scheduleSave,
    generate,
    ensurePreview,
    openReport,
  }
})
