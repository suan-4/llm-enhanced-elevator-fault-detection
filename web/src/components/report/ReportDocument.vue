<script setup lang="ts">
/* 报告正文：按 JTE 模板顺序渲染四页 —— 正文页、评价结果表、附页、附录A。
   每页包在 .paper-holder 里，外层负责按视口宽度等比缩放。 */
import InfoTable from './InfoTable.vue'
import ReportFrontMatter from './ReportFrontMatter.vue'
import EvaluationTable from './EvaluationTable.vue'
import AppendixPage from './AppendixPage.vue'
import AppendixA from './AppendixA.vue'
import type { RiskValue } from '@/domain/riskAssign'
import type { Grade, RiskCategory } from '@/domain/riskScore'
import type { AppendixRow } from '@/types/report'

defineProps<{
  overview: string
  conclusion: string
  riskByNo: Record<string, RiskValue>
  appendixRows: AppendixRow[]
  categories: RiskCategory[]
  g: number | null
  grade: Grade | null
  analysisText: string
}>()
</script>

<template>
  <ReportFrontMatter />
  <div class="paper-holder">
    <div class="paper">
      <h1>在用曳引驱动电梯安全评估报告</h1>
      <InfoTable readonly :overview="overview" :conclusion="conclusion" />
    </div>
  </div>

  <div class="paper-holder">
    <div class="paper">
      <EvaluationTable :risk-by-no="riskByNo" />
    </div>
  </div>

  <div class="paper-holder">
    <div class="paper">
      <div class="sec-title">附页</div>
      <AppendixPage :rows="appendixRows" />
    </div>
  </div>

  <div class="paper-holder">
    <div class="paper">
      <AppendixA :categories="categories" :g="g" :grade="grade" />
    </div>
  </div>

  <div v-if="analysisText" class="paper-holder">
    <div class="paper analysis-paper">
      <h1>文本分析报告</h1>
      <p class="analysis-note">以下内容由大模型基于本次评估事实与人工勾选的候选路径生成，未签核，供复核。</p>
      <div class="analysis-body">{{ analysisText }}</div>
    </div>
  </div>
</template>

<style scoped>
.analysis-paper h1 {
  margin-top: 0;
}
.analysis-note {
  color: var(--c-muted);
  font-size: 12px;
  margin: 6px 0 14px;
}
.analysis-body {
  white-space: pre-wrap;
  line-height: 1.9;
  font-size: 14px;
  color: #222;
}
</style>
