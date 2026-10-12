<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { RouterView } from 'vue-router'
import SplashScreen from '@/components/SplashScreen.vue'
import { useAuthStore } from '@/stores/auth'
import { useKiosk } from '@/utils/kiosk'
import { useToast } from '@/utils/toast'

const auth = useAuthStore()
const kiosk = useKiosk()
const { message } = useToast()

const ready = ref(false)

// 启动页至少显示这么长时间，避免快速启动时一闪而过
const SPLASH_MIN_MS = 600

onMounted(async () => {
  const boot = async () => {
    await auth.restore()
    await kiosk.load()
  }
  await Promise.all([boot(), new Promise((r) => setTimeout(r, SPLASH_MIN_MS))])
  ready.value = true
})
</script>

<template>
  <template v-if="ready">
    <!-- 中/英输入法切换：与旧版一致，固定在右上角，板端才显示 -->
    <button
      v-if="kiosk.imeAvailable.value"
      class="ime-toggle"
      :class="{ on: kiosk.imeLabel.value === '中' }"
      type="button"
      title="切换中/英文输入"
      @mousedown.prevent
      @click="kiosk.setIme()"
    >
      {{ kiosk.imeLabel.value }}
    </button>
    <RouterView />
    <div v-if="message" class="toast">{{ message }}</div>
  </template>
  <SplashScreen v-else />
</template>

<style>
/* 输入法切换按钮：样式与旧版逐值一致（固定右上角，避开登录卡片的 ×） */
.ime-toggle {
  position: fixed;
  top: 8px;
  right: 10px;
  z-index: 1300;
  min-width: 44px;
  height: 32px;
  padding: 0 12px;
  border-radius: 16px;
  border: 1px solid #c9dbe3;
  background: rgba(255, 255, 255, 0.94);
  color: #1b5e7a;
  font-family: 'Noto Sans SC', 'Source Han Sans CN', 'Noto Sans Symbols2', sans-serif;
  font-size: 12px;
  font-weight: 700;
  cursor: pointer;
  box-shadow: 0 2px 10px rgba(0, 0, 0, 0.12);
  transition: all 0.2s;
}

.ime-toggle.on {
  background: #1b5e7a;
  color: #fff;
  border-color: #1b5e7a;
}

.ime-toggle:disabled {
  opacity: 0.5;
}
</style>
