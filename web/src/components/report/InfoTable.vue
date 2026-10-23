<script setup lang="ts">
/* 抬头信息表：录入时渲染输入框，报告预览时渲染纯文本。
   行结构按 JTE 模板的信息表排列，四项必填带 id，供漏填定位使用。 */
import { useReportStore } from '@/stores/report'

const props = withDefaults(
  defineProps<{ readonly?: boolean; overview?: string; conclusion?: string }>(),
  { readonly: false, overview: '', conclusion: '' },
)

const store = useReportStore()
const form = store.form

/** 层/站/门三个数字框：单位字是固定标签（不可删除），值只收数字 */
const FLOOR_PARTS = [
  { key: 'floors', label: '层' },
  { key: 'stops', label: '站' },
  { key: 'doors', label: '门' },
] as const

/* 不用 v-model：Vue 会给 type=number 的 v-model 自动转成 number，
   而 form 的契约是 Record<string, string>。这里手动收数字，保持类型稳定。 */
function onFloorInput(key: 'floors' | 'stops' | 'doors', event: Event): void {
  const el = event.target as HTMLInputElement
  const cleaned = el.value.replace(/[^\d]/g, '').slice(0, 4)
  form[key] = cleaned
  if (el.value !== cleaned) el.value = cleaned
}

/** 额定载重/额定速度：收数字（速度允许小数），单位固定、不参与输入 */
function onUnitInput(key: string, allowDecimal: boolean, event: Event): void {
  const el = event.target as HTMLInputElement
  const pattern = allowDecimal ? /[^\d.]/g : /[^\d]/g
  let cleaned = el.value.replace(pattern, '')
  if (allowDecimal) cleaned = (cleaned.match(/^\d*\.?\d*/) ?? [''])[0]
  cleaned = cleaned.slice(0, allowDecimal ? 6 : 5)
  form[key] = cleaned
  if (el.value !== cleaned) el.value = cleaned
}

/** 报告预览用：按模板写法拼回「X 层　X 站　X 门」，未填的位按「/」占位 */
function floorsText(): string {
  return FLOOR_PARTS.map((part) => `${String(form[part.key] ?? '').trim() || '/'} ${part.label}`).join('　')
}

/** 单值 + 固定单位（额定载重量/额定速度）；未填时按模板习惯显示「/ kg」 */
function unitText(key: string, unit: string): string {
  return `${String(form[key] ?? '').trim() || '/'} ${unit}`
}

interface UnitField {
  label: string
  key: string
  /** 固定单位字（kg / m/s），不是输入内容 */
  unit?: string
}

interface InfoRow extends UnitField {
  /** 独占整行时给出 colspan */
  span?: number
  /** 同一行右侧的第二个字段 */
  second?: UnitField
  /** 仅在报告预览中出现，值来自计算结果而非用户输入 */
  computed?: 'overview' | 'conclusion'
  /** 非普通单输入框的自定义单元格 */
  custom?: 'floors'
}

const ROWS: InfoRow[] = [
  { label: '委托单位名称', key: 'clientName', span: 3 },
  { label: '使用单位名称', key: 'userName', span: 3 },
  { label: '安装地点', key: 'installSite', span: 3 },
  { label: '设备类别', key: 'deviceCategory', second: { label: '设备品种', key: 'deviceVariety' } },
  { label: '型号', key: 'model', second: { label: '产品编号', key: 'productNo' } },
  { label: '使用登记证编号', key: 'registerNo', second: { label: '制造日期', key: 'manufactureDate' } },
  { label: '制造单位名称', key: 'manufacturer', span: 3 },
  { label: '改造单位名称', key: 'retrofitUnit', second: { label: '改造日期', key: 'retrofitDate' } },
  { label: '维护保养单位名称', key: 'maintainUnit', span: 3 },
  { label: '额定载重量', key: 'ratedLoad', unit: 'kg', second: { label: '额定速度', key: 'ratedSpeed', unit: 'm/s' } },
  { label: '层站门数', key: 'floorsStopsDoors', custom: 'floors', second: { label: '控制方式', key: 'controlMode' } },
  { label: '评估仪器', key: 'instruments', span: 3 },
  { label: '评估依据', key: 'basis', span: 3 },
  { label: '评估概况', key: '__overview', span: 3, computed: 'overview' },
  { label: '评估结论', key: '__conclusion', span: 3, computed: 'conclusion' },
  { label: '整机建议', key: 'suggestion', span: 3 },
  { label: '备注', key: 'remark', span: 3 },
  { label: '评估日期', key: 'assessDate', span: 3 },
]

function rowText(row: InfoRow): string {
  if (row.computed === 'overview') return props.overview
  if (row.computed === 'conclusion') return props.conclusion
  return form[row.key]
}

function rowVisible(row: InfoRow): boolean {
  return row.computed ? props.readonly : true
}
</script>

<template>
  <table class="info">
    <tbody>
      <tr v-for="row in ROWS" v-show="rowVisible(row)" :key="row.key">
        <th>{{ row.label }}</th>

        <td :colspan="row.span">
          <template v-if="row.custom === 'floors'">
            <div v-if="!readonly" class="floors">
              <label v-for="part in FLOOR_PARTS" :key="part.key" class="floor-part">
                <input
                  :id="`f-${part.key}`"
                  :value="form[part.key]"
                  class="input input-plain floor-input"
                  type="number"
                  min="0"
                  inputmode="numeric"
                  placeholder="/"
                  @input="onFloorInput(part.key, $event)"
                />
                <span class="floor-unit">{{ part.label }}</span>
              </label>
            </div>
            <span v-else>{{ floorsText() }}</span>
          </template>
          <template v-else-if="row.unit">
            <div v-if="!readonly" class="unit-field">
              <input
                :id="`f-${row.key}`"
                :value="form[row.key]"
                class="input input-plain unit-input"
                type="number"
                min="0"
                inputmode="decimal"
                placeholder="/"
                @input="onUnitInput(row.key, row.unit === 'm/s', $event)"
              />
              <span class="unit-label">{{ row.unit }}</span>
            </div>
            <span v-else>{{ unitText(row.key, row.unit) }}</span>
          </template>
          <template v-else-if="!readonly">
            <input
              :id="`f-${row.key}`"
              v-model="form[row.key]"
              class="input input-plain"
              type="text"
            />
          </template>
          <span v-else>{{ rowText(row) }}</span>
        </td>

        <template v-if="row.second">
          <th>{{ row.second.label }}</th>
          <td>
            <template v-if="row.second.unit">
              <div v-if="!readonly" class="unit-field">
                <input
                  :id="`f-${row.second.key}`"
                  :value="form[row.second.key]"
                  class="input input-plain unit-input"
                  type="number"
                  min="0"
                  inputmode="decimal"
                  placeholder="/"
                  @input="onUnitInput(row.second.key, row.second.unit === 'm/s', $event)"
                />
                <span class="unit-label">{{ row.second.unit }}</span>
              </div>
              <span v-else>{{ unitText(row.second.key, row.second.unit) }}</span>
            </template>
            <template v-else-if="!readonly">
              <input
                :id="`f-${row.second.key}`"
                v-model="form[row.second.key]"
                class="input input-plain"
                type="text"
              />
            </template>
            <span v-else>{{ form[row.second.key] }}</span>
          </td>
        </template>
      </tr>
    </tbody>
  </table>
</template>
