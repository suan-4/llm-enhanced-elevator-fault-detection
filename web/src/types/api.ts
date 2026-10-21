/* 与后端契约对应的类型。字段名与后端返回保持一致（snake_case）。 */

export type UserRole = 'admin' | 'inspector'

export interface User {
  id: number
  username: string
  display_name: string
  role: UserRole
  is_active: boolean
  created_at: string
  last_login_at: string | null
}

export interface LoginResponse {
  success: boolean
  token: string
  expires_at: string
  user: User
}

export interface MeResponse {
  success: boolean
  user: User
}

/** 模板条目：由 JTE-09-R02-3.00 抽取，编号与模板评价结果表行序一致 */
export interface JteItem {
  /** 项目编号，如 1.7、12.10 */
  no: string
  /** 项目名称 */
  name: string
  /** 子项名称（钢丝绳、包覆绳等纵向合并单元格才有） */
  sub: string
  /** 评价内容与要求的全部行 */
  req: string[]
  /** 可作为「不符合」候选的情形条款（a) b) c) 形式） */
  opts: string[]
}

export interface JteItemsResponse {
  success: boolean
  items: JteItem[]
}

export interface ExportResponse {
  success: boolean
  report_id: string
  status: 'filed'
  version: number
  result_digest: string
  sha256: string
  exported_at: string
  fmt: string
  filename: string
  path: string
  dir: string
  size: number
}
