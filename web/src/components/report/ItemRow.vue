<script setup lang="ts">
import { computed } from 'vue'
import { itemProblem } from '@/domain/validation'
import { useReportStore } from '@/stores/report'
import type { JteItem } from '@/types/api'

const props = defineProps<{ item: JteItem }>()
const store = useReportStore()
const state = computed(() => store.stateOf(props.item.no))
const problem = computed(() => itemProblem(state.value))
const unfit = computed(() => state.value.result === '不符合')
const oldReasons = computed(() => state.value.reasons.filter(text => !props.item.opts.includes(text)))

const rowId = computed(() => `row-${props.item.no.replace('.', '-')}`)

const RESULTS = ['符合', '不符合', '无此项'] as const

function setResult(value: (typeof RESULTS)[number]): void {
  state.value.result = value
}

/* 三态/情形都走「点 label 自己改状态」，而不是让浏览器去激活里面的
   <input type=radio|checkbox>：
   1) 输入框聚焦会让板端弹出软键盘（只有要打字时才该弹）；
   2) 隐藏 input 抢焦点还会把整页滚走（见 styles/base.css .seg input 的说明）。
   鼠标/触摸走 label 的 @click.prevent，键盘仍走 input 的 @change，两条路都能用。 */
function toggleReason(text: string, checked: boolean): void {
  const list = state.value.reasons
  const index = list.indexOf(text)
  if (checked && index < 0) list.push(text)
  if (!checked && index >= 0) list.splice(index, 1)
}

/** 点 label 时默认激活已被拦住，所以按「点击前」的状态取反 */
function pickReason(text: string): void {
  toggleReason(text, !state.value.reasons.includes(text))
}
</script>

<template>
  <tr
    :id="rowId"
    :class="{
      'row-unfit': unfit,
      'row-miss': !!problem,
      'row-done': state.result === '符合' || state.result === '无此项',
    }"
  >
    <td class="item-no">{{ item.no }}</td>
    <td>
      <div class="item-name">
        {{ item.name }}
        <span v-if="item.sub" class="sub">{{ item.sub }}</span>
      </div>
    </td>
    <td class="item-req">
      <div v-for="(line, i) in item.req" :key="i">{{ line }}</div>
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
            :name="`seg-${item.no}`"
            :value="opt"
            :checked="state.result === opt"
            @change="setResult(opt)"
          />
          <span>{{ opt }}</span>
        </label>
      </div>

      <div v-if="unfit" class="reasons">
        <div class="reasons-head">不符合情形（可多选）</div>
        <template v-if="oldReasons.length">
          <div class="reasons-err">以下为旧版选项，请取消并重新选择当前风险，或填入其他：</div>
          <label v-for="old in oldReasons" :key="old" class="chk" @click.prevent="pickReason(old)">
            <input type="checkbox" checked @change="toggleReason(old, false)" />
            <span>{{ old }}</span>
          </label>
        </template>
        <label
          v-for="(opt, i) in item.opts"
          :key="i"
          class="chk"
          @click.prevent="pickReason(opt)"
        >
          <input
            type="checkbox"
            :checked="state.reasons.includes(opt)"
            @change="toggleReason(opt, ($event.target as HTMLInputElement).checked)"
          />
          <span>{{ opt }}</span>
        </label>
        <label class="chk is-other" @click.prevent="state.other = !state.other">
          <input v-model="state.other" type="checkbox" />
          <span>其他（自行填写）</span>
        </label>
        <div v-if="state.other" class="other-box">
          <textarea
            v-model="state.otherText"
            class="textarea"
            placeholder="请填写具体情况，将写入报告「存在风险」"
          />
        </div>
        <div v-if="problem" class="reasons-err">{{ problem }}</div>
      </div>
    </td>
  </tr>
</template>

<style scoped>
.other-box {
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
