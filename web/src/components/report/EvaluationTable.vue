<script setup lang="ts">
import { reasonsText } from '@/domain/validation'
import type { RiskValue } from '@/domain/riskAssign'
import { useReportStore } from '@/stores/report'

defineProps<{ riskByNo: Record<string, RiskValue> }>()

const store = useReportStore()

function resultText(no: string): string {
  const state = store.stateOf(no)
  if (state.result === '不符合') {
    const text = reasonsText(state)
    return text ? `不符合（${text}）` : '不符合'
  }
  return state.result || '—'
}
</script>

<template>
  <table>
    <thead>
      <tr>
        <th rowspan="2" style="width: 16mm">项目编号</th>
        <th rowspan="2" style="width: 22mm">项目</th>
        <th rowspan="2">评价内容与要求</th>
        <th rowspan="2" style="width: 30mm">评价结果</th>
        <th colspan="3" class="ctr" style="width: 38mm">风险评定值</th>
      </tr>
      <tr>
        <th class="ctr" style="width: 12mm">严重程度</th>
        <th class="ctr" style="width: 12mm">概率等级</th>
        <th class="ctr" style="width: 12mm">风险类别</th>
      </tr>
    </thead>
    <tbody>
      <tr v-for="item in store.items" :key="item.no">
        <td>{{ item.no }}</td>
        <td>{{ item.name }}<template v-if="item.sub">　{{ item.sub }}</template></td>
        <td>
          <div v-for="(line, i) in item.req" :key="i">{{ line }}</div>
        </td>
        <td>{{ resultText(item.no) }}</td>
        <template v-if="riskByNo[item.no]">
          <td class="ctr">{{ riskByNo[item.no].severity }}</td>
          <td class="ctr">{{ riskByNo[item.no].probability }}</td>
          <td class="ctr">{{ riskByNo[item.no].category }}</td>
        </template>
        <template v-else>
          <td class="ctr">—</td>
          <td class="ctr">—</td>
          <td class="ctr">—</td>
        </template>
      </tr>
    </tbody>
  </table>
</template>
