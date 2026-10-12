/* 风险定级与综合得分 —— 规范定义的确定性计算。
   这部分必须可单测、结果可复现；大模型只负责文字表述，不参与定级。 */

export type RiskCategory = 'Ⅰ类' | 'Ⅱ类' | 'Ⅲ类'

/** 表A.1 风险类别分值 */
export const CAT_VALUE: Record<RiskCategory, number> = {
  'Ⅰ类': 0,
  'Ⅱ类': -1,
  'Ⅲ类': 2,
}

/** 附页「降低风险措施」文本。
    Ⅰ、Ⅱ 类取自模板样例；Ⅲ 类模板未给出样例，暂沿用 Ⅱ 类表述，待业务方确认。 */
export const CAT_MEASURE: Record<RiskCategory, string> = {
  'Ⅰ类': '建议结合技术及经济可行性，加装或改进安全保护装置（措施）来消除或降低风险。',
  'Ⅱ类': '应采用修理、调整、更换等措施消除或降低风险。',
  'Ⅲ类': '应采用修理、调整、更换等措施消除或降低风险。',
}

/**
 * 附录A 综合安全状况得分：
 *   G = 100 · Σv / (2n)   当所有 v ≠ 0
 *   G = 0                 当存在 v = 0（即 Ⅰ 类，一票否决）或 Σv < 0
 * 无风险情节时视为 100 分。
 */
export function computeG(categories: RiskCategory[]): number {
  const n = categories.length
  if (n === 0) return 100

  let sum = 0
  let hasZero = false
  for (const cat of categories) {
    const value = CAT_VALUE[cat]
    if (value === 0) hasZero = true
    sum += value
  }

  if (hasZero || sum < 0) return 0
  return Math.round(((100 * sum) / (2 * n)) * 100) / 100
}

export type Grade = '一级' | '二级' | '三级' | '四级'

/** 表A.2 综合安全状况等级 */
export function gradeOf(g: number): Grade {
  if (g >= 90) return '一级'
  if (g >= 75) return '二级'
  if (g >= 60) return '三级'
  return '四级'
}

export interface RiskCount {
  'Ⅰ类': number
  'Ⅱ类': number
  'Ⅲ类': number
}

export function countByCategory(categories: RiskCategory[]): RiskCount {
  const count: RiskCount = { 'Ⅰ类': 0, 'Ⅱ类': 0, 'Ⅲ类': 0 }
  for (const cat of categories) count[cat] += 1
  return count
}

/** 评估概况文案，用于报告正文页 */
export function overviewText(categories: RiskCategory[], g: number): string {
  const count = countByCategory(categories)
  return `1、存在Ⅰ类风险　${count['Ⅰ类']}　项，Ⅱ类风险　${count['Ⅱ类']}　项。\n2、综合安全状况得分：${g}`
}
