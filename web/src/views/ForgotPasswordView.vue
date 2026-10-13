<script setup lang="ts">
/* 忘记口令：用板端恢复口令文件（/userdata/elevator/recovery.key）重置。
   登录页只有在这个文件存在时才会显示入口 —— 不给用不了的按钮。 */
import { computed, ref } from 'vue'
import { RouterLink, useRouter } from 'vue-router'
import * as authApi from '@/api/auth'
import { ApiError } from '@/utils/http'
import { useToast } from '@/utils/toast'

const router = useRouter()
const { show } = useToast()

const recoveryKey = ref('')
const username = ref('')
const newPassword = ref('')
const confirmText = ref('')
const busy = ref(false)
const error = ref('')

const confirmIssue = computed(() =>
  confirmText.value && confirmText.value !== newPassword.value ? '两次输入的口令不一致' : '',
)

const canSubmit = computed(
  () =>
    !!recoveryKey.value.trim() &&
    !!username.value.trim() &&
    newPassword.value.length >= 8 &&
    confirmText.value === newPassword.value,
)

async function submit(): Promise<void> {
  if (!canSubmit.value || busy.value) return
  busy.value = true
  error.value = ''
  try {
    await authApi.forgotPassword({
      recovery_key: recoveryKey.value.trim(),
      username: username.value.trim(),
      new_password: newPassword.value,
    })
    show('口令已重置，请用新口令登录')
    await router.replace({ name: 'login' })
  } catch (err) {
    error.value = err instanceof ApiError ? err.detail : '重置失败，请重试'
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <div class="plain-view">
    <form class="plain-card" @submit.prevent="submit">
      <h1>重置口令</h1>
      <p class="hint">
        请输入设备上的恢复口令（由维护人员在部署时设置）。恢复口令错误时不会提示账号是否存在。
      </p>

      <div v-if="error" class="err-box">{{ error }}</div>

      <div class="field" style="margin-top: 14px">
        <label>恢复口令</label>
        <input v-model="recoveryKey" class="input" type="password" placeholder="请输入恢复口令" />
      </div>

      <div class="field">
        <label>要重置的用户名</label>
        <input v-model="username" class="input" type="text" placeholder="请输入登录用户名" />
      </div>

      <div class="field">
        <label>新口令</label>
        <input v-model="newPassword" class="input" type="password" placeholder="至少 8 位，含字母和数字" />
      </div>

      <div class="field">
        <label>确认新口令</label>
        <input v-model="confirmText" class="input" type="password" placeholder="再输入一次" />
        <span v-if="confirmIssue" class="err">{{ confirmIssue }}</span>
      </div>

      <button class="btn btn-primary btn-block" type="submit" :disabled="!canSubmit || busy">
        {{ busy ? '重置中…' : '重置口令' }}
      </button>

      <RouterLink class="hint" style="display: block; margin-top: 12px; text-align: center" to="/login">
        返回登录
      </RouterLink>
    </form>
  </div>
</template>
