import { defineStore } from 'pinia'
import { ref } from 'vue'
import * as authApi from '@/api/auth'
import { getToken, setToken } from '@/utils/http'
import type { User } from '@/types/api'

export const useAuthStore = defineStore('auth', () => {
  const user = ref<User | null>(null)
  const loading = ref(false)
  const restored = ref(false)

  async function signIn(username: string, password: string): Promise<User> {
    loading.value = true
    try {
      const res = await authApi.login(username, password)
      setToken(res.token)
      user.value = res.user
      return res.user
    } finally {
      loading.value = false
    }
  }

  /** 用本地令牌恢复登录态；失败则清空 */
  async function restore(): Promise<User | null> {
    if (!getToken()) return null
    try {
      const res = await authApi.me()
      user.value = res.user
      return res.user
    } catch {
      setToken('')
      user.value = null
      return null
    }
  }

  /** 只恢复一次（路由守卫和 App 都会调，避免重复请求） */
  async function restoreOnce(): Promise<User | null> {
    if (restored.value) return user.value
    const result = await restore()
    restored.value = true
    return result
  }

  /** 初始化向导创建账号后直接进入系统 */
  function adoptSession(token: string, nextUser: User): void {
    setToken(token)
    user.value = nextUser
    restored.value = true
  }

  async function signOut(): Promise<void> {
    try {
      await authApi.logout()
    } catch {
      // 令牌可能已失效，忽略即可
    }
    setToken('')
    user.value = null
    restored.value = true
  }

  return { user, loading, restored, signIn, restore, restoreOnce, adoptSession, signOut }
})
