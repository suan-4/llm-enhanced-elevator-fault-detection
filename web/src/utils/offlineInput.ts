import { ref, shallowRef } from 'vue'
import { editText } from '@/domain/inputEditing'

export type TextField = HTMLInputElement | HTMLTextAreaElement
const target = shallowRef<TextField | null>(null)
const opened = ref(false)
const chinese = ref(true)
const enabled = ref(false)
const generation = ref(0)
let caret = { start: 0, end: 0 }

export function editable(element: unknown): element is TextField {
  return (element instanceof HTMLInputElement || element instanceof HTMLTextAreaElement)
    && !element.disabled && !element.readOnly && !element.closest('[data-offline-keyboard]')
    && (element instanceof HTMLTextAreaElement || ['text', 'search', 'tel', 'url', 'email', 'password', 'number'].includes(element.type))
}

function remember(): void {
  const field = target.value
  if (field) caret = { start: field.selectionStart ?? field.value.length, end: field.selectionEnd ?? field.value.length }
}

function edit(text: string, deleting = false): void {
  const field = target.value
  if (!field?.isConnected || field.disabled || field.readOnly) return
  const next = editText(field.value, caret.start, caret.end, text, deleting, field.maxLength,
    field instanceof HTMLInputElement && field.type === 'number')
  const prototype = field instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype
  Object.getOwnPropertyDescriptor(prototype, 'value')?.set?.call(field, next.value)
  field.dispatchEvent(new Event('input', { bubbles: true }))
  field.focus({ preventScroll: true })
  const position = Math.min(next.cursor, field.value.length)
  try { field.setSelectionRange(position, position) } catch { /* number has no selection API */ }
  caret = { start: position, end: position }
}

export function useOfflineInput() {
  return { target, opened, chinese, enabled, generation, remember, edit,
    close() { opened.value = false; generation.value++ },
    focus(field: TextField) {
      if (field !== target.value) generation.value++
      target.value = field
      remember()
      opened.value = true
    },
    nextField() {
      const all = [...document.querySelectorAll('input,textarea')].filter(editable)
      const position = all.indexOf(target.value as TextField)
      const next = all[position + 1]
      if (next) next.focus()
      else { opened.value = false; target.value?.blur() }
    },
  }
}
