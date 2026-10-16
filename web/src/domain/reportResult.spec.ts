import { describe, expect, it } from 'vitest'
import { createSSRApp } from 'vue'
import { renderToString } from '@vue/server-renderer'
import AppendixA from '@/components/report/AppendixA.vue'
import { buildAppendixRows } from './reportResult'
import type { RiskValue } from './riskAssign'

describe('专家风险生成结果', () => {
  it('同项目附页统一显示最终类别但保留各风险和措施', () => {
    const risks: Record<string, RiskValue> = {
      '16.1': {
        severity: 2, probability: 'B', category: 'Ⅰ类',
        selected_risks: [
          { key: '16.1:01', text: '风险甲', category: 'I', measure: '措施甲' },
          { key: '16.1:32', text: '风险乙', category: 'II', measure: '措施乙' },
        ],
      },
    }
    const rows = buildAppendixRows(
      [{ no: '16.1', name: '控制柜', sub: '', req: [], opts: [] }],
      () => ({ result: '不符合', reasons: [], other: false, otherText: '' }), risks,
    )
    expect(rows).toHaveLength(2)
    expect(rows.map(r => [r.text, r.risk.category, r.measure])).toEqual([
      ['风险甲', 'Ⅰ类', '措施甲'], ['风险乙', 'Ⅰ类', '措施乙'],
    ])
    expect(new Set(rows.map(r => r.key)).size).toBe(2)
  })

  it('旧报告没有逐风险快照时仍展示原有文字', () => {
    const rows = buildAppendixRows(
      [{ no: '1.7', name: '工作空间', sub: '', req: [], opts: [] }],
      () => ({ result: '不符合', reasons: ['原报告风险'], other: true, otherText: '补充文字' }),
      { '1.7': { severity: 2, probability: 'D', category: 'Ⅱ类' } },
    )
    expect(rows).toHaveLength(1)
    expect(rows[0].text).toBe('原报告风险；补充文字')
  })

  it('未确认的计分不能在附录显示为满分或一级', async () => {
    const html = await renderToString(createSSRApp(AppendixA, { categories: ['Ⅲ类'], g: null, grade: null }))
    expect(html).toContain('暂不输出综合得分和等级')
    expect(html).not.toContain('本次判定结果：')
    expect(html).not.toContain('计分口径待确认')
  })
})
