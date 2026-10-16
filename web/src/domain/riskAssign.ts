/* 风险评定值来自服务端专家材料查表；前端不再自行生成演示风险值。 */

import type { RiskCategory } from './riskScore'

export interface RiskValue {
  severity: number | null
  probability: string | null
  category: RiskCategory
  issue?: string
  selected_risks?: SelectedRisk[]
}

export interface SelectedRisk {
  key: string
  text: string
  category: 'I' | 'II' | 'III'
  measure: string
}
