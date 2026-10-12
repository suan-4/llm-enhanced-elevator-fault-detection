<script setup lang="ts">
/* 登录页：结构、文案与样式均与旧版单文件前端一致（不重新设计）。
   字号按旧版 html{font-size:15px} 换算为 px，保证渲染尺寸相同。 */
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

/* 退出系统：登录页也必须可用（kiosk 模式下进不去系统时的唯一出口） */
async function exitSystem(): Promise<void> {
  try {
    await kiosk.exit()
    show('已退出系统，正在返回桌面')
  } catch (err) {
    show(err instanceof Error ? err.message : '退出失败')
  }
}
</script>

<template>
  <div class="login-view">
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

      <BrandLockup class="login-logo" />

      <div class="login-h">电梯安全评估系统</div>
      <div class="login-sub">请使用您的账号登录</div>

      <div v-if="error" class="login-err">{{ error }}</div>

      <div class="form-group">
        <label class="form-label">用户名</label>
        <input
          v-model="username"
          class="form-input"
          type="text"
          autocomplete="username"
          placeholder="请输入用户名"
        />
      </div>

      <div class="form-group">
        <label class="form-label">口令</label>
        <input
          v-model="password"
          class="form-input"
          type="password"
          autocomplete="current-password"
          placeholder="请输入口令"
        />
      </div>

      <button class="btn btn-primary login-btn" type="submit" :disabled="auth.loading">
        {{ auth.loading ? '登录中…' : '登 录' }}
      </button>

      <div class="login-foot">广东省特种设备检测研究院佛山检测院 · 佛山大学</div>
    </form>
  </div>
</template>

<style scoped>
.login-view {
  display: flex;
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  z-index: 900;
  background: linear-gradient(160deg, #10365f 0%, #1b5e7a 55%, #0d2b47 100%);
  align-items: center;
  justify-content: center;
  padding: 20px;
  overflow: auto;
  font-family: 'Noto Sans SC', 'Source Han Sans CN', 'Noto Sans Symbols2', sans-serif;
}

.login-card {
  position: relative;
  width: 100%;
  max-width: 340px;
  background: #fff;
  border-radius: 16px;
  box-shadow: 0 18px 50px rgba(0, 0, 0, 0.32);
  padding: 30px;
}

.login-x {
  position: absolute;
  top: 10px;
  right: 12px;
  width: 32px;
  height: 32px;
  line-height: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  background: none;
  border: 0;
  border-radius: 50%;
  color: #8a959d;
  font-size: 22px;
  font-family: inherit;
  cursor: pointer;
  transition: all 0.18s;
}

.login-x:hover {
  background: #fef0f0;
  color: #c5343e;
}

.login-logo {
  /* 上外边距 16px 不是装饰：卡片右上角浮着 32×32 的「×」（top:10px，底部在卡片顶下方 42px），
     logo 行若从 padding 30px 开始会与其重叠 12.5×8.5 逻辑像素 ——
     而「×」是可点的触控目标，点佛大 logo 右上角会直接退出系统。 */
  margin: 16px auto 20px;
}

.login-h {
  font-size: 15.3px;
  font-weight: 700;
  text-align: center;
  color: #2c2c2c;
}

.login-sub {
  font-size: 10.5px;
  color: #8a959d;
  text-align: center;
  margin: 4px 0 20px;
}

.login-err {
  background: #fef0f0;
  color: #c5343e;
  border: 1px solid #f3c9cc;
  border-radius: 6px;
  padding: 9px 12px;
  font-size: 11.1px;
  margin-bottom: 14px;
}

.form-group {
  display: flex;
  flex-direction: column;
  gap: 4px;
  margin-bottom: 14px;
}

.form-label {
  font-size: 11.4px;
  font-weight: 600;
  color: #5d6b74;
}

.form-input {
  border: 1.5px solid #c9dbe3;
  border-radius: 6px;
  padding: 8px 12px;
  font-size: 12.9px;
  font-family: inherit;
  color: #2c2c2c;
  outline: none;
  width: 100%;
  background: #fff;
}

.form-input:focus {
  border-color: #2d8ab5;
  box-shadow: 0 0 0 3px rgba(27, 94, 122, 0.06);
}

.btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 9px 22px;
  border-radius: 6px;
  font-size: 12.3px;
  font-weight: 600;
  font-family: inherit;
  cursor: pointer;
  border: 1.5px solid transparent;
  transition: all 0.2s;
}

.btn-primary {
  background: #1b5e7a;
  color: #fff;
}

.btn-primary:hover:not(:disabled) {
  background: #164b63;
}

.btn:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.login-btn {
  width: 100%;
  justify-content: center;
  padding: 11px;
  font-size: 12.75px;
  margin-top: 8px;
}

.login-foot {
  margin-top: 16px;
  text-align: center;
  font-size: 9.6px;
  color: #8a959d;
}
</style>
