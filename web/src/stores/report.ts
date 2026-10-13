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
  risks: Record<string, RiskValue>
  generated_at: string
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
    ratedLoad: '/ kg',
    ratedSpeed: '/ m/s',
    floorsStopsDoors: '/ 层　/ 站　/ 门',
    controlMode: '/',
    instruments:
      '温湿度计、万用表、绝缘电阻仪、转速表、钢卷尺、钢直尺、塞尺、游标卡尺、钳形电流表、照度计、乘运质量测试仪、声级计等',
    basis:
      '1、GB/T 42615-2023《在用电梯安全评估规范》　2、技术服务合同/协议（合同/协议编号：　　　　）',
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
    /* 必须**就地改**这个对象，不能整体替换：
       报告预览里的只读信息表（InfoTable）在 setup 时就抓住了 form 的引用，
       换成新对象它还是渲染旧的那份，纸面上的抬头就会全空。 */
    const next = { ...createForm(), ...(draft.form || {}) }
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
  }

  /** 进页面时调用：没有当前报告就新建，有就续录 */
  async function ensureDraft(): Promise<'created' | 'resumed'> {
    if (reportId.value) return 'resumed'
    draftError.value = ''
    try {
      // 先看有没有上次没做完的草稿 —— 现场经常是"录一半去下一台，回头接着录"
      const drafts = await flowApi.listReports({ status: 'draft', mine: true, size: 1 })
      if (drafts.items.length) {
        const id = drafts.items[0].id
        const draft = await flowApi.getDraft(id)
        hydrate(draft)
        reportId.value = id
        return 'resumed'
      }
      const created = await flowApi.createReport()
      reportId.value = created.report.id
      version.value = created.report.version
      status.value = created.report.status
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
    saveState.value = 'saving'
    try {
      const res = await flowApi.saveReport(reportId.value, {
        form: form.value,
        items: serializeItems(),
        version: version.value,
      })
      savedAt.value = res.saved_at
      saveState.value = 'saved'
    } catch (err) {
      saveState.value = 'error'
      throw err
    }
  }

  /** 改动后防抖保存：既保证不丢，又不至于每敲一个字写一次盘 */
  function scheduleSave(delay = 800): void {
    if (!ready.value || !reportId.value) return
    window.clearTimeout(saveTimer)
    saveTimer = window.setTimeout(() => {
      void save().catch(() => undefined)
    }, delay)
  }

  /** 生成报告：编号、风险评定值、得分等级都由服务端给 */
  async function generate(): Promise<ReportSummary> {
    if (!reportId.value) throw new Error('还没有正在编辑的报告')
    await save()
    const res = await flowApi.generateReport(reportId.value)
    const report = res.report
    version.value = report.version
    status.value = report.status
    generated.value = {
      report_no: report.report_no,
      score: report.score,
      grade: report.grade,
      narrative: report.narrative,
      risks: report.risks || {},
      generated_at: report.generated_at || '',
    }
    return report
  }

  /** 打开某一份历史报告（报告管理页点「打开」） */
  async function openReport(id: string): Promise<ReportSummary> {
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
      report.status === 'draft'
        ? null
        : {
            report_no: report.report_no,
            score: report.score,
            grade: report.grade,
            narrative: report.narrative,
            risks: report.risks || {},
            generated_at: report.generated_at || '',
          }
    return report
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
    ensureDraft,
    flush,
    hydrate,
    serializeItems,
    save,
    scheduleSave,
    generate,
    openReport,
  }
})
