import { describe, expect, it } from 'vitest'
import {
  collectMissing,
  countItems,
  createItemState,
  isFieldMissing,
  itemProblem,
  reasonList,
  reasonsText,
} from './validation'
import type { JteItem } from '@/types/api'

function makeItem(no: string, name = '项目'): JteItem {
  return { no, name, sub: '', req: ['要求'], opts: ['a)情形一', 'b)情形二'] }
}

describe('itemProblem（条目漏填判定）', () => {
  it('新条目默认「符合」，直接通过', () => {
    expect(createItemState().result).toBe('符合')
    expect(itemProblem(createItemState())).toBe('')
  })

  it('旧草稿残留的空结果仍算未填', () => {
    expect(itemProblem({ ...createItemState(), result: '' })).toBe('未选择评价结果')
  })

  it('符合 / 无此项 直接通过', () => {
    expect(itemProblem({ ...createItemState(), result: '符合' })).toBe('')
    expect(itemProblem({ ...createItemState(), result: '无此项' })).toBe('')
  })

  it('不符合但未填任何情形', () => {
    expect(itemProblem({ ...createItemState(), result: '不符合' })).toBe(
      '选择了「不符合」但未填写具体情形',
    )
  })

  it('勾选已有情形即通过', () => {
    const state = { ...createItemState(), result: '不符合' as const, reasons: ['a)情形一'] }
    expect(itemProblem(state)).toBe('')
  })

  it('勾选「其他」但内容为空不算通过', () => {
    const state = { ...createItemState(), result: '不符合' as const, other: true, otherText: '   ' }
    expect(itemProblem(state)).toBe('选择了「不符合」但未填写具体情形')
  })

  it('其他分支的未填写内容不能被停用的清单缓存掩盖', () => {
    expect(itemProblem({ ...createItemState(), result: '不符合', reasons: ['缓存'],
      other: true, otherText: '', legacyCombined: false })).not.toBe('')
  })

  it('勾选「其他」并填写内容即通过', () => {
    const state = {
      ...createItemState(),
      result: '不符合' as const,
      other: true,
      otherText: '现场实测净高不足',
    }
    expect(itemProblem(state)).toBe('')
  })
})

describe('reasonList / reasonsText（不符合项明细）', () => {
  it('多个清单项按顺序全部保留', () => {
    const state = {
      ...createItemState(),
      result: '不符合' as const,
      reasons: ['情形一。', '情形二。'],
    }
    expect(reasonList(state)).toEqual(['情形一。', '情形二。'])
  })

  it('勾选「其他」并自行填写时，填写内容也算不符合项', () => {
    const state = {
      ...createItemState(),
      result: '不符合' as const,
      other: true,
      otherText: '  现场自行描述的内容  ',
    }
    expect(reasonList(state)).toEqual(['现场自行描述的内容'])
    expect(reasonsText(state)).toBe('现场自行描述的内容')
  })

  it('旧报告同时存在清单项与「其他」文字时两者都保留', () => {
    const state = {
      ...createItemState(),
      result: '不符合' as const,
      reasons: ['情形一'],
      other: true,
      otherText: '补充文字',
      legacyCombined: true,
    }
    expect(reasonList(state)).toEqual(['情形一', '补充文字'])
  })

  it('拼接时去掉非末条句号，避免出现「。；」', () => {
    const state = {
      ...createItemState(),
      result: '不符合' as const,
      reasons: ['情形一。', '情形二。', '情形三。'],
    }
    expect(reasonsText(state)).toBe('情形一；情形二；情形三。')
  })
})

describe('isFieldMissing（必填字段判定）', () => {
  it('空值与占位符「/」都算未填', () => {
    expect(isFieldMissing('')).toBe(true)
    expect(isFieldMissing('   ')).toBe(true)
    expect(isFieldMissing('/')).toBe(true)
    expect(isFieldMissing(undefined)).toBe(true)
    expect(isFieldMissing('曳引驱动电梯')).toBe(false)
  })
})

describe('collectMissing', () => {
  const items = [makeItem('1.7', '机房工作安全空间'), makeItem('1.9', '限速器')]

  it('同时收集必填字段与条目漏填', () => {
    const form = { clientName: '', userName: '使用单位', deviceVariety: '/', productNo: 'X1' }
    const states: Record<string, ReturnType<typeof createItemState>> = {
      '1.7': { ...createItemState(), result: '符合' },
      '1.9': { ...createItemState(), result: '' },
    }
    const missing = collectMissing(form, items, (no) => states[no])
    expect(missing.map((m) => m.key)).toEqual(['clientName', 'deviceVariety', '1.9'])
    expect(missing[2].why).toBe('未选择评价结果')
  })

  it('全部填妥时无漏填项', () => {
    const form = {
      clientName: '委托单位',
      userName: '使用单位',
      deviceVariety: '曳引驱动乘客电梯',
      productNo: 'P-001',
    }
    const states = {
      '1.7': { ...createItemState(), result: '符合' as const },
      '1.9': { ...createItemState(), result: '不符合' as const, reasons: ['a)情形一'] },
    }
    expect(collectMissing(form, items, (no) => states[no as '1.7' | '1.9'])).toEqual([])
  })
})

describe('countItems', () => {
  it('统计总数、已评、不符合与漏填', () => {
    const items = [makeItem('1.7'), makeItem('1.9'), makeItem('2.1')]
    const states = {
      '1.7': { ...createItemState(), result: '符合' as const },
      '1.9': { ...createItemState(), result: '不符合' as const, reasons: ['a)情形一'] },
      '2.1': { ...createItemState(), result: '' as const },
    }
    expect(countItems(items, (no) => states[no as '1.7' | '1.9' | '2.1'])).toEqual({
      total: 3,
      done: 2,
      unfit: 1,
      miss: 1,
    })
  })
})
