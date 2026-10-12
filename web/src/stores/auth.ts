import { defineStore } from 'pinia'
import { ref } from 'vue'
import * as authApi from '@/api/auth'
import { getToken, setToken } from '@/utils/http'
import type { User } from '@/types/api'

export const useAuthStore = defineStore('auth', () => {
  const user = ref<User | null>(null)
  const loading = ref(false)

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

  async function signOut(): Promise<void> {
    try {
      await authApi.logout()
    } catch {
      // 令牌可能已失效，忽略即可
    }
    setToken('')
    user.value = null
  }

  return { user, loading, signIn, restore, signOut }
})
