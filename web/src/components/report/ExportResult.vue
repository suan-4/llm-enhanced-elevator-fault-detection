<script setup lang="ts">
/* 导出结果卡片：固定悬浮在底部操作条上方。
   导出的触发按钮在操作条里（见 ReportView），这里只负责呈现结果与后续动作。 */
import { useExport } from '@/utils/export'

const { result, open, dismiss } = useExport()
</script>

<template>
  <div v-if="result" class="export-float">
    <div class="row">
      <b>导出成功</b>
      <span class="name">{{ result.filename }}（{{ result.size }}）</span>
      <button class="close" type="button" title="关闭" @click="dismiss">×</button>
    </div>
    <div class="row" style="margin-top: 8px">
      <button class="btn btn-primary" type="button" @click="open('file')">打开文件</button>
      <button class="btn" type="button" @click="open('dir')">打开所在文件夹</button>
    </div>
  </div>
</template>

<style scoped>
.export-float {
  position: fixed;
  right: 20px;
  bottom: 84px;
  z-index: 40;
  width: 360px;
  max-width: calc(100vw - 32px);
  background: var(--c-panel);
  border: 1px solid var(--c-line);
  border-left: 3px solid var(--c-ok);
  border-radius: var(--radius);
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.12);
  padding: 12px 14px;
}

.row {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.name {
  color: var(--c-secondary);
  font-size: 12.5px;
  word-break: break-all;
}

.close {
  margin-left: auto;
  background: none;
  border: 0;
  color: var(--c-muted);
  font-size: 18px;
  line-height: 1;
  cursor: pointer;
}

.close:hover {
  color: var(--c-danger);
}

@media (max-width: 900px) {
  .export-float {
    right: 8px;
    left: 8px;
    width: auto;
    bottom: 96px;
  }
}
</style>
