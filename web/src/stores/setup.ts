import { defineStore } from 'pinia'
import { ref } from 'vue'
import * as authApi from '@/api/auth'

/* 初始化状态：前端启动第一问。
   默认 initialized=true —— 万一这个接口挂了，宁可让人看到登录页，
   也不要误把已初始化的系统推进向导。 */
export const useSetupStore = defineStore('setup', () => {
  const initialized = ref(true)
  const recoveryAvailable = ref(false)
  const version = ref('')
  const loaded = ref(false)

  async function load(): Promise<void> {
    try {
      const res = await authApi.setupStatus()
      initialized.value = !!res.initialized
      recoveryAvailable.value = !!res.recovery_available
      version.value = res.version || ''
    } catch {
      // 保守默认，见文件头说明
    } finally {
      loaded.value = true
    }
  }

  return { initialized, recoveryAvailable, version, loaded, load }
})
