/* 漏填判定 —— 纯函数，无副作用。
   判定结果既用于顶部提示条，也用于底部的计数。 */

import type { JteItem } from '@/types/api'

export type ItemResult = '' | '符合' | '不符合' | '无此项'

export interface ItemState {
  result: ItemResult
  /** 已勾选的情形条款原文 */
  reasons: string[]
  /** 是否勾选「其他」 */
  other: boolean
  /** 「其他」的自由填写内容 */
  otherText: string
  /** Historical reports may contain both inputs; never silently discard either. */
  legacyCombined?: boolean
}

/** 新条目默认「符合」：现场只关注例外项，逐条点 66 次「符合」不现实。
    未填状态只可能来自旧草稿（result 为空串），仍会触发定位提示。 */
export function createItemState(): ItemState {
  return { result: '符合', reasons: [], other: false, otherText: '' }
}

export interface MissingEntry {
  kind: 'field' | 'item'
  /** 必填字段用字段 key；条目用项目编号 */
  key: string
  label: string
  why: string
}

export const REQUIRED_FIELDS = [
  { key: 'clientName', label: '委托单位名称' },
  { key: 'userName', label: '使用单位名称' },
  { key: 'deviceVariety', label: '设备品种' },
  { key: 'productNo', label: '产品编号' },
] as const

export type FormValues = Record<string, string>

/** 单条目的漏填原因；返回空串表示无问题 */
export function itemProblem(state: ItemState): string {
  if (!state.result) return '未选择评价结果'
  if (
    state.result === '不符合' &&
    !(state.other && state.otherText.trim()) &&
    !(state.reasons.length && (!state.other || state.legacyCombined))
  ) {
    return '选择了「不符合」但未填写具体情形'
  }
  return ''
}

/** 必填字段判定：空字符串或占位符「/」都算未填 */
export function isFieldMissing(value: string | undefined): boolean {
  const v = (value ?? '').trim()
  return v === '' || v === '/'
}

export function collectMissing(
  form: FormValues,
  items: JteItem[],
  stateOf: (no: string) => ItemState,
): MissingEntry[] {
  const missing: MissingEntry[] = []

  for (const field of REQUIRED_FIELDS) {
    if (isFieldMissing(form[field.key])) {
      missing.push({ kind: 'field', key: field.key, label: field.label, why: '未填写（必填）' })
    }
  }

  for (const item of items) {
    const why = itemProblem(stateOf(item.no))
    if (why) {
      missing.push({ kind: 'item', key: item.no, label: item.name, why })
    }
  }

  return missing
}

export interface ItemCounters {
  total: number
  done: number
  unfit: number
  miss: number
}

export function countItems(items: JteItem[], stateOf: (no: string) => ItemState): ItemCounters {
  let done = 0
  let unfit = 0
  let miss = 0
  for (const item of items) {
    const state = stateOf(item.no)
    if (state.result) done += 1
    if (state.result === '不符合') unfit += 1
    if (itemProblem(state)) miss += 1
  }
  return { total: items.length, done, unfit, miss }
}

/** 不符合项明细列表：勾选的情形 + 「其他」自行填写的内容。
    清单项与「其他」二选一，但历史草稿可能两者都有（legacyCombined），都要保留。 */
export function reasonList(state: ItemState): string[] {
  const list = (state.other && state.legacyCombined === false ? [] : state.reasons.slice())
    .map((text) => text.trim())
    .filter(Boolean)
  if (state.other && state.otherText.trim()) list.push(state.otherText.trim())
  return list
}

/** 非末条去掉收尾标点：条文本身多以「。」结尾，
    直接拼接会出现「。；」，读起来像两句话没接上；末条保留原有结尾。 */
function trimMiddleReason(text: string): string {
  return text.trim().replace(/[。；;，,、\s]+$/g, '')
}

/** 「存在风险」列文本：不符合项明细，多条用「；」连接 */
export function reasonsText(state: ItemState): string {
  const parts = reasonList(state)
  if (!parts.length) return ''
  return parts
    .map((text, i) => (i === parts.length - 1 ? text : trimMiddleReason(text)))
    .join('；')
}
