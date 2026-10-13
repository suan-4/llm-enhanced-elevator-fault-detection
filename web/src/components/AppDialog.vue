<script setup lang="ts">
/* 页面内自绘弹窗。
   为什么不用原生 confirm/prompt：板端 WebKit 会弹英文系统框并**阻塞页面**，
   现场人员既看不懂也没法处理。 */
defineProps<{
  open: boolean
  title: string
  /** 危险操作：主按钮用红色 */
  danger?: boolean
  confirmText?: string
  cancelText?: string
  busy?: boolean
}>()

const emit = defineEmits<{ close: []; confirm: [] }>()
</script>

<template>
  <div v-if="open" class="dialog-mask" @click.self="emit('close')">
    <div class="dialog">
      <div class="dialog-head">{{ title }}</div>
      <div class="dialog-body">
        <slot />
      </div>
      <div class="dialog-foot">
        <button class="btn" type="button" :disabled="busy" @click="emit('close')">
          {{ cancelText || '取消' }}
        </button>
        <button
          class="btn"
          :class="danger ? 'btn-danger' : 'btn-primary'"
          type="button"
          :disabled="busy"
          @click="emit('confirm')"
        >
          {{ busy ? '处理中…' : confirmText || '确定' }}
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.dialog-foot .btn-danger {
  background: var(--c-danger);
  border-color: var(--c-danger);
  color: #fff;
}
</style>
