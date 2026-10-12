import { ref } from 'vue'

const message = ref('')
let timer: number | undefined

export function useToast() {
  function show(text: string, duration = 3200): void {
    message.value = text
    window.clearTimeout(timer)
    timer = window.setTimeout(() => {
      message.value = ''
    }, duration)
  }

  function hide(): void {
    message.value = ''
    window.clearTimeout(timer)
  }

  return { message, show, hide }
}
