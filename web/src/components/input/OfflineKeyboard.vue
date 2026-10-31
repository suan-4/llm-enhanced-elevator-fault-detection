<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import HandwritingPad from './HandwritingPad.vue'
import { inputRequest, type InputAction, type InputStatus, type PinyinResult } from '@/api/input'
import { editable, useOfflineInput } from '@/utils/offlineInput'

const input = useOfflineInput()
const route = useRoute()
const capabilities = ref<InputStatus>({ keyboard: false, pinyin: false, voice: false, offline: true })
const mode = ref<'keyboard' | 'handwriting' | 'voice'>('keyboard')
const layout = ref<'letters' | 'numbers' | 'symbols'>('letters')
const shift = ref(false)
const error = ref('')
const actions = ref<InputAction[]>([])
const candidates = ref<string[]>([])
const hasNext = ref(false)
const busy = ref(false)
const recordingId = ref('')
const voiceBusy = ref(false)
const holdReleased = ref(false)
const voiceText = ref('')
const seconds = ref(0)
const panel = ref<HTMLElement>()
let serial = 0, committedLength = 0
let voiceSerial = 0
let debounce: ReturnType<typeof setTimeout> | undefined
let clock: ReturnType<typeof setInterval> | undefined
let observer: ResizeObserver | undefined
const password = computed(() => input.target.value?.type === 'password')
const numeric = computed(() => input.target.value?.type === 'number')
const multiline = computed(() => input.target.value instanceof HTMLTextAreaElement)
const label = computed(() => input.target.value?.getAttribute('aria-label') || input.target.value?.placeholder || '文字输入')
const pinyinText = computed(() => actions.value.reduce((text, action) => {
  if ('key' in action) return action.key === 'BackSpace' ? text.slice(0, -1) : text + action.key
  return text
}, ''))
const rows = computed(() => {
  if (layout.value === 'numbers') return ['1234567890', '-/:;()¥&@"', '.,?!\'#+=_%'].map(row => Array.from(row))
  if (layout.value === 'symbols') return ['【】《》“”‘’', '（）〔〕［］｛｝', '+−×÷=℃°ⅠⅡⅢ'].map(row => Array.from(row))
  return ['qwertyuiop', 'asdfghjkl', 'zxcvbnm'].map(row => Array.from(shift.value ? row.toUpperCase() : row))
})

function resetComposition() {
  clearTimeout(debounce); serial++; actions.value = []; candidates.value = []
  committedLength = 0; busy.value = false; hasNext.value = false
}
async function refresh() {
  const requestSerial = ++serial, generation = input.generation.value, field = input.target.value
  busy.value = true; error.value = ''
  try {
    const result = await inputRequest<PinyinResult>('/pinyin', { actions: actions.value })
    if (requestSerial !== serial || generation !== input.generation.value || field !== input.target.value || !field?.isConnected) return
    if (result.committed.length > committedLength) input.edit(result.committed.slice(committedLength))
    committedLength = result.committed.length
    candidates.value = result.candidates
    hasNext.value = result.has_next
    if (!result.candidates.length && result.committed) resetComposition()
  } catch (err) {
    if (requestSerial === serial) error.value = err instanceof Error ? err.message : '拼音输入暂不可用'
  } finally { if (requestSerial === serial) busy.value = false }
}
function action(value: InputAction, immediately = false) {
  if (actions.value.length >= 155) { error.value = '请先完成当前拼音输入'; return }
  actions.value.push(value); clearTimeout(debounce)
  if (immediately) void refresh()
  else debounce = setTimeout(refresh, 25)
}
function key(text: string) {
  error.value = ''
  if (layout.value === 'letters' && input.chinese.value && !shift.value && !password.value && !numeric.value && /^[a-z']$/.test(text)) {
    if (!capabilities.value.pinyin) { error.value = '本机拼音引擎不可用，请使用手写或切到英文'; return }
    action({ key: text })
  } else { resetComposition(); input.edit(text) }
}
function backspace() {
  if (actions.value.length) action({ key: 'BackSpace' }, true)
  else input.edit('', true)
}
function space() {
  if (actions.value.length) action({ key: ' ' }, true)
  else input.edit(' ')
}
function enter() {
  if (actions.value.length) { space(); return }
  if (input.target.value instanceof HTMLTextAreaElement) input.edit('\n')
  else input.nextField()
}
function changeLayout(next: 'letters' | 'numbers' | 'symbols') { resetComposition(); layout.value = next }
function language() { resetComposition(); input.chinese.value = !input.chinese.value }
async function cancelVoice() {
  voiceSerial++; voiceBusy.value = false; holdReleased.value = false
  clearInterval(clock)
  const id = recordingId.value
  recordingId.value = ''; voiceText.value = ''; seconds.value = 0
  if (id) {
    try { await inputRequest('/voice/cancel', { id }) } catch { /* expiry already cleaned it */ }
  }
}
function switchMode(next: typeof mode.value) {
  if (next !== 'keyboard' && (password.value || numeric.value)) return
  resetComposition(); void cancelVoice(); mode.value = next; error.value = ''
}

function beginHold(event: Event): void {
  if (password.value || voiceBusy.value || !capabilities.value.voice) return
  // 按住麦克风开始，松开由 endHold 触发停止和识别。
  if (event.currentTarget instanceof HTMLElement && 'pointerId' in event) {
    try { event.currentTarget.setPointerCapture((event as PointerEvent).pointerId) } catch { /* ignore */ }
  }
  holdReleased.value = false
  if (recordingId.value) return
  void startVoice()
}

function endHold(event?: Event): void {
  if (event && event.currentTarget instanceof HTMLElement && 'pointerId' in event) {
    try { event.currentTarget.releasePointerCapture((event as PointerEvent).pointerId) } catch { /* ignore */ }
  }
  if (recordingId.value) {
    void stopVoice()
    return
  }
  if (voiceBusy.value) holdReleased.value = true
}

async function startVoice() {
  if (voiceBusy.value || recordingId.value || password.value) return
  const generation = input.generation.value, request = ++voiceSerial
  voiceBusy.value = true; error.value = ''; voiceText.value = ''
  try {
    const result = await inputRequest<{ id: string }>('/voice/start', {})
    if (request !== voiceSerial || generation !== input.generation.value || !input.opened.value || mode.value !== 'voice') {
      await inputRequest('/voice/cancel', { id: result.id }); return
    }
    // /voice/start 已返回，允许 pointerup 立即结束录音；此时不再算“启动中”。
    voiceBusy.value = false
    recordingId.value = result.id; seconds.value = 0
    clock = setInterval(() => { seconds.value++; if (seconds.value >= 30) void stopVoice() }, 1000)
  } catch (err) { if (request === voiceSerial) error.value = err instanceof Error ? err.message : '麦克风未就绪' }
  finally {
    if (request === voiceSerial) {
      voiceBusy.value = false
      // 用户可能在 /voice/start 返回前就松手了。
      if (holdReleased.value) {
        holdReleased.value = false
        void stopVoice()
      }
    }
  }
}
async function stopVoice() {
  const id = recordingId.value, generation = input.generation.value, request = voiceSerial
  if (!id || voiceBusy.value) return
  clearInterval(clock); voiceBusy.value = true
  try {
    const result = await inputRequest<{ text: string }>('/voice/stop', { id })
    if (request === voiceSerial && generation === input.generation.value && input.opened.value && mode.value === 'voice') voiceText.value = result.text
  } catch (err) {
    if (request === voiceSerial && generation === input.generation.value) error.value = err instanceof Error ? err.message : '语音识别失败'
  } finally { if (request === voiceSerial) { voiceBusy.value = false; recordingId.value = '' } }
}
function insertVoice() {
  if (!voiceText.value) return
  input.edit(voiceText.value); voiceText.value = ''; mode.value = 'keyboard'
}
function close() { input.close(); input.target.value?.blur() }
function keepVisible() {
  void nextTick(() => {
    const field = input.target.value
    if (!field?.isConnected || !input.opened.value || !panel.value) return
    const height = panel.value.getBoundingClientRect().height
    document.documentElement.style.setProperty('--offline-keyboard-height', height + 'px')
    const rect = field.getBoundingClientRect(), top = panel.value.getBoundingClientRect().top
    if (rect.bottom > top - 16 || rect.top < 54) {
      field.scrollIntoView({ block: 'center', behavior: 'auto' })
      const scrolling = field.closest('.main')
      if (scrolling) scrolling.scrollTop += Math.max(0, field.getBoundingClientRect().bottom - top + 24)
    }
  })
}
function focus(event: FocusEvent) {
  if (!editable(event.target)) return
  if (input.enabled.value) input.focus(event.target)
  else { input.target.value = event.target; input.remember() }
}
function selection() { if (document.activeElement === input.target.value) input.remember() }
function pointer(event: PointerEvent) {
  const element = event.target as HTMLElement
  if (element.closest('[data-offline-keyboard],.ime-toggle,.offline-input-launcher') || editable(element)) return
  if (input.opened.value) input.close()
}
function offlineBridge(enabled: boolean) {
  const win = window as unknown as { __elevatorInputManaged: boolean; webkit?: { messageHandlers?: { elevatorKbd?: { postMessage(value: boolean): void } } } }
  win.__elevatorInputManaged = enabled
  if (enabled) win.webkit?.messageHandlers?.elevatorKbd?.postMessage(false)
}
watch(() => input.generation.value, () => { resetComposition(); void cancelVoice(); mode.value = 'keyboard'; layout.value = numeric.value ? 'numbers' : 'letters'; error.value = ''; keepVisible() })
watch(() => input.opened.value, open => {
  document.body.classList.toggle('offline-input-open', open)
  if (open) { observer = new ResizeObserver(keepVisible); void nextTick(() => { if (panel.value) observer?.observe(panel.value) }); keepVisible() }
  else { observer?.disconnect(); resetComposition(); void cancelVoice(); document.documentElement.style.removeProperty('--offline-keyboard-height') }
})
watch(() => route.fullPath, close)
watch(() => input.chinese.value, resetComposition)
onMounted(async () => {
  document.addEventListener('focusin', focus)
  document.addEventListener('selectionchange', selection)
  document.addEventListener('input', input.externalEdit)
  document.addEventListener('pointerdown', pointer, true)
  window.addEventListener('pagehide', close)
  try {
    capabilities.value = await inputRequest<InputStatus>('/status')
    input.enabled.value = capabilities.value.keyboard
    offlineBridge(input.enabled.value)
    if (input.enabled.value && editable(document.activeElement)) input.focus(document.activeElement)
  } catch { /* Desktop physical keyboard still works. */ }
})
onBeforeUnmount(() => {
  close(); observer?.disconnect(); document.removeEventListener('focusin', focus)
  document.removeEventListener('selectionchange', selection); document.removeEventListener('pointerdown', pointer, true)
  document.removeEventListener('input', input.externalEdit)
  window.removeEventListener('pagehide', close); offlineBridge(false)
})
</script>

<template>
  <button v-if="input.target.value?.isConnected && !input.enabled.value && !input.opened.value" class="offline-input-launcher"
    type="button" @pointerdown.prevent @click="input.enabled.value = true; offlineBridge(true); input.focus(input.target.value!)">键盘</button>
  <Teleport to="body">
    <section v-if="input.opened.value && input.target.value?.isConnected" ref="panel" data-offline-keyboard class="offline-keyboard"
      role="region" aria-label="离线输入面板" @pointerdown.prevent>
      <div class="keyboard-toolbar">
        <div class="keyboard-modes" role="group" aria-label="输入方式">
          <button type="button" :class="{ selected: mode === 'keyboard' }" @click="switchMode('keyboard')">键盘</button>
          <button type="button" :class="{ selected: mode === 'handwriting' }" :disabled="password || numeric" @click="switchMode('handwriting')">手写</button>
          <button type="button" :class="{ selected: mode === 'voice' }" :disabled="password || numeric" @click="switchMode('voice')">语音</button>
        </div>
        <span class="keyboard-field">{{ label }}</span>
        <button type="button" class="keyboard-hide" aria-label="收起键盘" @click="close">⌄</button>
      </div>
      <p v-if="error" class="keyboard-error" role="alert">{{ error }}</p>
      <template v-if="mode === 'keyboard'">
        <div class="keyboard-candidatebar">
          <span v-if="input.numericDraft.value !== null" class="keyboard-preedit">{{ input.numericDraft.value }}</span>
          <span v-if="pinyinText" class="keyboard-preedit">{{ pinyinText }}</span>
          <div class="keyboard-candidates" aria-label="拼音候选词">
            <button v-for="word in candidates" :key="word" type="button" @click="action({ candidate: word }, true)">{{ word }}</button>
            <span v-if="!candidates.length">{{ busy ? '正在组词…' : numeric ? '数字输入' : password ? '密码输入' : input.chinese.value ? '中文拼音' : 'English' }}</span>
          </div>
          <button v-if="hasNext" type="button" aria-label="更多候选词" @click="action({ page: 'next' }, true)">›</button>
        </div>
        <div class="keyboard-rows">
          <div v-for="(row, index) in rows" :key="index" class="keyboard-row" :class="{ indented: index === 1 }">
            <button v-if="index === 2 && layout === 'letters'" class="key function" type="button" aria-label="切换大小写" :aria-pressed="shift" @click="shift = !shift">⇧</button>
            <button v-for="char in row" :key="char" type="button" class="key" @click="key(char)">{{ char }}</button>
            <button v-if="index === 2" class="key function" type="button" aria-label="删除一个字" @click="backspace">⌫</button>
          </div>
          <div class="keyboard-row keyboard-bottom">
            <button type="button" class="key function" @click="changeLayout(layout === 'letters' ? 'numbers' : 'letters')">{{ layout === 'letters' ? '123' : 'ABC' }}</button>
            <button type="button" class="key function" @click="changeLayout(layout === 'symbols' ? 'letters' : 'symbols')">符</button>
            <button type="button" class="key function" :disabled="password || numeric" @click="language">{{ input.chinese.value ? '中' : '英' }}</button>
            <button type="button" class="key" @click="key(input.chinese.value && !numeric ? '，' : ',')">{{ input.chinese.value && !numeric ? '，' : ',' }}</button>
            <button type="button" class="key space" @click="space">{{ pinyinText ? '选词' : '空格' }}</button>
            <button type="button" class="key" @click="key(input.chinese.value && !numeric ? '。' : '.')">{{ input.chinese.value && !numeric ? '。' : '.' }}</button>
            <button type="button" class="key enter" @click="enter">{{ multiline ? '换行' : '下一项' }}</button>
          </div>
        </div>
      </template>
      <template v-else-if="mode === 'handwriting'">
        <HandwritingPad @pick="input.edit" @error="error = $event" />
        <div class="handwriting-footer"><button type="button" @click="backspace">⌫ 删除</button><button type="button" @click="input.edit(' ')">空格</button><button type="button" @click="enter">下一项</button></div>
      </template>
      <div v-else class="voice-panel">
        <template v-if="voiceText">
          <p class="voice-result">{{ voiceText }}</p>
          <p class="voice-hint">核对后填入，可继续修改文字</p>
          <div class="voice-actions"><button type="button" @click="voiceText = ''">重新录入</button><button type="button" class="primary" @click="insertVoice">填入文字</button></div>
        </template>
        <template v-else>
          <button type="button" class="voice-record" :class="{ recording: recordingId }" :disabled="!capabilities.voice"
            :aria-label="recordingId ? '松开结束录音并识别' : '按住开始语音输入'"
            @pointerdown.prevent="beginHold"
            @pointerup.prevent="endHold"
            @pointercancel="endHold"
            @touchstart.prevent="beginHold"
            @touchend.prevent="endHold"
            @touchcancel.prevent="endHold"
            @contextmenu.prevent
            @keydown.space.prevent="beginHold"
            @keyup.space.prevent="endHold"
            @keydown.enter.prevent="beginHold"
            @keyup.enter.prevent="endHold">
            <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 15a3 3 0 003-3V5a3 3 0 00-6 0v7a3 3 0 003 3zm-7-4v1a7 7 0 0014 0v-1M12 19v3m-4 0h8" /></svg>
          </button>
          <p class="voice-state">{{ voiceBusy && !recordingId ? '正在处理，请稍候…' : recordingId ? `正在录音 ${seconds} / 30 秒，松开结束` : capabilities.voice ? '按住麦克风说话，松开自动识别' : '离线语音模型尚未就绪' }}</p>
          <p class="voice-hint">离线识别 · 按住说话，松开自动识别</p>
          <button v-if="recordingId" type="button" class="voice-cancel" @click="cancelVoice">取消录音</button>
        </template>
      </div>
    </section>
  </Teleport>
</template>

<style src="./offline-keyboard.css"></style>
