<script setup lang="ts">
/* 生成前的「故障路径确认」页：
   每个不符合项 / 其他填写 → Top3 候选 → 人工勾选 / 无合适候选 → 生成报告。 */
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { fetchKgCandidates, selectKgPath, type KgCandidatesResponse } from '@/api/kg'
import { useReportStore } from '@/stores/report'
import StreamingOverlay from '@/components/StreamingOverlay.vue'
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
}

const router = useRouter()
const store = useReportStore()
const rows = ref<Row[]>([])
const loading = ref(true)
const generating = ref(false)
const error = ref('')
const streamText = ref('')

const allChosen = computed(() => rows.value.length > 0 && rows.value.every((r) => !!r.choice))
const doneCount = computed(() => rows.value.filter((r) => !!r.choice).length)

onMounted(async () => {
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
    })
  }
  if (!rows.value.length) {
    await router.replace('/')
    return
  }
  await Promise.all(rows.value.map(loadRow))
  loading.value = false
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
      top_k: 3,
    })
    row.result = res
    if (!res.candidates.length) row.choice = 'none'
  } catch (err) {
    row.error = err instanceof Error ? err.message : '检索失败'
  } finally {
    row.loading = false
  }
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
  if (!allChosen.value || generating.value) return
  generating.value = true
  error.value = ''
  try {
    const selections: KgSelection[] = rows.value.map((row) => ({
      item_no: row.no,
      path_id: row.choice === 'none' ? null : row.choice,
      decision: row.choice === 'none' ? 'no_candidate' : 'selected',
      rank: rankOf(row),
      query: row.result?.query || '',
    }))
    // 审计日志：失败不阻塞生成
    await Promise.all(selections.map((sel) => selectKgPath({
      report_id: store.reportId,
      item_no: sel.item_no,
      item_name: rows.value.find((r) => r.no === sel.item_no)?.name || '',
      query: sel.query || '',
      path_id: sel.path_id,
      decision: sel.decision,
      rank: sel.rank,
      top3: [],
    }).catch(() => null)))
    streamText.value = ''
    const report = await store.generate(undefined, selections, (text) => {
      streamText.value += text
    })
    await router.replace({ path: '/', query: { section: 'reports', report: report.id } })
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
        </p>
      </div>
      <div class="progress">
        <b>{{ doneCount }}/{{ rows.length }}</b> 已确认
      </div>
    </header>

    <div v-if="loading" class="loading">正在检索候选路径…</div>

    <section v-for="row in rows" :key="row.no" class="item">
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
      <div v-else class="candidates">
        <label
          v-for="c in row.result?.candidates || []"
          :key="c.path_id"
          class="candidate"
          :class="{ on: row.choice === c.path_id }"
        >
          <input v-model="row.choice" type="radio" :value="c.path_id" />
          <span class="body">
            <span class="path">#{{ c.rank }}　{{ chainOf(c) }}</span>
            <span class="meta">系统：{{ c.system || '—' }}　部位：{{ c.component || '—' }}　匹配度 {{ (c.score * 100).toFixed(1) }}</span>
            <span class="line"><b>风险：</b>{{ c.risk || '—' }}　<b>整改：</b>{{ c.action || '—' }}</span>
            <span class="terms">命中：{{ c.matched_terms.join('、') || '—' }}</span>
          </span>
        </label>
        <label class="candidate none" :class="{ on: row.choice === 'none' }">
          <input v-model="row.choice" type="radio" value="none" />
          <span class="body">
            <span class="path">无合适候选</span>
            <span class="meta">不引用图谱路径，只按规则表的风险类别与处置生成</span>
          </span>
        </label>
      </div>
    </section>

    <footer class="foot">
      <p v-if="error" class="error-line">{{ error }}</p>
      <div class="foot-actions">
        <button class="btn" type="button" :disabled="generating" @click="back">返回修改</button>
        <button class="btn primary" type="button" :disabled="!allChosen || generating" @click="generate">
          {{ generating ? '生成中…' : '生成报告' }}
        </button>
      </div>
      <p class="tip">未全部确认时不能生成；选中路径仅作为报告候选证据，标注「操作员选定、未签核」。</p>
    </footer>
  </div>
  <StreamingOverlay v-if="generating" :text="streamText" />
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
.candidate input { margin-top: 3px; }
.body { display: flex; flex-direction: column; gap: 4px; min-width: 0; }
.path { font-size: 13px; font-weight: 600; line-height: 1.5; color: #223; }
.meta { font-size: 11.5px; color: #667; }
.line { font-size: 12px; color: #445; line-height: 1.5; }
.terms { font-size: 11px; color: #2c6b42; }
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
</style>
