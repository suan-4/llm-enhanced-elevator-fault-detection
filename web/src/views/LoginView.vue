<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { useToast } from '@/utils/toast'

const router = useRouter()
const auth = useAuthStore()
const { show } = useToast()

const username = ref('')
const password = ref('')
const error = ref('')

async function submit(): Promise<void> {
  error.value = ''
  if (!username.value.trim() || !password.value) {
    error.value = '请输入用户名和口令'
    return
  }
  try {
    await auth.signIn(username.value.trim(), password.value)
    show('登录成功')
    await router.replace({ name: 'report' })
  } catch (err) {
    error.value = err instanceof Error ? err.message : '登录失败'
    password.value = ''
  }
}
</script>

<template>
  <div class="login-page">
    <form class="login-card" @submit.prevent="submit">
      <div class="login-brand">
        <span class="brand-mark">GDSEI</span>
        <span class="login-title">在用曳引驱动电梯安全评估系统</span>
      </div>

      <label class="login-field">
        <span>用户名</span>
        <input v-model="username" class="input" type="text" autocomplete="username" />
      </label>

      <label class="login-field">
        <span>口令</span>
        <input v-model="password" class="input" type="password" autocomplete="current-password" />
      </label>

      <p v-if="error" class="login-error">{{ error }}</p>

      <button class="btn btn-primary btn-lg btn-block" type="submit" :disabled="auth.loading">
        {{ auth.loading ? '登录中…' : '登 录' }}
      </button>
    </form>
  </div>
</template>

<style scoped>
.login-page {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--c-bg);
  padding: 24px;
}

.login-card {
  width: 380px;
  max-width: 100%;
  background: var(--c-panel);
  border: 1px solid var(--c-line);
  border-top: 3px solid var(--c-primary);
  padding: 28px 24px 24px;
}

.login-brand {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 24px;
}

.login-title {
  font-size: 15px;
  font-weight: 700;
  color: var(--c-ink);
  line-height: 1.4;
}

.login-field {
  display: block;
  margin-bottom: 14px;
}

.login-field span {
  display: block;
  font-size: 13px;
  color: var(--c-ink);
  margin-bottom: 5px;
}

.login-field .input {
  height: var(--h-control-lg);
}

.login-error {
  margin: 0 0 12px;
  color: var(--c-danger);
  font-size: 12.5px;
}

@media (max-width: 900px) {
  .login-card {
    padding: 22px 16px 18px;
  }

  .login-field .input,
  .login-card .btn {
    height: var(--h-touch);
    font-size: 15px;
  }
}
</style>
