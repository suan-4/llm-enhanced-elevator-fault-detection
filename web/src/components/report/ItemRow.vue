<script setup lang="ts">
import { computed, ref } from 'vue'
import { itemProblem } from '@/domain/validation'
import { useReportStore } from '@/stores/report'
import type { JteItem } from '@/types/api'

const props = defineProps<{ item: JteItem }>()
const store = useReportStore()
const state = computed(() => store.stateOf(props.item.no))
const problem = computed(() => itemProblem(state.value))
const unfit = computed(() => state.value.result === '不符合')
const otherTexts = computed(() => {
  if (!state.value.otherTexts) state.value.otherTexts = []
  return state.value.otherTexts
})
const deleteIndex = ref<number | null>(null)

const rowId = computed(() => 'row-' + props.item.no.replace('.', '-'))
const reasonsId = computed(() => rowId.value + '-reasons')

const RESULTS = ['符合', '不符合', '无此项'] as const

/* 「其他」与清单选项二选一，停用内容仍保留在草稿中，不参与评定。 */
const otherOn = computed(() => state.value.other)
const hasReasons = computed(() => !otherOn.value && state.value.reasons.length > 0)
const reasonsLocked = computed(() => unfit.value && otherOn.value && !state.value.legacyCombined)
const otherLocked = computed(() => !unfit.value || (hasReasons.value && !state.value.legacyCombined))

function setResult(value: (typeof RESULTS)[number]): void {
  state.value.result = value
}

/* 三态/情形都走「点 label 自己改状态」，而不是让浏览器去激活里面的
   <input type=radio|checkbox>：
   1) 输入框聚焦会让板端弹出软键盘（只有要打字时才该弹）；
   2) 隐藏 input 抢焦点还会把整页滚走（见 styles/base.css .seg input 的说明）。
   鼠标/触摸走 label 的 @click.prevent，键盘仍走 input 的 @change，两条路都能用。 */
function toggleReason(text: string, checked: boolean): void {
  if (reasonsLocked.value) return
  state.value.legacyCombined = false
  const list = state.value.reasons
  const index = list.indexOf(text)
  if (checked && index < 0) list.push(text)
  if (!checked && index >= 0) list.splice(index, 1)
  // 二选一：只要选了清单项，「其他」就让位并置灰
  if (list.length) {
    state.value.other = false
  }
}

/** 点 label 时默认激活已被拦住，所以按「点击前」的状态取反 */
function pickReason(text: string): void {
  if (reasonsLocked.value) return
  toggleReason(text, !state.value.reasons.includes(text))
}

function toggleOther(): void {
  if (otherLocked.value) return
  state.value.legacyCombined = false
  state.value.other = !state.value.other
  if (state.value.other && !state.value.otherTexts?.length) state.value.otherTexts = ['']
  // Inactive inputs remain in the draft editing metadata, not in risk assessment.
}

function addOther(): void {
  if (otherLocked.value) return
  state.value.legacyCombined = false
  state.value.other = true
  if (!state.value.otherTexts?.length) state.value.otherTexts = ['']
  state.value.otherTexts.push('')
  deleteIndex.value = null
}

function askDeleteOther(index: number): void {
  deleteIndex.value = index
}

function cancelDeleteOther(): void {
  deleteIndex.value = null
}

function confirmDeleteOther(index: number): void {
  const list = otherTexts.value
  if (index < 0 || index >= list.length) return
  list.splice(index, 1)
  deleteIndex.value = null
  if (!list.length) {
    state.value.other = false
  }
}
</script>

<template>
  <!-- 主行：项目编号 / 项目 / 评价结果 -->
  <tr
    :id="rowId"
    class="item-main"
    :class="{
      'row-unfit': unfit,
      'row-miss': !!problem,
      'row-done': state.result === '符合' || state.result === '无此项',
      'has-reasons': unfit,
    }"
  >
    <td class="item-no">{{ item.no }}</td>
    <td>
      <div class="item-name">
        {{ item.name }}
        <span v-if="item.sub" class="sub">{{ item.sub }}</span>
      </div>
    </td>
    <td>
      <div class="seg">
        <label
          v-for="opt in RESULTS"
          :key="opt"
          :class="{ on: state.result === opt, unfit: opt === '不符合' && unfit }"
          @click.prevent="setResult(opt)"
        >
          <input
            type="radio"
            :name="'seg-' + item.no"
            :value="opt"
            :checked="state.result === opt"
            @change="setResult(opt)"
          />
          <span>{{ opt }}</span>
        </label>
      </div>
    </td>
  </tr>

  <!-- 情形选项单独一行、横跨整张表：
       不再被「评价结果」的窄列约束，左侧编号/项目下方不再留一大块空白。 -->
  <tr v-if="unfit" :id="reasonsId" class="reasons-row">
    <td :colspan="3">
      <div class="reasons">
        <div class="reasons-head">
          不符合情形（清单项与其他二选一）
        </div>
        <label
          v-for="(opt, i) in item.opts"
          :key="i"
          class="chk"
          :class="{ disabled: reasonsLocked }"
          @click.prevent="pickReason(opt)"
        >
          <input
            type="checkbox"
            :checked="(!state.other || state.legacyCombined) && state.reasons.includes(opt)"
            :disabled="reasonsLocked"
            @change="toggleReason(opt, ($event.target as HTMLInputElement).checked)"
          />
          <span>{{ opt }}</span>
        </label>
        <label
          class="chk is-other"
          :class="{ disabled: otherLocked }"
          @click.prevent="toggleOther"
        >
          <input
            type="checkbox"
            :checked="state.other"
            :disabled="otherLocked"
            @change="toggleOther"
          />
          <span class="other-title">
            其他（自行填写）
            <button
              class="other-add"
              type="button"
              title="添加一条其他不符合项"
              aria-label="添加一条其他不符合项"
              @click.stop.prevent="addOther"
            >＋</button>
          </span>
        </label>
        <div v-if="state.other" class="other-box">
          <div v-for="(_text, index) in otherTexts" :key="index" class="other-item">
            <div class="other-input-row">
              <textarea
                v-model="otherTexts[index]"
                class="textarea"
                :disabled="otherLocked"
                :placeholder="`第 ${index + 1} 条其他不符合项`"
              />
              <button
                class="other-delete"
                type="button"
                title="删除这条其他不符合项"
                aria-label="删除这条其他不符合项"
                @click="askDeleteOther(index)"
              >×</button>
            </div>
            <div v-if="deleteIndex === index" class="other-delete-confirm">
              <span>确认删除这条其他不符合项？</span>
              <button class="other-confirm-delete" type="button" @click="confirmDeleteOther(index)">删除</button>
              <button type="button" @click="cancelDeleteOther">取消</button>
            </div>
          </div>
        </div>
        <div v-if="problem" class="reasons-err">{{ problem }}</div>
      </div>
    </td>
  </tr>
</template>

<style scoped>
.reasons-head {
  display: flex;
  align-items: center;
  gap: 6px;
}
.other-title {
  display: inline-flex;
  align-items: center;
  gap: 4px;
}
.other-input-row {
  display: flex;
  align-items: flex-start;
  gap: 6px;
}
.other-input-row .textarea {
  flex: 1 1 auto;
}
.other-delete {
  flex: 0 0 auto;
  width: 26px;
  height: 26px;
  padding: 0;
  border: 1px solid #e3b4b0;
  border-radius: 6px;
  background: #fff5f4;
  color: #b3261e;
  font-size: 18px;
  line-height: 1;
  cursor: pointer;
}
.other-delete:hover {
  border-color: #b3261e;
  background: #fdeceb;
}
.other-delete-confirm {
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 3px 0 2px;
  color: #b3261e;
  font-size: 11.5px;
}
.other-delete-confirm button {
  padding: 2px 8px;
  border: 1px solid #c9d6dd;
  border-radius: 6px;
  background: #f7fafb;
  font-size: 11.5px;
  cursor: pointer;
}
.other-delete-confirm .other-confirm-delete {
  border-color: #b3261e;
  background: #b3261e;
  color: #fff;
}
.other-add {
  margin-left: 4px;
  vertical-align: middle;
  width: 20px;
  height: 20px;
  padding: 0;
  border: 1px solid #c9d6dd;
  border-radius: 6px;
  background: #f7fafb;
  color: #1b5e7a;
  font-size: 14px;
  line-height: 1;
  cursor: pointer;
}
.other-add:hover {
  border-color: #1b5e7a;
  background: #eaf3f6;
}
.other-box {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin-top: 6px;
}

.seg label.on {
  cursor: default;
}

.seg label.unfit {
  color: var(--c-danger);
}

.seg label.on.unfit {
  color: #fff;
}
</style>
