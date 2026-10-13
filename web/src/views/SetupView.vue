<script setup lang="ts">
/* 初始化向导：账号表为空时的第一个账号。
   取代过去"预置 admin/admin123"——设备上不再存在默认口令。 */
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'
import * as authApi from '@/api/auth'
import { useAuthStore } from '@/stores/auth'
import { useSetupStore } from '@/stores/setup'
import { ApiError } from '@/utils/http'

const router = useRouter()
const auth = useAuthStore()
const setup = useSetupStore()

const displayName = ref('')
const username = ref('')
const password = ref('')
const confirmText = ref('')
const busy = ref(false)
const error = ref('')

/** 与后端同口径：≥8 位、含字母与数字、不得与用户名相同 */
const passwordIssue = computed(() => {
  const value = password.value
  if (!value) return ''
  if (value.length < 8) return '口令至少 8 位'
  if (!/[A-Za-z]/.test(value) || !/\d/.test(value)) return '口令需要同时包含字母和数字'
  if (value.toLowerCase() === username.value.trim().toLowerCase()) return '口令不能与用户名相同'
  return ''
})

const confirmIssue = computed(() =>
  confirmText.value && confirmText.value !== password.value ? '两次输入的口令不一致' : '',
)

const canSubmit = computed(
  () =>
    !!displayName.value.trim() &&
    !!username.value.trim() &&
    !!password.value &&
    !passwordIssue.value &&
    !confirmIssue.value &&
    confirmText.value === password.value,
)

async function submit(): Promise<void> {
  if (!canSubmit.value || busy.value) return
  busy.value = true
  error.value = ''
  try {
    const res = await authApi.setupInit({
      display_name: displayName.value.trim(),
      username: username.value.trim(),
      password: password.value,
    })
    auth.adoptSession(res.token, res.user)
    setup.initialized = true
    await router.replace({ name: 'report' })
  } catch (err) {
    error.value = err instanceof ApiError ? err.detail : '初始化失败，请重试'
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <div class="plain-view">
    <form class="plain-card" @submit.prevent="submit">
      <h1>系统初始化</h1>
      <p class="hint">首次使用，请创建第一个账号。登录用户名创建后不可修改。</p>

      <div v-if="error" class="err-box">{{ error }}</div>

      <div class="field" style="margin-top: 14px">
        <label>姓名</label>
        <input v-model="displayName" class="input" type="text" placeholder="请输入真实姓名" />
      </div>

      <div class="field">
        <label>登录用户名</label>
        <input v-model="username" class="input" type="text" placeholder="字母、数字、下划线" />
      </div>

      <div class="field">
        <label>口令</label>
        <input v-model="password" class="input" type="password" placeholder="至少 8 位，含字母和数字" />
        <span v-if="passwordIssue" class="err">{{ passwordIssue }}</span>
      </div>

      <div class="field">
        <label>确认口令</label>
        <input v-model="confirmText" class="input" type="password" placeholder="再输入一次" />
        <span v-if="confirmIssue" class="err">{{ confirmIssue }}</span>
      </div>

      <button class="btn btn-primary btn-block" type="submit" :disabled="!canSubmit || busy">
        {{ busy ? '创建中…' : '创建并进入系统' }}
      </button>
    </form>
  </div>
</template>
