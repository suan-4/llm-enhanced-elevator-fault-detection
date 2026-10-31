<script setup lang="ts">
/* 知识图谱检索演示页（MVP）：Top3 + 人工勾选 + 证据包预览。
   仅用于验证检索/摘要/选择效果，未接入正式报告生成。 */
import { computed, onMounted, ref } from 'vue'
import { fetchJteItems } from '@/api/report'
import {
  fetchKgCandidates, fetchKgStatus, selectKgPath,
  type KgCandidate, type KgCandidatesResponse,
} from '@/api/kg'
import type { JteItem } from '@/types/api'

const items = ref<JteItem[]>([])
const itemNo = ref('')
const selectedReasons = ref<string[]>([])
const otherText = ref('')
const loading = ref(false)
const error = ref('')
const result = ref<KgCandidatesResponse | null>(null)
const selectedPathId = ref('')
const notice = ref('')
const status = ref<{ available: boolean; paths: number; items: number } | null>(null)

const currentItem = computed(() => items.value.find((it) => it.no === itemNo.value) || null)
const selectedCandidate = computed<KgCandidate | null>(
  () => result.value?.candidates.find((c) => c.path_id === selectedPathId.value) || null,
)
function chainOf(c: { states: string[]; path_summary: string }): string {
  /* path_summary 是「部件 → 状态 → ... → 风险」的阅读串；真正的状态链在 states 里 */
  return c.states.length ? c.states.join(' → ') : c.path_summary
}

const top3 = computed(() =>
  (result.value?.candidates || []).map((c) => ({
    rank: c.rank, path_id: c.path_id, path_summary: c.path_summary,
    component: c.component, system: c.system, score: c.score,
  })),
)

onMounted(async () => {
  try {
    const [jte, st] = await Promise.all([fetchJteItems(), fetchKgStatus().catch(() => null)])
    items.value = jte.items
    itemNo.value = jte.items[0]?.no || ''
    if (st) status.value = st
  } catch (err) {
    error.value = err instanceof Error ? err.message : '加载条目失败'
  }
})

function toggleReason(text: string): void {
  const i = selectedReasons.value.indexOf(text)
  if (i >= 0) selectedReasons.value.splice(i, 1)
  else selectedReasons.value.push(text)
}

async function search(): Promise<void> {
  if (!itemNo.value) return
  if (!selectedReasons.value.length && !otherText.value.trim()) {
    error.value = '请至少勾选一条不符合情形，或填写「其他」描述'
    return
  }
  loading.value = true
  error.value = ''
  notice.value = ''
  result.value = null
  selectedPathId.value = ''
  try {
    result.value = await fetchKgCandidates({
      item_no: itemNo.value,
      item_name: currentItem.value?.name || '',
      reasons: selectedReasons.value,
      other_text: otherText.value.trim(),
      top_k: 3,
    })
  } catch (err) {
    error.value = err instanceof Error ? err.message : '检索失败'
  } finally {
    loading.value = false
  }
}

async function confirm(decision: 'selected' | 'no_candidate'): Promise<void> {
  if (!result.value) return
  if (decision === 'selected' && !selectedPathId.value) {
    error.value = '请先选中一条候选路径'
    return
  }
  try {
    const rank = selectedCandidate.value?.rank ?? null
    const res = await selectKgPath({
      item_no: result.value.item_no,
      item_name: result.value.item_name,
      query: result.value.query,
      path_id: decision === 'selected' ? selectedPathId.value : null,
      decision,
      rank,
      top3: top3.value,
    })
    notice.value = decision === 'selected'
      ? `已记录选择 #${res.id}（${selectedPathId.value}）`
      : `已记录「无合适候选」#${res.id}`
  } catch (err) {
    error.value = err instanceof Error ? err.message : '保存失败'
  }
}
</script>

<template>
  <div class="kg-demo">
    <header class="head">
      <div>
        <h1>知识图谱检索</h1>
        <p class="sub">GraphRAG 风格 Top3 · 人工勾选 · 证据包预览（MVP，不写入正式报告）</p>
      </div>
      <span v-if="status" class="badge" :class="{ off: !status.available }">
        {{ status.available ? `${status.paths} 条路径 / ${status.items} 项` : '索引不可用' }}
      </span>
    </header>

    <section class="panel">
      <div class="row">
        <label class="field">
          <span>评估项</span>
          <select v-model="itemNo" class="input" @change="selectedReasons = []; result = null">
            <option v-for="it in items" :key="it.no" :value="it.no">{{ it.no }}　{{ it.name }}</option>
          </select>
        </label>
      </div>

      <div v-if="currentItem" class="field">
        <span>不符合情形（可多选）</span>
        <div class="opts">
          <label v-for="(opt, idx) in currentItem.opts" :key="idx" class="opt">
            <input
              type="checkbox"
              :checked="selectedReasons.includes(opt)"
              @change="toggleReason(opt)"
            />
            <span>{{ opt }}</span>
          </label>
          <p v-if="!currentItem.opts.length" class="muted">该条没有可选情形，请用下方「其他」描述。</p>
        </div>
      </div>

      <label class="field">
        <span>其他（自行填写）</span>
        <textarea v-model="otherText" class="input textarea" rows="2"
          placeholder="例：制动器柱塞发涩，松闸后回位慢" />
      </label>

      <div class="actions">
        <button class="btn primary" type="button" :disabled="loading" @click="search">
          {{ loading ? '检索中…' : '检索 Top3' }}
        </button>
        <button class="btn" type="button" :disabled="loading || !result" @click="search">重新检索</button>
      </div>
      <p v-if="error" class="error">{{ error }}</p>
      <p v-if="notice" class="notice">{{ notice }}</p>
    </section>

    <template v-if="result">
      <section class="panel summary">
        <h2>系统级摘要</h2>
        <p>{{ result.summary.text }}</p>
        <div class="chips">
          <span class="chip">检索词：{{ result.query_terms.join('、') || '—' }}</span>
          <span class="chip">系统：{{ result.summary.systems.join('、') || '—' }}</span>
          <span class="chip">部件：{{ result.summary.components.join('、') || '—' }}</span>
        </div>
      </section>

      <section class="cards">
        <article
          v-for="c in result.candidates"
          :key="c.path_id"
          class="candidate"
          :class="{ on: selectedPathId === c.path_id }"
          @click="selectedPathId = c.path_id"
        >
          <div class="cand-head">
            <label class="radio">
              <input v-model="selectedPathId" type="radio" :value="c.path_id" />
              <b>#{{ c.rank }}</b>
            </label>
            <span class="score">匹配度 {{ (c.score * 100).toFixed(1) }}</span>
            <span class="conf">候选 · confidence {{ c.confidence }} · verified {{ c.verified }}</span>
          </div>
          <p class="path">{{ chainOf(c) }}</p>
          <p class="meta">系统：{{ c.system || '—' }}　部位：{{ c.component || '—' }}</p>
          <p class="risk">风险：{{ c.risk || '—' }}</p>
          <p class="line"><b>检查：</b>{{ c.inspection || '—' }}</p>
          <p class="line"><b>整改：</b>{{ c.action || '—' }}</p>
          <p class="line"><b>复验：</b>{{ c.verification || '—' }}</p>
          <p v-if="c.matched_terms.length" class="terms">命中：{{ c.matched_terms.join('、') }}</p>
          <details>
            <summary>查看状态链 / 机理 / 条款 / 来源</summary>
            <p><b>状态链：</b>{{ c.states.join(' → ') || '—' }}</p>
            <p><b>机理：</b>{{ c.mechanism_steps.join('；') || '—' }}</p>
            <p><b>条款：</b>{{ c.clause.standard_code || '' }} {{ c.clause.clause_no || '' }} {{ c.clause.title || '' }}</p>
            <p><b>来源：</b>{{ c.source_refs.length }} 条</p>
          </details>
        </article>
        <p v-if="!result.candidates.length" class="empty">没有命中候选，可点「无合适候选」走规则处置。</p>
      </section>

      <section class="panel actions-panel">
        <button class="btn primary" type="button" :disabled="!selectedPathId" @click="confirm('selected')">
          确认选中路径
        </button>
        <button class="btn danger" type="button" @click="confirm('no_candidate')">无合适候选</button>
      </section>

      <section v-if="selectedCandidate" class="panel evidence">
        <h2>将交给大模型的证据包（预览）</h2>
        <pre>{{ JSON.stringify({
          path_id: selectedCandidate.path_id,
          path_summary: selectedCandidate.path_summary,
          component: selectedCandidate.component,
          system: selectedCandidate.system,
          states: selectedCandidate.states,
          mechanism_steps: selectedCandidate.mechanism_steps,
          trigger_condition: selectedCandidate.trigger_condition,
          barrier_condition: selectedCandidate.barrier_condition,
          risk: selectedCandidate.risk,
          inspection: selectedCandidate.inspection,
          acceptance_basis: selectedCandidate.acceptance_basis,
          action: selectedCandidate.action,
          verification: selectedCandidate.verification,
          clause: selectedCandidate.clause,
          confidence: selectedCandidate.confidence,
          verified: selectedCandidate.verified,
          source_refs: selectedCandidate.source_refs,
        }, null, 2) }}</pre>
      </section>
    </template>
  </div>
</template>

<style scoped>
.kg-demo {
  max-width: 1180px;
  margin: 0 auto;
  padding: 20px 20px 60px;
}
.head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 16px;
}
h1 { margin: 0; font-size: 21px; }
.sub { margin: 4px 0 0; color: var(--c-muted); font-size: 12.5px; }
.badge {
  border-radius: 999px;
  padding: 5px 12px;
  background: #e8f5e9;
  color: #1b5e20;
  font-size: 12px;
  white-space: nowrap;
}
.badge.off { background: #fde7e7; color: #b3261e; }
.panel {
  background: #fff;
  border: 1px solid var(--c-border, #dfe6ea);
  border-radius: 10px;
  padding: 14px 16px;
  margin-bottom: 14px;
}
.row { display: flex; gap: 14px; align-items: flex-end; }
.field { display: flex; flex-direction: column; gap: 6px; margin-bottom: 10px; font-size: 12.5px; }
.field > span { color: #445; font-weight: 600; }
.input {
  border: 1px solid #c9d6dd;
  border-radius: 7px;
  padding: 8px 10px;
  font-size: 13px;
  background: #fff;
  color: #222;
}
.textarea { resize: vertical; font-family: inherit; }
.opts {
  display: flex;
  flex-direction: column;
  gap: 4px;
  max-height: 220px;
  overflow-y: auto;
  border: 1px solid #eef2f4;
  border-radius: 8px;
  padding: 8px 10px;
}
.opt { display: flex; gap: 8px; align-items: flex-start; line-height: 1.45; }
.opt input { margin-top: 3px; }
.muted { color: #879; font-size: 12px; margin: 4px 0; }
.actions { display: flex; gap: 10px; }
.btn {
  border: 1px solid #c9d6dd;
  background: #f7fafb;
  color: #233;
  border-radius: 8px;
  padding: 8px 16px;
  font-size: 13px;
  cursor: pointer;
}
.btn.primary { background: #1b5e7a; border-color: #1b5e7a; color: #fff; }
.btn.danger { background: #fff1f0; border-color: #f3c3bf; color: #b3261e; }
.btn:disabled { opacity: .45; cursor: not-allowed; }
.error { margin: 10px 0 0; color: #b3261e; font-size: 12.5px; }
.notice { margin: 10px 0 0; color: #1b5e20; font-size: 12.5px; }
.summary h2 { margin: 0 0 6px; font-size: 15px; }
.summary p { margin: 0 0 8px; line-height: 1.65; font-size: 13px; }
.chips { display: flex; flex-wrap: wrap; gap: 6px; }
.chip {
  background: #eef6f8;
  border-radius: 999px;
  padding: 3px 10px;
  color: #285;
  font-size: 11.5px;
}
.cards { display: grid; gap: 10px; }
.candidate {
  background: #fff;
  border: 1.5px solid #dfe6ea;
  border-radius: 10px;
  padding: 12px 14px;
  cursor: pointer;
}
.candidate.on { border-color: #1b5e7a; box-shadow: 0 0 0 2px rgba(27, 94, 122, .12); }
.cand-head { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.radio { display: flex; align-items: center; gap: 6px; }
.score { font-size: 12px; color: #1b5e7a; font-weight: 700; }
.conf { margin-left: auto; font-size: 11px; color: #9a6a00; background: #fff8e1; padding: 2px 8px; border-radius: 999px; }
.path { margin: 8px 0 4px; font-size: 13.5px; font-weight: 600; line-height: 1.5; }
.meta { margin: 0 0 4px; font-size: 12px; color: #567; }
.risk { margin: 0 0 6px; font-size: 12px; color: #b3261e; }
.line { margin: 2px 0; font-size: 12.3px; line-height: 1.55; }
.terms { margin: 6px 0 0; font-size: 11.5px; color: #285; }
details { margin-top: 6px; font-size: 12px; color: #445; line-height: 1.55; }
details summary { cursor: pointer; color: #1b5e7a; }
.empty { color: #879; padding: 18px; text-align: center; }
.actions-panel { display: flex; gap: 10px; align-items: center; }
.evidence pre {
  max-height: 360px;
  overflow: auto;
  background: #0f1720;
  color: #d7e3ea;
  border-radius: 8px;
  padding: 12px;
  font-size: 11.5px;
  line-height: 1.5;
}
@media (max-width: 700px) {
  .kg-demo { padding: 12px 10px 40px; }
  .head { flex-direction: column; }
  .cand-head .conf { margin-left: 0; }
}
</style>
