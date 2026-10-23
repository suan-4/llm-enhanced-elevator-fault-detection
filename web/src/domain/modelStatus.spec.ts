import { describe, expect, it } from 'vitest'
import { modelStatus } from './modelStatus'

describe('model participation notices', () => {
  it('distinguishes an old preview from a new model invocation', () => {
    const notice = modelStatus({ llm_used: true, loaded_from_history: true })
    expect(notice).toContain('已保存的预览')
    expect(notice).toContain('未重新调用模型')
    expect(notice).toContain('模型概况已生成')
  })
  it('does not treat missing legacy evidence as model success or failure', () => {
    expect(modelStatus({ llm_used: null })).toContain('模型参与状态未记录')
  })
  it('separates successful risk matching from a degraded overview', () => {
    const notice = modelStatus({ llm_used: false, llm_status: 'degraded',
      llm_error_code: 'context_budget_exceeded', other_matches: [{}] })
    expect(notice).toContain('规则摘要')
    expect(notice).toContain('输入超过模型预算')
    expect(notice).toContain('风险匹配已使用模型')
    expect(notice).not.toContain('模型概况已生成')
  })
  it('shows controlled explanations without publishing arbitrary backend errors', () => {
    expect(modelStatus({ llm_used: false, llm_error_code: 'tokenizer_uncalibrated' })).toContain('分词校准未就绪')
    expect(modelStatus({ llm_used: false, llm_status: 'not_requested' })).toContain('未请求模型概况')
    expect(modelStatus({ llm_used: false, llm_error_code: 'SECRET password' })).not.toContain('SECRET')
    expect(modelStatus(null)).toBe('')
  })
})
