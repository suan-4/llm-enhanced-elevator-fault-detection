<script setup lang="ts">
import { renderMarkdown } from '@/utils/markdown'

defineProps<{ text: string }>()
</script>

<template>
  <div class="stream-mask">
    <div class="stream-card">
      <div class="stream-head">
        <span class="dot" />
        正在生成文末文本分析报告
        <span class="count">{{ text.length }} 字</span>
      </div>
      <div v-if="text" class="stream-text md" v-html="renderMarkdown(text)" />
      <pre v-else class="stream-text">正在生成文本分析报告…</pre>
      <p class="stream-tip">分析报告生成完成后会自动进入报告查看；评估概况、风险与得分由程序单独生成。</p>
    </div>
  </div>
</template>

<style scoped>
.stream-mask {
  position: fixed;
  inset: 0;
  z-index: 900;
  background: rgba(15, 23, 32, .55);
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
}
.stream-card {
  width: min(920px, 100%);
  max-height: 86vh;
  display: flex;
  flex-direction: column;
  background: #fff;
  border-radius: 12px;
  box-shadow: 0 18px 50px rgba(0, 0, 0, .28);
  overflow: hidden;
}
.stream-head {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 14px 18px;
  border-bottom: 1px solid #e3eaee;
  font-size: 14px;
  font-weight: 700;
  color: #1b5e7a;
}
.dot {
  width: 9px;
  height: 9px;
  border-radius: 50%;
  background: #1b5e7a;
  animation: blink 1s infinite;
}
.count { margin-left: auto; font-size: 11.5px; font-weight: 400; color: #879; }
.stream-text {
  margin: 0;
  padding: 16px 20px;
  overflow-y: auto;
  flex: 1;
  min-height: 220px;
  max-height: 62vh;
  white-space: pre-wrap;
  word-break: break-word;
  font-family: inherit;
  font-size: 13.5px;
  line-height: 1.75;
  color: #223;
}
.stream-text.md { white-space: normal; }
.stream-text.md :deep(h1),
.stream-text.md :deep(h2),
.stream-text.md :deep(h3) {
  margin: 8px 0 6px;
  color: #1b5e7a;
}
.stream-text.md :deep(p) { margin: 0 0 8px; }
.stream-text.md :deep(ul),
.stream-text.md :deep(ol) { margin: 4px 0 8px; padding-left: 22px; }
.stream-text.md :deep(li) { margin: 2px 0; }
.stream-text.md :deep(strong) { color: #123; }
.stream-tip { margin: 0; padding: 10px 18px; border-top: 1px solid #eef2f4; font-size: 11.5px; color: #879; }
@keyframes blink { 0%, 100% { opacity: 1; } 50% { opacity: .25; } }
</style>
