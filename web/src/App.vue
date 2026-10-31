<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { RouterView, useRoute } from 'vue-router'
import AppShell from '@/components/AppShell.vue'
import SplashScreen from '@/components/SplashScreen.vue'
import OfflineKeyboard from '@/components/input/OfflineKeyboard.vue'
import { useOfflineInput } from '@/utils/offlineInput'
import { useAuthStore } from '@/stores/auth'
import { useSetupStore } from '@/stores/setup'
import { useKiosk } from '@/utils/kiosk'
import { useToast } from '@/utils/toast'

const auth = useAuthStore()
const setup = useSetupStore()
const kiosk = useKiosk()
const offlineInput = useOfflineInput()
const route = useRoute()
const { message, tone } = useToast()

const ready = ref(false)

// 启动页至少显示这么长时间，避免快速启动时一闪而过
const SPLASH_MIN_MS = 600

/* 登录页 / 初始化向导 / 忘记口令 是"空白页"：不套外壳（侧栏 + 顶栏）。
   其余页面套外壳，共用同一份侧栏。 */
const PLAIN_ROUTES = ['login', 'forgot', 'setup']
const withShell = computed(
  () => !!auth.user && !PLAIN_ROUTES.includes(String(route.name || '')),
)

onMounted(async () => {
  const boot = async () => {
    // 三件事并行：恢复登录态、问一体机状态、问是否已初始化
    await Promise.all([auth.restoreOnce(), kiosk.load(), setup.load()])
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
      @click="offlineInput.enabled.value ? (offlineInput.chinese.value = !offlineInput.chinese.value) : kiosk.setIme()"
    >
      {{ offlineInput.enabled.value ? (offlineInput.chinese.value ? '中' : '英') : kiosk.imeLabel.value }}
    </button>

    <AppShell v-if="withShell">
      <RouterView />
    </AppShell>
    <RouterView v-else />
    <OfflineKeyboard />

    <div v-if="message" class="toast" :class="{ danger: tone === 'danger' }">{{ message }}</div>
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
