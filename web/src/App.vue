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
    <RouterView />
    <div v-if="message" class="toast">{{ message }}</div>
  </template>
  <SplashScreen v-else />
</template>
