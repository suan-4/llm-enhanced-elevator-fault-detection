/** Operator-only notice; never part of the printable report. */
interface ModelEvidence {
  llm_used: boolean | null
  llm_status?: string
  llm_error_code?: string
  loaded_from_history?: boolean
  other_matches?: unknown[]
}

const REASONS: Record<string, string> = {
  context_budget_exceeded: '输入超过模型预算，未截断原始资料',
  tokenizer_unavailable: '离线分词组件不可用',
  tokenizer_mismatch: '分词文件校验失败',
  tokenizer_uncalibrated: '分词校准未就绪',
  model_mismatch: '模型与分词校准不匹配',
  model_budget_config_invalid: '模型预算配置无效',
  model_empty_response: '模型返回空内容',
  model_not_finished: '模型未正常完成',
  model_output_truncated: '模型回答不完整',
  model_response_invalid: '模型结果未通过验证',
  model_unavailable: '模型服务不可用',
  model_timeout: '模型调用超时',
}

export function modelStatus(evidence: ModelEvidence | null): string {
  if (!evidence) return ''
  const saved = evidence.loaded_from_history ? '正在查看已保存的预览，本次未重新调用模型。' : ''
  const matching = evidence.other_matches?.length ? '风险匹配已使用模型，请核对匹配结果。' : ''
  if (evidence.llm_used === true) return `${saved}模型概况已生成。${matching}`
  if (evidence.llm_used === null) return `${saved}历史记录的模型参与状态未记录。${matching}`
  const reason = evidence.llm_status === 'not_requested'
    ? '未请求模型概况' : REASONS[evidence.llm_error_code ?? ''] ?? '模型概况未成功生成或未记录失败原因'
  return `${saved}当前概况采用规则摘要：${reason}。${matching}风险类别与得分仍按已确认规则计算。`
}
