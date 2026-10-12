/* ⚠ 占位实现

   真实的「风险评定值」（严重程度 / 概率等级 / 风险类别）应由知识图谱查询
   加算法判定给出，取值规则尚未确认（见 PRD 的 Q4）。

   规则确定后，本文件应改为调用后端接口，由后端返回三列取值；
   在此之前，报告预览用这里的演示值占位。 */

import type { RiskCategory } from './riskScore'

export interface RiskValue {
  severity: number
  probability: string
  category: RiskCategory
}

export function assignRiskDemo(index: number): RiskValue {
  const severity = [4, 3, 4, 5][index % 4]
  const probability = ['B', 'C', 'B', 'A'][index % 4]
  const category: RiskCategory = index % 4 === 0 ? 'Ⅰ类' : 'Ⅱ类'
  return { severity, probability, category }
}
