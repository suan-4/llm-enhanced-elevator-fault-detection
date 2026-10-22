<script setup lang="ts">
import ItemRow from './ItemRow.vue'
import { useReportStore } from '@/stores/report'

const store = useReportStore()
</script>

<template>
  <table class="items">
    <colgroup>
      <col style="width: 74px" />
      <col />
      <col style="width: 302px" />
    </colgroup>
    <thead>
      <tr>
        <th>项目编号</th>
        <th>项目</th>
        <th>评价结果</th>
      </tr>
    </thead>
    <tbody>
      <ItemRow v-for="item in store.items" :key="item.no" :item="item" />
    </tbody>
  </table>
</template>
