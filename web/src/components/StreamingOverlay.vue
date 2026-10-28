<script setup lang="ts">
defineProps<{ text: string }>()
</script>

<template>
  <div class="stream-mask">
    <div class="stream-card">
      <div class="stream-head">
        <span class="dot" />
        正在生成报告正文
        <span class="count">{{ text.length }} 字</span>
      </div>
      <pre class="stream-text">{{ text || '正在生成最终正文…' }}</pre>
      <p class="stream-tip">正文生成完成后会自动进入报告查看；风险与得分随后由程序一次填入。</p>
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
.stream-tip { margin: 0; padding: 10px 18px; border-top: 1px solid #eef2f4; font-size: 11.5px; color: #879; }
@keyframes blink { 0%, 100% { opacity: 1; } 50% { opacity: .25; } }
</style>
