import { ref } from 'vue'

export type ToastTone = 'info' | 'danger'

const message = ref('')
/** danger = 红色提示（校验拦截等需要现场立刻注意的情况） */
const tone = ref<ToastTone>('info')
let timer: number | undefined

export function useToast() {
  /** 旧调用保持 show(text) / show(text, ms)；需要红色时传第三个参数 */
  function show(text: string, duration = 3200, nextTone: ToastTone = 'info'): void {
    message.value = text
    tone.value = nextTone
    window.clearTimeout(timer)
    timer = window.setTimeout(() => {
      message.value = ''
    }, duration)
  }

  function hide(): void {
    message.value = ''
    tone.value = 'info'
    window.clearTimeout(timer)
  }

  return { message, tone, show, hide }
}
