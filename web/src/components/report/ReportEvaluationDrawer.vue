<script setup lang="ts">
/* 共用「评估填写内容」只读抽屉：
   - 报告查看页用它；
   - 报告生成中页也用它，避免维护两份相同结构。 */
import { computed, nextTick, reactive, ref, watch } from 'vue'
import InfoTable from '@/components/report/InfoTable.vue'
import { itemGroupName } from '@/domain/itemGroups'
import { reasonList } from '@/domain/validation'
import { useReportStore } from '@/stores/report'
import { renderMarkdown } from '@/utils/markdown'

const props = withDefaults(defineProps<{
  open: boolean
  analysisText?: string
  typing?: boolean
  typingText?: string
  inline?: boolean
  closable?: boolean
  autoScroll?: boolean
}>(), {
  analysisText: '',
  typing: false,
  typingText: '',
  inline: false,
  closable: true,
  autoScroll: true,
})

const emit = defineEmits<{ close: [] }>()
const store = useReportStore()
const refBody = ref<HTMLElement | null>(null)
const collapsed = reactive<Record<string, boolean>>({})

interface RefGroup {
  key: string
  name: string
  range: string
  items: typeof store.items
  total: number
  unfit: number
}

const refGroups = computed<RefGroup[]>(() => {
  const map = new Map<string, RefGroup>()
  for (const item of store.items) {
    const key = item.no.split('.')[0] || item.no
    let group = map.get(key)
    if (!group) {
      group = { key, name: itemGroupName(key), range: item.no, items: [], total: 0, unfit: 0 }
      map.set(key, group)
    }
    group.items.push(item)
    group.range = group.items.length === 1 ? item.no : group.items[0].no + '–' + item.no
    group.total += 1
    if (store.stateOf(item.no).result === '不符合') group.unfit += 1
  }
  return [...map.values()]
})

function resultOf(no: string): string {
  return store.stateOf(no).result || '未填'
}

function detailsOf(no: string): string[] {
  const state = store.stateOf(no)
  if (state.result !== '不符合') return []
  return reasonList(state)
}

function riskOf(no: string) {
  return store.generated?.risks?.[no]
}

function scrollBottom(): void {
  const body = refBody.value
  if (body) body.scrollTop = body.scrollHeight
}

function toggleGroup(key: string): void {
  collapsed[key] = !collapsed[key]
}

const analysis = computed(() => props.typing ? props.typingText : props.analysisText)

watch([() => props.open, () => props.typingText, () => props.analysisText], () => {
  if (!props.open || !props.autoScroll) return
  void nextTick(scrollBottom)
}, { immediate: true })
</script>

<template>
  <aside
    v-if="open"
    class="ref-panel"
    :class="{ inline }"
    aria-label="评估填写内容（只读）"
  >
    <div class="ref-head">
      <button v-if="closable" class="ref-close" type="button" title="收起" aria-label="收起" @click="emit('close')">
        ×
      </button>
      <b>评估填写内容</b>
      <span class="ref-tag">只读</span>
    </div>
    <div ref="refBody" class="ref-body">
      <h3>基础信息</h3>
      <InfoTable readonly :show-computed="true" class="ref-info" />

      <h3>检测项目（{{ store.items.length }} 项 · 不符合 {{ refGroups.reduce((n, g) => n + g.unfit, 0) }} 项）</h3>
      <table class="ref-items">
        <thead>
          <tr>
            <th rowspan="2" style="width: 56px">编号</th>
            <th rowspan="2">项目</th>
            <th rowspan="2" style="width: 62px">结果</th>
            <th colspan="3" class="ref-risk-head">风险评定值</th>
          </tr>
          <tr>
            <th style="width: 50px">严重程度</th>
            <th style="width: 50px">概率等级</th>
            <th style="width: 50px">风险类别</th>
          </tr>
        </thead>
        <tbody v-for="group in refGroups" :key="group.key">
          <tr class="ref-group">
            <td colspan="6">
              <button
                class="ref-group-toggle"
                type="button"
                :aria-expanded="!collapsed[group.key]"
                @click="toggleGroup(group.key)"
              >
                <span class="caret" :class="{ open: !collapsed[group.key] }">▸</span>
                <span class="ref-group-name">{{ group.key }} {{ group.name }}</span>
                <span class="ref-group-range">{{ group.range }}</span>
                <span class="ref-group-meta">{{ group.total }} 项 · 不符合 {{ group.unfit }}</span>
              </button>
            </td>
          </tr>
          <template v-if="!collapsed[group.key]">
            <template v-for="item in group.items" :key="item.no">
              <tr :class="{ 'ref-unfit': resultOf(item.no) === '不符合' }">
                <td class="ref-no">{{ item.no }}</td>
                <td>
                  {{ item.name }}<span v-if="item.sub" class="ref-sub">（{{ item.sub }}）</span>
                </td>
                <td class="ref-result" :class="{ unfit: resultOf(item.no) === '不符合' }">{{ resultOf(item.no) }}</td>
                <template v-if="riskOf(item.no)">
                  <td class="ref-risk">{{ riskOf(item.no)?.severity ?? '待确认' }}</td>
                  <td class="ref-risk">{{ riskOf(item.no)?.probability ?? '待确认' }}</td>
                  <td class="ref-risk">{{ riskOf(item.no)?.category }}</td>
                </template>
                <template v-else>
                  <td class="ref-risk">—</td>
                  <td class="ref-risk">—</td>
                  <td class="ref-risk">—</td>
                </template>
              </tr>
              <tr v-if="detailsOf(item.no).length" class="ref-reasons">
                <td></td>
                <td colspan="5">
                  <div class="ref-reasons-box">
                    <div class="ref-reasons-head">不符合项</div>
                    <ul class="ref-reasons-list">
                      <li v-for="(reason, i) in detailsOf(item.no)" :key="i">{{ reason }}</li>
                    </ul>
                  </div>
                </td>
              </tr>
            </template>
          </template>
        </tbody>
      </table>

      <div v-if="analysisText || typingText" class="ref-analysis">
        <h3>文本分析报告</h3>
        <div v-if="typing" class="ref-typing">生成中…</div>
        <div class="md" v-html="renderMarkdown(analysis)" />
      </div>
    </div>
  </aside>
</template>

<style scoped>
.ref-panel {
  position: fixed;
  top: 0;
  right: 0;
  bottom: 0;
  width: min(560px, 100vw);
  display: flex;
  flex-direction: column;
  background: var(--c-panel);
  border-left: 1px solid var(--c-line);
  box-shadow: -8px 0 28px rgba(0, 0, 0, 0.16);
  z-index: 500;
}
.ref-panel.inline {
  position: static;
  width: 100%;
  height: 100%;
  border: 1px solid var(--c-line);
  border-radius: var(--radius);
  box-shadow: none;
}
.ref-head {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 12px 14px;
  border-bottom: 1px solid var(--c-line);
}
.ref-head b { font-family: var(--font-bold); font-size: 14px; color: var(--c-primary); }
.ref-tag { padding: 0 6px; border-radius: 8px; background: var(--c-primary-soft); color: var(--c-primary); font-size: 10.5px; line-height: 16px; }
.ref-close { flex: 0 0 auto; width: 32px; height: 32px; padding: 0; border: 1px solid var(--c-line); border-radius: 8px; background: #fff; color: var(--c-primary); font-size: 20px; line-height: 1; cursor: pointer; }
.ref-body { flex: 1; min-height: 0; overflow: auto; padding: 12px 14px 28px; scroll-behavior: smooth; }
.ref-body h3 { margin: 16px 0 8px; font-family: var(--font-bold); font-size: 13px; color: var(--c-secondary); }
.ref-body h3:first-child { margin-top: 0; }
.ref-items {
  width: 100%;
  border-collapse: collapse;
  font-size: 12.5px;
}
.ref-info :deep(th),
.ref-info :deep(td) {
  display: table-cell;
  width: auto;
  height: 30px;
  padding: 2px 4px;
  border: 1px solid var(--c-line);
  font-size: 12px;
  line-height: 16px;
  white-space: normal;
}
.ref-info :deep(.info) { table-layout: fixed; }
.ref-items th,
.ref-items td {
  border: 1px solid var(--c-line);
  padding: 5px 6px;
  text-align: left;
  vertical-align: top;
}
.ref-items thead th { background: var(--c-head); color: var(--c-text); }
.ref-no { color: var(--c-secondary); white-space: nowrap; }
.ref-result { white-space: nowrap; }
.ref-result.unfit { color: var(--c-danger); font-weight: 700; }
.ref-risk-head,
.ref-items thead tr:nth-child(2) th { text-align: center; }
.ref-risk { text-align: center; color: var(--c-text); white-space: nowrap; }
.ref-sub { color: var(--c-muted); font-size: 11.5px; }
.ref-items tr.ref-unfit td { background: #fef0f0; }
.ref-items tr.ref-reasons td { background: #fef7f7; color: var(--c-text); font-size: 12px; line-height: 1.7; }
.ref-reasons-box { padding: 2px 0 4px; }
.ref-reasons-head { margin-bottom: 4px; color: var(--c-danger); font-weight: 700; font-size: 12px; }
.ref-reasons-list { margin: 0; padding: 0; list-style: none; }
.ref-reasons-list li { padding: 1px 0 1px 2px; }
.ref-reasons-list li + li { margin-top: 2px; }
.ref-items .ref-group td { padding: 0; background: var(--c-head); }
.ref-group-toggle {
  display: flex; align-items: center; gap: 8px; width: 100%;
  padding: 6px 8px; border: 0; background: none; color: var(--c-text);
  font: inherit; font-size: 12px; text-align: left; cursor: pointer;
}
.ref-group-toggle .caret { color: var(--c-primary); font-size: 10px; transition: transform 0.15s; }
.ref-group-toggle .caret.open { transform: rotate(90deg); }
.ref-group-name { font-weight: 700; }
.ref-group-range { color: var(--c-muted); font-size: 11px; }
.ref-group-meta { margin-left: auto; color: var(--c-secondary); font-size: 11px; white-space: nowrap; }

.ref-analysis { margin: 18px 0 8px; padding-top: 12px; border-top: 1px solid var(--c-line); }
.ref-analysis h3 { margin: 0 0 8px; }
.ref-analysis .md { line-height: 1.75; font-size: 13px; color: #223; }
.ref-analysis .md :deep(h1),
.ref-analysis .md :deep(h2),
.ref-analysis .md :deep(h3) { margin: 8px 0 6px; color: #1b5e7a; }
.ref-analysis .md :deep(p) { margin: 0 0 8px; }
.ref-analysis .md :deep(ul),
.ref-analysis .md :deep(ol) { margin: 4px 0 8px; padding-left: 20px; }
.ref-typing { color: #6b8b98; font-size: 11.5px; margin-bottom: 4px; }
</style>
