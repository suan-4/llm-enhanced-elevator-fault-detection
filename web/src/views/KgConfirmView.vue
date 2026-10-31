<script setup lang="ts">
/* 生成前的「故障路径确认」页：
   每个不符合项 / 其他填写 → Top3 候选 → 人工勾选 / 无合适候选 → 生成报告。 */
import { computed, onActivated, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { fetchKgCandidates, fetchKgRecommendation, fetchKgRecommendationBatch,
  selectKgPath, type KgCandidatesResponse, type KgRecommendation } from '@/api/kg'
import { systemConfig } from '@/api/system'
import { useReportStore } from '@/stores/report'
import { useGenerationStore } from '@/stores/generation'
import { useShell } from '@/stores/shell'
import type { KgSelection } from '@/api/reports'

interface Row {
  no: string
  name: string
  reasons: string[]
  otherText: string
  result: KgCandidatesResponse | null
  loading: boolean
  error: string
  choice: string // path_id 或 'none'
  recommendation: KgRecommendation | null
  recommending: boolean
  choiceSource: 'human' | 'model' | 'rule' | 'human_override'
  batch: number
  aiOpen: boolean
}

const router = useRouter()
const store = useReportStore()
const generationStore = useGenerationStore()
const shell = useShell()
defineOptions({ name: 'KgConfirmView' })
const rows = ref<Row[]>([])
const loading = ref(true)
const generating = ref(false)
const error = ref('')
const batchLoading = ref(false)
const currentIndex = ref(0)
const aiPromptCount = ref(3)
const recommendQueue: Row[] = []
let recommendActive = 0
const lastReportId = ref('')
const lastVersion = ref(-1)

const canGenerate = computed(() => rows.value.length > 0
  && rows.value.every((r) => !!r.choice))
const doneCount = computed(() => rows.value.filter((r) => !!r.choice).length)
const remainingRows = computed(() => rows.value.filter(
  (r) => !r.choice && !r.recommending && (r.result?.candidates || []).length > 0,
))
const BATCH_SIZE = 3
const currentRow = computed(() => rows.value[currentIndex.value] || null)
const visibleRows = computed(() => (currentRow.value ? [currentRow.value] : []))
const hasPrev = computed(() => currentIndex.value > 0)
const hasNext = computed(() => currentIndex.value < rows.value.length - 1)

function visibleCandidates(row: Row) {
  const all = row.result?.candidates || []
  return all.slice(row.batch * BATCH_SIZE, row.batch * BATCH_SIZE + BATCH_SIZE)
}

function batchCount(row: Row): number {
  return Math.max(1, Math.ceil((row.result?.candidates || []).length / BATCH_SIZE))
}

function setBatch(row: Row, batch: number): void {
  row.batch = Math.max(0, Math.min(batch, batchCount(row) - 1))
  row.recommendation = null
  const main = document.querySelector('.main') as HTMLElement | null
  main?.scrollTo({ top: 0 })
}

function ensureBatchForPath(row: Row, pathId: string): void {
  const index = (row.result?.candidates || []).findIndex((c) => c.path_id === pathId)
  if (index >= 0) row.batch = Math.floor(index / BATCH_SIZE)
}

function goPage(delta: number): void {
  const next = currentIndex.value + delta
  if (next < 0 || next >= rows.value.length) return
  currentIndex.value = next
  const main = document.querySelector('.main') as HTMLElement | null
  main?.scrollTo({ top: 0 })
}

async function loadRows(): Promise<void> {
  rows.value = []
  currentIndex.value = 0
  recommendQueue.splice(0)
  loading.value = true
  if (!store.reportId) {
    await router.replace('/')
    return
  }
  for (const item of store.items) {
    const state = store.states[item.no]
    if (state?.result !== '不符合') continue
    rows.value.push({
      no: item.no,
      name: item.name,
      reasons: state.reasons.slice(),
      otherText: state.otherText || '',
      result: null,
      loading: true,
      error: '',
      choice: '',
      recommendation: null,
      recommending: false,
      choiceSource: 'human',
      batch: 0,
      aiOpen: false,
    })
  }
  if (!rows.value.length) {
    await router.replace('/')
    return
  }
  await Promise.all(rows.value.map(loadRow))
  loading.value = false
  lastReportId.value = store.reportId
  lastVersion.value = store.version
}

async function loadAiPromptCount(): Promise<void> {
  try {
    const cfg = await systemConfig()
    const item = cfg.items.find((row) => row.key === 'ai_prompt_candidate_count')
    const n = item && typeof item.value === 'number' ? item.value : 3
    aiPromptCount.value = Math.max(1, Math.min(9, n))
  } catch {
    aiPromptCount.value = 3
  }
}

onMounted(async () => {
  shell.active = 'confirm'
  shell.reportsView = false
  await loadAiPromptCount()
  await loadRows()
})

onActivated(async () => {
  shell.active = 'confirm'
  shell.reportsView = false
  // 从录入页改过不符合项再回来时，不能继续用旧 rows/旧候选
  if (lastReportId.value && (store.reportId !== lastReportId.value
      || store.version !== lastVersion.value
      || store.status !== 'draft')) {
    await loadRows()
  }
})

async function loadRow(row: Row): Promise<void> {
  row.loading = true
  row.error = ''
  try {
    const res = await fetchKgCandidates({
      item_no: row.no,
      item_name: row.name,
      reasons: row.reasons,
      other_text: row.otherText,
      top_k: 9,
    })
    row.result = res
    if (!res.candidates.length) {
      row.choice = 'none'
    }
  } catch (err) {
    row.error = err instanceof Error ? err.message : '检索失败'
  } finally {
    row.loading = false
  }
}

async function recommendRemaining(): Promise<void> {
  const targets = remainingRows.value.slice(0, 3)
  if (!targets.length || batchLoading.value) return
  batchLoading.value = true
  targets.forEach((row) => { row.recommending = true })
  try {
    const res = await fetchKgRecommendationBatch(targets.map((row) => ({
      item_no: row.no,
      item_name: row.name,
      reasons: row.reasons,
      other_text: row.otherText,
      top_k: 3,
    })))
    if (!res.success) throw new Error(res.error || '批量推荐失败')
    for (const item of res.recommendations) {
      const row = rows.value.find((r) => r.no === item.item_no)
      if (!row || !item.recommendation) continue
      row.recommendation = item.recommendation
      row.aiOpen = true
      if (item.recommendation.path_id) ensureBatchForPath(row, item.recommendation.path_id)
    }
  } catch (err) {
    error.value = err instanceof Error ? err.message : '批量推荐失败'
  } finally {
    targets.forEach((row) => { row.recommending = false })
    batchLoading.value = false
  }
}

function openAiMenu(row: Row): void {
  if (row.recommending || row.recommendation || row.choice === 'direct_ai') return
  row.aiOpen = !row.aiOpen
}

function chooseAiRecommend(row: Row): void {
  row.aiOpen = false
  if (row.recommendation || row.recommending) return
  enqueueRecommendation(row)
}

function chooseDirectAi(row: Row): void {
  row.aiOpen = false
  row.recommendation = null
  row.choice = 'direct_ai'
  row.choiceSource = 'model'
}

function clearDirectAi(row: Row): void {
  row.choice = ''
  row.choiceSource = 'human'
}

function clearRecommendation(row: Row): void {
  row.recommendation = null
  row.choice = ''
  row.choiceSource = 'human'
}

function enqueueRecommendation(row: Row): void {
  row.recommending = true
  recommendQueue.push(row)
  void drainRecommendations()
}

async function drainRecommendations(): Promise<void> {
  // RKLLM 板端一次只能稳定处理少量请求，限制并发，避免 12 个不符合项同时打模型
  while (recommendActive < 2 && recommendQueue.length) {
    const row = recommendQueue.shift() as Row
    if (row.choice) {
      row.recommending = false
      continue
    }
    recommendActive++
    await recommendRow(row).finally(() => {
      recommendActive--
      void drainRecommendations()
    })
  }
}

async function recommendRow(row: Row, fastOnly = false): Promise<void> {
  row.recommending = true
  try {
    const res = await fetchKgRecommendation({
      item_no: row.no,
      item_name: row.name,
      reasons: row.reasons,
      other_text: row.otherText,
      top_k: 3,
      fast_only: fastOnly,
    })
    row.recommendation = res.recommendation
    if (res.recommendation?.path_id) ensureBatchForPath(row, res.recommendation.path_id)
  } catch {
    row.recommendation = null
  } finally {
    row.recommending = false
  }
}

function recommendedChoice(row: Row): string {
  const rec = row.recommendation
  if (!rec) return ''
  return rec.none ? 'none' : (rec.path_id || '')
}

function markChoice(row: Row): void {
  if (!row.recommendation) {
    row.choiceSource = 'human'
    return
  }
  row.choiceSource = row.choice === recommendedChoice(row)
    ? (row.recommendation.source === 'rule' ? 'rule' : 'model')
    : 'human_override'
}

function applyRecommendation(row: Row): void {
  const choice = recommendedChoice(row)
  if (!choice) return
  if (row.recommendation?.path_id) ensureBatchForPath(row, row.recommendation.path_id)
  row.choice = choice
  row.choiceSource = row.recommendation?.source === 'rule' ? 'rule' : 'model'
}

function auditSource(row: Row): 'human' | 'model' | 'rule' | 'human_override' {
  if (!row.recommendation) return 'human'
  if (row.choice !== recommendedChoice(row)) return 'human_override'
  return row.recommendation.source === 'rule' ? 'rule' : 'model'
}

function top3Of(row: Row) {
  return visibleCandidates(row).map((c) => ({
    rank: c.rank,
    path_id: c.path_id,
    path_summary: c.path_summary,
    component: c.component,
    system: c.system,
    score: c.score,
  }))
}

function chainOf(c: { states: string[]; path_summary: string }): string {
  /* path_summary 以部件名开头；状态链本身在 states 中 */
  return c.states.length ? c.states.join(' → ') : c.path_summary
}

function rankOf(row: Row): number | null {
  if (!row.result || row.choice === 'none') return null
  return row.result.candidates.find((c) => c.path_id === row.choice)?.rank ?? null
}

async function generate(): Promise<void> {
  if (!canGenerate.value || generating.value) return
  generating.value = true
  error.value = ''
  try {
    const selections: KgSelection[] = []
    for (const row of rows.value) {
      if (row.choice === 'direct_ai') {
        const candidates = (row.result?.candidates || []).slice(0, aiPromptCount.value)
        if (!candidates.length) {
          selections.push({
            item_no: row.no, path_id: null, decision: 'no_candidate',
            rank: null, query: row.result?.query || '',
          })
        } else {
          for (const candidate of candidates) {
            selections.push({
              item_no: row.no, path_id: candidate.path_id, decision: 'selected',
              rank: candidate.rank, query: row.result?.query || '',
            })
          }
        }
        continue
      }
      selections.push({
        item_no: row.no,
        path_id: row.choice === 'none' || !row.choice ? null : row.choice,
        decision: row.choice === 'none' || !row.choice ? 'no_candidate' : 'selected',
        rank: rankOf(row),
        query: row.result?.query || '',
      })
    }
    // 审计日志：失败不阻塞生成
    await Promise.all(selections.map((sel) => {
      const row = rows.value.find((r) => r.no === sel.item_no)
      const direct = row?.choice === 'direct_ai'
      return selectKgPath({
        report_id: store.reportId,
        item_no: sel.item_no,
        item_name: row?.name || '',
        query: sel.query || '',
        path_id: sel.path_id,
        decision: sel.decision,
        rank: sel.rank,
        top3: row ? top3Of(row) : [],
        selection_source: direct ? 'model' : (row ? auditSource(row) : 'human'),
        model_path_id: direct ? sel.path_id : (row?.recommendation?.path_id ?? null),
        model_reason: direct ? `前 ${aiPromptCount.value} 个候选直接拼接` : (row?.recommendation?.reason || ''),
      }).catch(() => null)
    }))
    // 把选择交给报告页；由报告页在填写区底部显示流式正文
    generationStore.setPending(selections)
    await router.replace({ path: '/' })
  } catch (err) {
    error.value = err instanceof Error ? err.message : '生成失败'
  } finally {
    generating.value = false
  }
}

function back(): void {
  router.push('/')
}
</script>

<template>
  <div class="kg-confirm">
    <header class="head">
      <div>
        <h1>故障路径确认</h1>
        <p class="sub">
          为每个不符合项选择最接近的故障演化路径；没有合适路径可选「无合适候选」，按规则表处置。
          点「AI 推荐」可自选：单轮推荐并查看推荐项，或直接把前 N 个候选拼入提示词。
        </p>
      </div>
      <div class="progress">
        <b>{{ doneCount }}/{{ rows.length }}</b> 已确认
        <span class="page-count">{{ currentIndex + 1 }}/{{ rows.length }}</span>
        <button
          v-if="remainingRows.length || batchLoading"
          class="btn tiny batch-btn"
          type="button"
          :disabled="batchLoading || !remainingRows.length"
          @click="recommendRemaining"
        >{{ batchLoading ? 'AI 批量推荐中…' : 'AI 推荐剩余 ' + Math.min(3, remainingRows.length) + ' 项' }}</button>
      </div>
    </header>

    <div v-if="loading" class="loading">正在检索候选路径…</div>

    <section v-for="row in visibleRows" :key="row.no" class="item">
      <div class="item-head">
        <h2>{{ row.no }}　{{ row.name }}</h2>
        <span v-if="row.result" class="hint">{{ row.result.item_system }} · {{ row.result.query_terms.join('、') }}</span>
      </div>
      <div class="inputs">
        <p v-for="(reason, idx) in row.reasons" :key="idx" class="reason">· {{ reason }}</p>
        <p v-if="row.otherText" class="reason other">其他：{{ row.otherText }}</p>
      </div>

      <p v-if="row.loading" class="muted">检索中…</p>
      <div v-else-if="row.error" class="error-line">
        {{ row.error }}
        <button class="btn tiny" type="button" @click="loadRow(row)">重试</button>
      </div>
      <div v-else>
        <div class="row-actions">
          <template v-if="row.choice === 'direct_ai'">
            <span class="direct-hint">已选择：前 {{ aiPromptCount }} 个候选直接拼入提示词</span>
            <button class="btn tiny" type="button" @click="clearDirectAi(row)">取消选择</button>
          </template>

          <template v-else-if="row.recommendation">
            <span class="ai-badge">AI 推荐</span>
            <span v-if="row.recommendation.none">
              建议「无合适候选」：{{ row.recommendation.reason || '未匹配到候选路径' }}
            </span>
            <span v-else>
              #{{ row.recommendation.rank }}　{{ row.recommendation.reason || '候选路径' }}
            </span>
            <button
              v-if="row.choice !== recommendedChoice(row)"
              class="btn tiny"
              type="button"
              @click="applyRecommendation(row)"
            >采用</button>
            <button class="ai-close" type="button" title="清除推荐" @click="clearRecommendation(row)">×</button>
          </template>

          <template v-else>
            <button
              class="btn tiny ai-trigger"
              type="button"
              :disabled="batchLoading || row.recommending"
              @click="openAiMenu(row)"
            >{{ row.recommending ? 'AI 推荐中…' : 'AI 推荐' }}</button>
          </template>

          <div v-if="row.aiOpen" class="ai-popover" @click.stop>
            <button class="popover-close" type="button" title="关闭" @click="row.aiOpen = false">×</button>
            <button class="popover-option" type="button" @click="chooseAiRecommend(row)">
              <b>单轮 AI 推荐</b>
              <span>先看 AI 推荐项，再决定是否采用；会多等几秒</span>
            </button>
            <button class="popover-option" type="button" @click="chooseDirectAi(row)">
              <b>将前 {{ aiPromptCount }} 个候选拼接进提示词</b>
              <span>不等待推荐，直接全权交给生成模型；更省时间</span>
            </button>
          </div>
        </div>

        <div class="candidates">
        <label
          v-for="c in visibleCandidates(row)"
          :key="c.path_id"
          class="candidate"
          :class="{ on: row.choice === c.path_id, recommended: row.recommendation?.path_id === c.path_id }"
        >
          <input v-model="row.choice" type="radio" :value="c.path_id" @change="markChoice(row)" />
          <span class="body">
            <span class="path">
              #{{ c.rank }}　{{ chainOf(c) }}
              <span v-if="row.recommendation?.path_id === c.path_id" class="ai-badge">
                AI 推荐
                <template v-if="row.recommendation.cached">·缓存</template>
              </span>
            </span>
            <span class="meta">系统：{{ c.system || '—' }}　部位：{{ c.component || '—' }}　匹配度 {{ (c.score * 100).toFixed(1) }}</span>
            <span class="line"><b>风险：</b>{{ c.risk || '—' }}　<b>整改：</b>{{ c.action || '—' }}</span>
            <span class="terms">命中：{{ c.matched_terms.join('、') || '—' }}</span>
          </span>
        </label>
        <label class="candidate none" :class="{ on: row.choice === 'none', recommended: row.recommendation?.none }">
          <input v-model="row.choice" type="radio" value="none" @change="markChoice(row)" />
          <span class="body">
            <span class="path">无合适候选</span>
            <span class="meta">不引用图谱路径，只按规则表的风险类别与处置生成</span>
          </span>
        </label>
        </div>
        <div v-if="(row.result?.candidates || []).length > 3" class="batch-nav">
          <button
            class="btn tiny"
            type="button"
            :disabled="row.batch <= 0"
            @click="setBatch(row, row.batch - 1)"
          >上一批</button>
          <span>第 {{ row.batch + 1 }}/{{ batchCount(row) }} 批</span>
          <button
            class="btn tiny"
            type="button"
            :disabled="row.batch >= batchCount(row) - 1"
            @click="setBatch(row, row.batch + 1)"
          >下一批</button>
        </div>
      </div>
    </section>

    <button
      v-if="rows.length > 1"
      class="page-turn prev"
      type="button"
      aria-label="上一项"
      :disabled="!hasPrev"
      @click="goPage(-1)"
    >‹</button>
    <button
      v-if="rows.length > 1"
      class="page-turn next"
      type="button"
      aria-label="下一项"
      :disabled="!hasNext"
      @click="goPage(1)"
    >›</button>

    <footer class="foot">
      <p v-if="error" class="error-line">{{ error }}</p>
      <div class="foot-actions">
        <button class="btn" type="button" :disabled="generating" @click="back">返回修改</button>
        <button class="btn primary" type="button" :disabled="!canGenerate || generating" @click="generate">
          {{ generating ? '生成中…' : '生成报告' }}
        </button>
      </div>
      <p class="tip">AI 只做预选，最终由操作员确认；选中路径仅作为报告候选证据，标注「操作员选定、未签核」。</p>
    </footer>
  </div>
</template>

<style scoped>
.kg-confirm {
  max-width: 1180px;
  margin: 0 auto;
  padding: 18px 20px 120px;
}
.head { display: flex; justify-content: space-between; gap: 16px; align-items: flex-start; margin-bottom: 14px; }
h1 { margin: 0; font-size: 21px; }
.sub { margin: 4px 0 0; color: var(--c-muted); font-size: 12.5px; line-height: 1.5; }
.progress { background: #eef6f8; color: #1b5e7a; border-radius: 999px; padding: 6px 14px; font-size: 12.5px; white-space: nowrap; }
.page-count { margin-left: 8px; color: #5b7; font-weight: 700; }
.page-turn {
  position: fixed;
  top: 50%;
  transform: translateY(-50%);
  z-index: 260;
  width: 52px;
  height: 72px;
  border: 1px solid rgba(27, 94, 122, 0.35);
  border-radius: 14px;
  background: rgba(255, 255, 255, 0.94);
  color: #1b5e7a;
  font-size: 38px;
  line-height: 1;
  cursor: pointer;
  box-shadow: 0 8px 22px rgba(20, 50, 70, 0.18);
}
.page-turn.prev { left: 64px; }
.page-turn.next { right: 18px; }
.page-turn:disabled { opacity: 0.28; cursor: default; box-shadow: none; }
@media (max-width: 900px) {
  .page-turn { width: 46px; height: 64px; font-size: 32px; }
  .page-turn.prev { left: 58px; }
  .page-turn.next { right: 10px; }
}
.batch-btn { margin-left: 8px; }
.loading { padding: 30px; text-align: center; color: var(--c-muted); }
.item {
  background: #fff;
  border: 1px solid var(--c-border, #dfe6ea);
  border-radius: 10px;
  padding: 14px 16px;
  margin-bottom: 12px;
}
.item-head { display: flex; align-items: baseline; gap: 12px; flex-wrap: wrap; }
.item-head h2 { margin: 0; font-size: 15px; }
.hint { font-size: 11.5px; color: #879; }
.inputs { margin: 8px 0 10px; }
.reason { margin: 2px 0; font-size: 12.5px; line-height: 1.5; color: #445; }
.reason.other { color: #8a5a00; }
.candidates { display: grid; gap: 8px; }
.candidate {
  display: flex;
  gap: 10px;
  align-items: flex-start;
  border: 1.5px solid #e3eaee;
  border-radius: 9px;
  padding: 10px 12px;
  cursor: pointer;
}
.candidate.on { border-color: #1b5e7a; background: #f5fbfc; }
.candidate.recommended { border-color: #2c8a5a; }
.candidate.recommended.on { border-color: #1b5e7a; }
.row-actions {
  position: relative;
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  margin: 6px 0 4px;
}
.row-actions .btn.tiny { margin-left: 0; }
.direct-hint {
  color: #2c8a5a;
  font-size: 11px;
}
.ai-trigger { margin: 2px 0; }
.ai-close {
  width: 24px; height: 24px; padding: 0; border: 0; background: transparent;
  color: #879; font-size: 17px; line-height: 1; cursor: pointer;
}
.ai-popover {
  position: absolute;
  top: calc(100% + 4px);
  left: 0;
  z-index: 40;
  width: min(430px, calc(100vw - 36px));
  padding: 8px 38px 8px 8px;
  border: 1px solid #cfe0e6;
  border-radius: 10px;
  background: #fff;
  box-shadow: 0 10px 28px rgba(20, 50, 65, 0.18);
}
.popover-close {
  position: absolute; top: 5px; right: 6px;
  width: 24px; height: 24px; padding: 0; border: 0; border-radius: 6px;
  background: #eef5f7; color: #567; font-size: 17px; line-height: 1; cursor: pointer;
}
.popover-option {
  display: flex; flex-direction: column; gap: 2px;
  width: 100%; padding: 8px 9px; border: 0; border-radius: 7px;
  background: transparent; color: #234; text-align: left; cursor: pointer;
}
.popover-option:hover { background: #f2faf5; }
.popover-option b { font-size: 12.5px; color: #1b5e7a; }
.popover-option span { font-size: 11px; color: #667; line-height: 1.35; }

.ai-badge {
  display: inline-block;
  padding: 1px 7px;
  border-radius: 999px;
  background: #2c8a5a;
  color: #fff;
  font-size: 10.5px;
  font-weight: 700;
  white-space: nowrap;
}
.candidate input { margin-top: 3px; }
.body { display: flex; flex-direction: column; gap: 4px; min-width: 0; }
.path { font-size: 13px; font-weight: 600; line-height: 1.5; color: #223; }
.meta { font-size: 11.5px; color: #667; }
.line { font-size: 12px; color: #445; line-height: 1.5; }
.terms { font-size: 11px; color: #2c6b42; }
.batch-nav { display: flex; align-items: center; gap: 8px; margin-top: 6px; color: #667; font-size: 11.5px; }
.batch-nav .btn.tiny { margin-left: 0; }
.candidate.none { background: #fafafa; }
.candidate.none .path { color: #556; }
.muted { color: #879; font-size: 12.5px; }
.error-line { color: #b3261e; font-size: 12.5px; margin: 6px 0; }
.btn {
  border: 1px solid #c9d6dd;
  background: #f7fafb;
  color: #233;
  border-radius: 8px;
  padding: 8px 16px;
  font-size: 13px;
  cursor: pointer;
}
.btn.tiny { padding: 3px 10px; font-size: 11.5px; margin-left: 8px; }
.btn.primary { background: #1b5e7a; border-color: #1b5e7a; color: #fff; }
.btn:disabled { opacity: .45; cursor: not-allowed; }
.foot { position: sticky; bottom: 0; background: rgba(247, 250, 251, .96); padding: 12px 0 8px; border-top: 1px solid #e3eaee; margin-top: 16px; }
.foot-actions { display: flex; justify-content: flex-end; gap: 10px; }
.tip { margin: 8px 0 0; text-align: right; font-size: 11.5px; color: #879; }
@media (max-width: 700px) {
  .kg-confirm { padding: 12px 10px 100px; }
  .head { flex-direction: column; }
  .foot-actions { justify-content: stretch; }
  .foot-actions .btn { flex: 1; }
}

/* 一页确认：页面本身不滚动，候选区按视口自适应 */
.kg-confirm {
  width: 100%;
  max-width: none;
  margin: 0;
  height: calc(100vh - 52px);
  box-sizing: border-box;
  padding: 8px 18px 8px;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.head {
  flex: 0 0 auto;
  margin-bottom: 6px;
  align-items: center;
}
h1 { font-size: 18px; }
.sub { font-size: 11.5px; margin-top: 2px; }
.item {
  flex: 1 1 auto;
  min-height: 0;
  margin-bottom: 6px;
  padding: 8px 12px;
  display: flex;
  flex-direction: column;
  overflow: visible;
}
.item-head h2 { font-size: 14px; }
.inputs { margin: 4px 0 6px; }
.reason { font-size: 11.5px; line-height: 1.35; }
.item > div:last-child {
  min-height: 0;
  flex: 1 1 auto;
  display: flex;
  flex-direction: column;
}
.candidates {
  flex: 1 1 auto;
  min-height: 0;
  grid-template-columns: 1fr;
  gap: 5px;
  overflow-y: auto;
  padding-right: 2px;
}
.candidate { padding: 7px 9px; gap: 7px; min-width: 0; overflow: hidden; }
.path { font-size: 11.5px; line-height: 1.35; }
.meta, .terms { font-size: 10px; line-height: 1.3; }
.line { font-size: 10.5px; line-height: 1.3; }
.ai-line { margin: 3px 0; padding: 5px 8px; font-size: 11.5px; }
.ai-trigger { margin: 2px 0; }
.foot {
  flex: 0 0 auto;
  position: static;
  margin-top: 0;
  padding: 5px 0 2px;
  display: flex;
  align-items: center;
  gap: 10px;
}
.foot-actions { margin-left: auto; }
.tip { margin: 0; font-size: 10.5px; }
.error-line { margin: 2px 0; }

@media (max-height: 700px) {
  .kg-confirm { padding-top: 4px; padding-bottom: 4px; }
  .head { margin-bottom: 3px; }
  .sub, .tip { display: none; }
  .item { padding: 6px 10px; }
  .inputs { margin: 2px 0 4px; }
}
@media (max-width: 820px) {
  .candidates { grid-template-columns: 1fr; }
  .kg-confirm { padding-left: 10px; padding-right: 10px; }
  .path { font-size: 12.5px; }
  .meta, .line, .terms { font-size: 11px; }
}
</style>
