import { describe, expect, it } from 'vitest'
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
} from './baseInfo'

const DEFAULTS: Record<string, string> = {
  clientName: '',
  userName: '',
  deviceCategory: '',
  productNo: '',
  installSite: '/',
  floors: '',
}

describe('profilesStorageKey / lastProfileStorageKey', () => {
  it('在基础信息键上扩展，按账号分开', () => {
    expect(profilesStorageKey('7')).toBe('elevator.baseInfo.v1.u7.profiles')
    expect(lastProfileStorageKey('7')).toBe('elevator.baseInfo.v1.u7.last')
    expect(profilesStorageKey()).toBe('elevator.baseInfo.v1.profiles')
  })
})

describe('sanitizeProfiles', () => {
  const good = { id: 'a', name: '方案A', values: { clientName: '甲' }, updatedAt: 't' }

  it('保留合法方案，丢弃坏数据并截断为 20 套', () => {
    const many = Array.from({ length: 25 }, (_, i) => ({ ...good, id: 'p' + i, name: '方案' + i }))
    const list = sanitizeProfiles([good, null, 'x', { name: '', values: {} }, { name: '坏', values: 1 }, ...many])
    expect(list.length).toBe(20)
    expect(list[0].name).toBe('方案A')
    expect(list[0].values.clientName).toBe('甲')
  })

  it('非数组输入返回空列表', () => {
    expect(sanitizeProfiles(null)).toEqual([])
    expect(sanitizeProfiles({})).toEqual([])
  })
})

describe('upsertProfile / removeProfile', () => {
  const make = (id: string, name: string): BaseInfoProfile => ({
    id,
    name,
    values: {},
    updatedAt: '',
  })

  it('新增排最前，同名/同 id 视为更新', () => {
    const a = make('a', '甲')
    const b = make('b', '乙')
    let list = upsertProfile([], a)
    list = upsertProfile(list, b)
    expect(list.map((p) => p.name)).toEqual(['乙', '甲'])
    const a2 = { ...a, values: { clientName: '甲改' } }
    list = upsertProfile(list, a2)
    expect(list.map((p) => p.name)).toEqual(['乙', '甲'])
    expect(list.find((p) => p.id === 'a')?.values.clientName).toBe('甲改')
  })

  it('删除按 id 过滤', () => {
    const list = [make('a', '甲'), make('b', '乙')]
    expect(removeProfile(list, 'a').map((p) => p.id)).toEqual(['b'])
  })
})

describe('defaultProfileName', () => {
  it('优先“委托单位 / 使用单位”，兜底产品编号/默认名', () => {
    expect(defaultProfileName({ clientName: '甲', userName: '乙' })).toBe('甲 / 乙')
    expect(defaultProfileName({ clientName: '甲', userName: '甲' })).toBe('甲')
    expect(defaultProfileName({ productNo: 'P-1' })).toBe('P-1')
    expect(defaultProfileName({})).toBe('常用基础信息')
  })
})

describe('baseInfoStorageKey', () => {
  it('按账号分开存储；没有账号时用公共前缀', () => {
    expect(baseInfoStorageKey()).toBe('elevator.baseInfo.v1')
    expect(baseInfoStorageKey('')).toBe('elevator.baseInfo.v1')
    expect(baseInfoStorageKey('1065')).toBe('elevator.baseInfo.v1.u1065')
    expect(baseInfoStorageKey(1065)).toBe('elevator.baseInfo.v1.u1065')
  })
})

describe('pickBaseInfo', () => {
  it('只保留表单定义字段，忽略 __ 计算字段与非字符串', () => {
    const form = {
      clientName: '某某公司',
      productNo: 'P-1',
      installSite: '/',
      __overview: 'x',
      unknown: 'drop',
      floors: 18 as unknown as string,
    }
    expect(pickBaseInfo(form, DEFAULTS)).toEqual({
      clientName: '某某公司',
      userName: '',
      deviceCategory: '',
      productNo: 'P-1',
      installSite: '/',
      floors: '',
    })
  })
})

describe('mergeBaseInfo', () => {
  it('用保存值覆盖默认值，未知键/非字符串忽略', () => {
    const merged = mergeBaseInfo(DEFAULTS, {
      clientName: '某某公司',
      floors: '18',
      unknown: 'x',
      productNo: 123,
    })
    expect(merged.clientName).toBe('某某公司')
    expect(merged.floors).toBe('18')
    expect(merged.productNo).toBe('')
    expect('unknown' in merged).toBe(false)
  })

  it('保存内容损坏时回退默认值', () => {
    expect(mergeBaseInfo(DEFAULTS, null)).toEqual(DEFAULTS)
    expect(mergeBaseInfo(DEFAULTS, 'bad')).toEqual(DEFAULTS)
    expect(mergeBaseInfo(DEFAULTS, ['x'])).toEqual(DEFAULTS)
  })
})