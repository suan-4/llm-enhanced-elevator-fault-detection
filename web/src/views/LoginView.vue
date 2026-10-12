<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import BrandLockup from '@/components/BrandLockup.vue'
import { useAuthStore } from '@/stores/auth'
import { useKiosk } from '@/utils/kiosk'
import { useToast } from '@/utils/toast'

const router = useRouter()
const auth = useAuthStore()
const { show } = useToast()
const kiosk = useKiosk()

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

/* 退出系统：登录页也必须可用。
   kiosk/README.md 有明确论证——否则「进不去系统时想退回桌面」这条
   最需要出口的路径就断了。 */
async function exitSystem(): Promise<void> {
  try {
    await kiosk.exit()
    show('已退出系统，正在返回桌面')
  } catch (err) {
    show(err instanceof Error ? err.message : '退出失败')
  }
}

/* 输入法中英切换：登录页需要。
   用户名/口令是 ASCII，但用户可能先在别处切到了中文。 */
async function switchIme(): Promise<void> {
  await kiosk.setIme()
}
</script>

<template>
  <div class="login-page">
    <form class="login-card" @submit.prevent="submit">
      <button
        v-if="kiosk.showExit()"
        class="login-x"
        type="button"
        title="退出系统并返回桌面"
        aria-label="退出系统"
        @click="exitSystem"
      >
        ×
      </button>

      <BrandLockup />

      <h1 class="login-title">电梯安全评估系统</h1>
      <p class="login-sub">请使用您的账号登录</p>

      <div v-if="error" class="login-err">{{ error }}</div>

      <label class="login-field">
        <span>用户名</span>
        <input
          v-model="username"
          class="input"
          type="text"
          autocomplete="username"
          placeholder="请输入用户名"
        />
      </label>

      <label class="login-field">
        <span>口令</span>
        <input
          v-model="password"
          class="input"
          type="password"
          autocomplete="current-password"
          placeholder="请输入口令"
        />
      </label>

      <button class="btn btn-primary btn-lg btn-block login-btn" type="submit" :disabled="auth.loading">
        {{ auth.loading ? '登录中…' : '登 录' }}
      </button>

      <div v-if="kiosk.imeAvailable.value" class="login-tools">
        <button class="btn" type="button" @mousedown.prevent @click="switchIme">
          {{ kiosk.imeLabel.value }}
        </button>
        <span class="login-tools-tip">点击切换中 / 英输入</span>
      </div>

      <div class="login-foot">广东省特种设备检测研究院佛山检测院 · 佛山大学</div>
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
  position: relative;
  width: 420px;
  max-width: 100%;
  background: var(--c-panel);
  border: 1px solid var(--c-line);
  border-top: 3px solid var(--c-primary);
  box-shadow: 0 2px 10px rgba(23, 35, 61, 0.08);
  padding: 26px 26px 20px;
}

.login-x {
  position: absolute;
  top: 8px;
  right: 10px;
  width: 30px;
  height: 30px;
  line-height: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  background: none;
  border: 0;
  color: var(--c-muted);
  font-size: 20px;
  font-family: var(--font-ui);
  cursor: pointer;
}

.login-x:hover {
  color: var(--c-danger);
  background: var(--c-danger-soft);
}

.login-title {
  margin: 18px 0 0;
  font-size: 17px;
  font-weight: 700;
  text-align: center;
  color: var(--c-ink);
}

.login-sub {
  margin: 5px 0 18px;
  font-size: 12.5px;
  text-align: center;
  color: var(--c-muted);
}

.login-err {
  background: var(--c-danger-soft);
  color: var(--c-danger);
  border: 1px solid #f3c9cc;
  padding: 8px 11px;
  font-size: 12.5px;
  margin-bottom: 12px;
}

.login-field {
  display: block;
  margin-bottom: 13px;
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

.login-btn {
  margin-top: 6px;
}

.login-tools {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 12px;
}

.login-tools-tip {
  font-size: 12px;
  color: var(--c-muted);
}

.login-foot {
  margin-top: 16px;
  text-align: center;
  font-size: 11.5px;
  color: var(--c-muted);
}

@media (max-width: 900px) {
  .login-page {
    padding: 12px;
  }

  .login-card {
    padding: 22px 16px 16px;
  }

  .login-field .input,
  .login-btn {
    height: var(--h-touch);
    font-size: 15px;
  }
}
</style>
