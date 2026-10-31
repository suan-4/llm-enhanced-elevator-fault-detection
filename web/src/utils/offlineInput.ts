import { ref, shallowRef } from 'vue'
import { editText } from '@/domain/inputEditing'

export type TextField = HTMLInputElement | HTMLTextAreaElement
const target = shallowRef<TextField | null>(null)
const opened = ref(false)
const chinese = ref(true)
const enabled = ref(false)
const generation = ref(0)
let caret = { start: 0, end: 0 }
const numericDraft = ref<string | null>(null)
let draftField: TextField | null = null
let ownInput = false

function commit(field: TextField, value: string) {
  const prototype = field instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype
  Object.getOwnPropertyDescriptor(prototype, 'value')?.set?.call(field, value)
  ownInput = true
  try { field.dispatchEvent(new Event('input', { bubbles: true })) }
  finally { ownInput = false }
}

export function editable(element: unknown): element is TextField {
  return (element instanceof HTMLInputElement || element instanceof HTMLTextAreaElement)
    && !element.disabled && !element.readOnly && !element.closest('[data-offline-keyboard]')
    && (element instanceof HTMLTextAreaElement || ['text', 'search', 'tel', 'url', 'email', 'password', 'number'].includes(element.type))
}

function remember(): void {
  const field = target.value
  if (field) {
    const length = draftField === field && numericDraft.value !== null ? numericDraft.value.length : field.value.length
    caret = { start: field.selectionStart ?? length, end: field.selectionEnd ?? length }
  }
}

function edit(text: string, deleting = false): void {
  const field = target.value
  if (!field?.isConnected || field.disabled || field.readOnly) return
  const numeric = field instanceof HTMLInputElement && field.type === 'number'
  if (numeric && field.inputMode === 'numeric' && text.includes('.')) return
  const value = draftField === field && numericDraft.value !== null ? numericDraft.value : field.value
  const next = editText(value, caret.start, caret.end, text, deleting, field.maxLength, numeric)
  // Native number inputs sanitize an unfinished decimal ("1.") to empty.
  // Keep that keystroke locally until the next digit can be committed atomically.
  if (numeric && next.value.endsWith('.')) {
    draftField = field; numericDraft.value = next.value
    const prefix = next.value.slice(0, -1)
    if (field.value !== prefix) commit(field, prefix)
    caret = { start: next.cursor, end: next.cursor }
    return
  }
  draftField = null; numericDraft.value = null
  commit(field, next.value)
  field.focus({ preventScroll: true })
  const position = Math.min(next.cursor, field.value.length)
  try { field.setSelectionRange(position, position) } catch { /* number has no selection API */ }
  caret = { start: position, end: position }
}

export function useOfflineInput() {
  return { target, opened, chinese, enabled, generation, numericDraft, remember, edit,
    externalEdit(event: Event) {
      if (!ownInput && event.target === target.value) { numericDraft.value = null; draftField = null; remember() }
    },
    close() { numericDraft.value = null; draftField = null; opened.value = false; generation.value++ },
    focus(field: TextField) {
      if (field !== target.value) { numericDraft.value = null; draftField = null; generation.value++ }
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
