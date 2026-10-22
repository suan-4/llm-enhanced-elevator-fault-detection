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
}>()
</script>

<template>
  <ReportFrontMatter />
  <div class="paper-holder">
    <div class="paper">
      <h1>在用曳引驱动电梯安全评估报告</h1>
      <InfoTable readonly :overview="overview" :conclusion="conclusion" />
      <div class="notes">
        评估：　　　　　　　　日期：　　年　　月　　日　　　检验机构核准证号：TS7Ⅰ10007-2029<br />
        审核：　　　　　　　　日期：　　年　　月　　日　　　（检验机构检验专用章）<br />
        批准：　　　　　　　　日期：　　年　　月　　日
      </div>
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
</template>
