<script setup lang="ts">
import { useReportStore } from '@/stores/report'

const store = useReportStore()

const emit = defineEmits<{
  jump: [key: string, kind: 'field' | 'item']
}>()
</script>

<template>
  <div class="alert">
    <div class="alert-head">以下 {{ store.missing.length }} 项未填写，无法生成报告：</div>
    <ul class="alert-list">
      <li v-for="entry in store.missing" :key="`${entry.kind}-${entry.key}`">
        <a @click.prevent="emit('jump', entry.key, entry.kind)">
          <template v-if="entry.kind === 'item'">{{ entry.key }}　{{ entry.label }}</template>
          <template v-else>{{ entry.label }}</template>
        </a>
        　{{ entry.why }}
      </li>
    </ul>
  </div>
</template>
