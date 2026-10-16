import type { RiskValue } from '@/domain/riskAssign'

/** 附页一行：项目编号 + 风险评定值 + 「存在风险」文本 */
export interface AppendixRow {
  key: string
  no: string
  risk: RiskValue
  text: string
  measure: string
}
