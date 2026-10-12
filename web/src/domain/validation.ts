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
}

export function createItemState(): ItemState {
  return { result: '', reasons: [], other: false, otherText: '' }
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
  { key: 'deviceCategory', label: '设备类别' },
  { key: 'productNo', label: '产品编号' },
] as const

export type FormValues = Record<string, string>

/** 单条目的漏填原因；返回空串表示无问题 */
export function itemProblem(state: ItemState): string {
  if (!state.result) return '未选择评价结果'
  if (
    state.result === '不符合' &&
    state.reasons.length === 0 &&
    !(state.other && state.otherText.trim())
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

/** 「存在风险」列文本：已勾选情形 + 其他自由填写 */
export function reasonsText(state: ItemState): string {
  const parts = state.reasons.slice()
  if (state.other && state.otherText.trim()) parts.push(state.otherText.trim())
  return parts.join('；')
}
