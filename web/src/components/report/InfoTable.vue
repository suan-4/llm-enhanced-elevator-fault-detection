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

interface InfoRow {
  label: string
  key: string
  /** 独占整行时给出 colspan */
  span?: number
  /** 同一行右侧的第二个字段 */
  second?: { label: string; key: string }
  /** 仅在报告预览中出现，值来自计算结果而非用户输入 */
  computed?: 'overview' | 'conclusion'
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
  { label: '额定载重量', key: 'ratedLoad', second: { label: '额定速度', key: 'ratedSpeed' } },
  { label: '层站门数', key: 'floorsStopsDoors', second: { label: '控制方式', key: 'controlMode' } },
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

        <template v-if="row.span">
          <td :colspan="row.span">
            <input
              v-if="!readonly"
              :id="`f-${row.key}`"
              v-model="form[row.key]"
              class="input input-plain"
              type="text"
            />
            <span v-else>{{ rowText(row) }}</span>
          </td>
        </template>

        <template v-else-if="row.second">
          <td>
            <input
              v-if="!readonly"
              :id="`f-${row.key}`"
              v-model="form[row.key]"
              class="input input-plain"
              type="text"
            />
            <span v-else>{{ form[row.key] }}</span>
          </td>
          <th>{{ row.second.label }}</th>
          <td>
            <input
              v-if="!readonly"
              :id="`f-${row.second.key}`"
              v-model="form[row.second.key]"
              class="input input-plain"
              type="text"
            />
            <span v-else>{{ form[row.second.key] }}</span>
          </td>
        </template>
      </tr>
    </tbody>
  </table>
</template>
