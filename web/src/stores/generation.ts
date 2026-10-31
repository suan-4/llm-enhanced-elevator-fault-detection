import { defineStore } from 'pinia'
import { ref } from 'vue'
import type { KgSelection } from '@/api/reports'

/* 人工确认页把选择交给报告页后再生成：
   这样用户点「生成报告」后会先回到报告录入页，
   在填写区底部看到文本分析报告的流式打字机，而不是停在确认页。 */
export const useGenerationStore = defineStore('generation', () => {
  const pendingSelections = ref<KgSelection[] | null>(null)
  const replayReportId = ref('')

  function setPending(selections: KgSelection[]): void {
    pendingSelections.value = selections
  }

  function consume(): KgSelection[] | null {
    const value = pendingSelections.value
    pendingSelections.value = null
    return value
  }

  function requestReplay(reportId: string): void {
    replayReportId.value = reportId
  }

  function consumeReplay(reportId: string): boolean {
    if (replayReportId.value !== reportId) return false
    replayReportId.value = ''
    return true
  }

  return { pendingSelections, replayReportId, setPending, consume,
    requestReplay, consumeReplay }
})
