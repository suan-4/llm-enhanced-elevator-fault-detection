import { ref } from 'vue'
import * as api from '@/api/kiosk'

/* 一体机状态的轻量共享状态：
   - kioskRunning  是否运行在一体机模式（决定是否显示「退出系统」）
   - exitEnabled   板端配置是否允许退出
   - isLocal       当前是否为本机访问（板端才为 true）
   - imeLabel      输入法当前状态标签（中 / 英） */
const kioskRunning = ref(false)
const exitEnabled = ref(false)
const isLocal = ref(false)
const probeOk = ref(false)
const imeLabel = ref('英')
const imeAvailable = ref(false)

export function useKiosk() {
  async function load(): Promise<void> {
    try {
      const s = await api.kioskStatus()
      kioskRunning.value = !!s.kiosk_running
      exitEnabled.value = !!s.exit_enabled
      isLocal.value = !!s.local
      probeOk.value = !!s.probe_ok
    } catch {
      // 非板端环境（如开发机直连）拿不到状态属正常，保持默认
    }
    try {
      const i = await api.imeStatus()
      imeLabel.value = i.label || '英'
      imeAvailable.value = !!i.available
    } catch {
      imeAvailable.value = false
    }
  }

  async function setIme(): Promise<void> {
    try {
      const i = await api.toggleIme()
      imeLabel.value = i.label || '英'
    } catch {
      // 忽略：板端外无输入法服务
    }
  }

  async function exit(): Promise<void> {
    await api.exitKiosk()
  }

  /** 一体机模式下显示退出入口。
      探针不可用时（板端缺 pgrep 等）保守显示：宁可多一个按钮，
      也不能让操作员被锁在系统里出不来。 */
  function showExit(): boolean {
    return isLocal.value && exitEnabled.value && (kioskRunning.value || !probeOk.value)
  }

  return {
    kioskRunning,
    exitEnabled,
    isLocal,
    probeOk,
    imeLabel,
    imeAvailable,
    load,
    setIme,
    exit,
    showExit,
  }
}
