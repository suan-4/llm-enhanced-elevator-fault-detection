<script setup lang="ts">
import type { AppendixRow } from '@/types/report'

defineProps<{ rows: AppendixRow[] }>()
</script>

<template>
  <table>
    <thead>
      <tr>
        <th class="ctr" style="width: 12mm">序号</th>
        <th class="ctr" style="width: 18mm">项目编号</th>
        <th>存在风险</th>
        <th class="ctr" style="width: 18mm">风险类别</th>
        <th>降低风险措施</th>
      </tr>
    </thead>
    <tbody>
      <tr v-for="(row, i) in rows" :key="row.key">
        <td class="ctr">{{ i + 1 }}</td>
        <td class="ctr">{{ row.no }}</td>
        <td>{{ row.text }}{{ row.risk.category === 'Ⅰ类' ? '（见注）' : '' }}</td>
        <td class="ctr">{{ row.risk.category }}</td>
        <td>{{ row.measure }}</td>
      </tr>
    </tbody>
  </table>
  <div class="notes">
    注：出厂时符合当时标准，但缺少或不符合现行标准所规定的安全保护装置（措施）而产生的风险。
  </div>
</template>
