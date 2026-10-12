import { describe, expect, it } from 'vitest'
import { computeG, countByCategory, gradeOf, type RiskCategory } from './riskScore'

describe('computeG（附录A 综合安全状况得分）', () => {
  it('无风险情节时视为满分', () => {
    expect(computeG([])).toBe(100)
  })

  it('全部 Ⅲ 类 → 100 分', () => {
    const cats: RiskCategory[] = ['Ⅲ类', 'Ⅲ类', 'Ⅲ类']
    expect(computeG(cats)).toBe(100)
  })

  it('存在 Ⅰ 类 → 一票否决，0 分', () => {
    expect(computeG(['Ⅰ类', 'Ⅲ类', 'Ⅲ类'])).toBe(0)
  })

  it('全部 Ⅱ 类 → Σv < 0，0 分', () => {
    expect(computeG(['Ⅱ类', 'Ⅱ类'])).toBe(0)
  })

  it('混合且 Σv ≥ 0 → 按 G = 100·Σv/(2n) 计算', () => {
    // Σv = 2 + 2 - 1 = 3，n = 3 → 100×3/(2×3) = 50
    expect(computeG(['Ⅲ类', 'Ⅲ类', 'Ⅱ类'])).toBe(50)
    // Σv = 2 + 2 = 4，n = 4 → 100×4/8 = 50
    expect(computeG(['Ⅲ类', 'Ⅲ类', 'Ⅲ类', 'Ⅲ类'])).toBe(100)
  })
})

describe('gradeOf（表A.2 综合安全状况等级）', () => {
  it('按区间判定，边界值归入较高等级', () => {
    expect(gradeOf(100)).toBe('一级')
    expect(gradeOf(90)).toBe('一级')
    expect(gradeOf(89.99)).toBe('二级')
    expect(gradeOf(75)).toBe('二级')
    expect(gradeOf(74.99)).toBe('三级')
    expect(gradeOf(60)).toBe('三级')
    expect(gradeOf(59.99)).toBe('四级')
    expect(gradeOf(0)).toBe('四级')
  })
})

describe('countByCategory', () => {
  it('按类别计数', () => {
    expect(countByCategory(['Ⅰ类', 'Ⅱ类', 'Ⅱ类', 'Ⅲ类'])).toEqual({
      'Ⅰ类': 1,
      'Ⅱ类': 2,
      'Ⅲ类': 1,
    })
  })
})
