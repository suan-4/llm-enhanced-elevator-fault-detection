<script setup lang="ts">
import { onBeforeUnmount, ref } from 'vue'
const emit = defineEmits<{ pick: [text: string]; error: [message: string] }>()
const canvas = ref<HTMLCanvasElement>()
const candidates = ref<string[]>([])
const busy = ref(false)
const strokes: number[][][] = []
let drawing = false, sequence = 0, timer: ReturnType<typeof setTimeout> | undefined
const worker = new Worker(new URL('./handwriting.worker.ts', import.meta.url))
worker.onmessage = event => {
  if (event.data.id !== sequence) return
  busy.value = false
  candidates.value = event.data.candidates
  if (event.data.error) emit('error', event.data.error)
}
worker.onerror = () => { busy.value = false; emit('error', '手写识别暂不可用') }
function draw() {
  const ctx = canvas.value?.getContext('2d')
  if (!ctx || !canvas.value) return
  ctx.clearRect(0, 0, canvas.value.width, canvas.value.height)
  ctx.lineWidth = 4; ctx.lineCap = 'round'; ctx.lineJoin = 'round'; ctx.strokeStyle = '#183c4b'
  for (const stroke of strokes) {
    ctx.beginPath()
    stroke.forEach((p, i) => i ? ctx.lineTo(p[0], p[1]) : ctx.moveTo(p[0], p[1]))
    ctx.stroke()
  }
}
function point(event: PointerEvent) {
  const rect = canvas.value!.getBoundingClientRect()
  return [(event.clientX - rect.left) * 420 / rect.width, (event.clientY - rect.top) * 220 / rect.height]
}
function begin(event: PointerEvent) {
  if (drawing) return
  drawing = true; sequence++; clearTimeout(timer); candidates.value = []
  canvas.value!.setPointerCapture(event.pointerId)
  strokes.push([point(event)]); draw()
}
function move(event: PointerEvent) { if (drawing) { strokes[strokes.length - 1].push(point(event)); draw() } }
function recognize() {
  sequence++
  candidates.value = []
  if (!strokes.length) { busy.value = false; return }
  busy.value = true
  worker.postMessage({ id: sequence, strokes })
}
function end(event: PointerEvent) {
  if (!drawing) return
  move(event); drawing = false
  timer = setTimeout(recognize, 220)
}
function clear() { strokes.length = 0; draw(); recognize() }
function undo() { strokes.pop(); draw(); recognize() }
function pick(text: string) { emit('pick', text); clear() }
onBeforeUnmount(() => { clearTimeout(timer); worker.terminate() })
</script>

<template>
  <div class="handwriting">
    <div class="handwriting-candidates" aria-label="手写候选字">
      <button v-for="word in candidates" :key="word" type="button" @click="pick(word)">{{ word }}</button>
      <span v-if="!candidates.length">{{ busy ? '正在识别…' : '写一个字，点选候选字' }}</span>
    </div>
    <div class="handwriting-body">
      <canvas ref="canvas" width="420" height="220" aria-label="手写区域" @pointerdown.prevent="begin"
        @pointermove.prevent="move" @pointerup.prevent="end" @pointercancel="drawing = false" />
      <div class="handwriting-tools">
        <button type="button" @click="undo">撤一笔</button>
        <button type="button" @click="clear">重写</button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.handwriting { display:flex; flex-direction:column; min-height:0; flex:1 }
.handwriting-candidates { display:flex; align-items:center; gap:8px; min-height:46px; overflow-x:auto; white-space:nowrap }
.handwriting-candidates button { min-width:44px; font-size:25px; background:white; border:1px solid #bfd0d8; border-radius:6px; height:42px }
.handwriting-candidates span { color:#465c66; font-size:14px; padding:8px }
.handwriting-body { display:flex; flex:1; gap:10px; min-height:0 }
canvas { width:calc(100% - 88px); height:100%; background:#fff; border:1px solid #b6c9d2; border-radius:8px; touch-action:none;
  background-image:linear-gradient(transparent calc(50% - .5px),#e1e8ec 50%,transparent calc(50% + .5px)),linear-gradient(90deg,transparent calc(50% - .5px),#e1e8ec 50%,transparent calc(50% + .5px)) }
.handwriting-tools { width:78px; display:flex; flex-direction:column; gap:10px }
.handwriting-tools button { min-height:48px; background:#fff; border:1px solid #b6c9d2; border-radius:6px; color:#203f4d; font-size:15px }
</style>
