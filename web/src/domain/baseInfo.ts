/* 常用基础信息本地保存：委托单位、使用单位、设备类别、层站门等
   填过一次后，新建评估时自动带入，减少现场重复录入。
   只存在本机 localStorage（板端 WebView 跨重启仍在），并按登录账号分开。 */
const PREFIX = 'elevator.baseInfo.v1'

export function baseInfoStorageKey(userId?: string | number | null): string {
  if (userId === undefined || userId === null || userId === '') return PREFIX
  return PREFIX + '.u' + String(userId)
}

/** 从表单里摘出要保存的基础信息（只保留表单定义的字段，忽略非字符串） */
export function pickBaseInfo(
  form: Record<string, string>,
  defaults: Record<string, string>,
): Record<string, string> {
  const out: Record<string, string> = {}
  for (const key of Object.keys(defaults)) {
    if (key.startsWith('__')) continue
    const value = form[key]
    // 缺字段/非字符串（历史数据）回退默认值，保证保存下来是一份完整抬头
    out[key] = typeof value === 'string' ? value : defaults[key]
  }
  return out
}

/** 用保存的基础信息覆盖默认值；未知键、非字符串值一律忽略，防止旧数据带坏表单 */
export function mergeBaseInfo(
  defaults: Record<string, string>,
  saved: unknown,
): Record<string, string> {
  const out = { ...defaults }
  if (!saved || typeof saved !== 'object' || Array.isArray(saved)) return out
  const record = saved as Record<string, unknown>
  for (const key of Object.keys(defaults)) {
    if (typeof record[key] === 'string') out[key] = record[key] as string
  }
  return out
}

/** 一套常用基础信息（现场常有多家委托/使用单位，需要保存多套供选择） */
export interface BaseInfoProfile {
  id: string
  name: string
  values: Record<string, string>
  updatedAt: string
}

/** 常用基础信息列表的存储键（按账号分开） */
export function profilesStorageKey(userId?: string | number | null): string {
  return baseInfoStorageKey(userId) + '.profiles'
}

/** 最近使用/应用到的那套配置的存储键 */
export function lastProfileStorageKey(userId?: string | number | null): string {
  return baseInfoStorageKey(userId) + '.last'
}

/** 清洗本地存储里的方案列表：坏数据直接丢弃，最多保留 20 套 */
export function sanitizeProfiles(raw: unknown): BaseInfoProfile[] {
  if (!Array.isArray(raw)) return []
  const out: BaseInfoProfile[] = []
  for (const item of raw) {
    if (!item || typeof item !== 'object') continue
    const record = item as Record<string, unknown>
    const name = typeof record.name === 'string' ? record.name.trim().slice(0, 40) : ''
    if (!name) continue
    if (!record.values || typeof record.values !== 'object' || Array.isArray(record.values)) continue
    const values: Record<string, string> = {}
    for (const [key, value] of Object.entries(record.values as Record<string, unknown>)) {
      if (typeof value === 'string') values[key] = value
    }
    out.push({
      id: typeof record.id === 'string' && record.id ? record.id : 'p' + out.length + '-' + name,
      name,
      values,
      updatedAt: typeof record.updatedAt === 'string' ? record.updatedAt : '',
    })
    if (out.length >= 20) break
  }
  return out
}

/** 新增/更新一套方案（同名或同 id 视为更新），最新保存的排最前 */
export function upsertProfile(
  list: BaseInfoProfile[],
  profile: BaseInfoProfile,
): BaseInfoProfile[] {
  const index = list.findIndex((item) => item.id === profile.id || item.name === profile.name)
  if (index >= 0) {
    const next = list.slice()
    next[index] = profile
    return next
  }
  return [profile, ...list].slice(0, 20)
}

export function removeProfile(list: BaseInfoProfile[], id: string): BaseInfoProfile[] {
  return list.filter((item) => item.id !== id)
}

/** 默认方案名：优先「委托单位 / 使用单位」，没有就按设备/产品编号兜底 */
export function defaultProfileName(values: Record<string, string>): string {
  const client = (values.clientName || '').trim()
  const user = (values.userName || '').trim()
  if (client && user && client !== user) return client + ' / ' + user
  const fallback = client || user || (values.productNo || '').trim()
  return fallback ? fallback.slice(0, 40) : '常用基础信息'
}
