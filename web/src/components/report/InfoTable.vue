<script setup lang="ts">
import InfoField from './InfoField.vue'
import { REQUIRED_FIELDS } from '@/domain/validation'
withDefaults(defineProps<{ readonly?: boolean; overview?: string; conclusion?: string }>(), {
  readonly: false,
  overview: '',
  conclusion: '',
})
const required = (key: string) => REQUIRED_FIELDS.some((f) => f.key === key)
const rows = [
  [{ label: '委托单位名称', key: 'clientName' }],
  [{ label: '使用单位名称', key: 'userName' }],
  [{ label: '安装地点', key: 'installSite' }],
  [
    { label: '设备类别', key: 'deviceCategory' },
    { label: '设备品种', key: 'deviceVariety' },
  ],
  [
    { label: '型号', key: 'model' },
    { label: '产品编号', key: 'productNo' },
  ],
  [
    { label: '使用登记证编号', key: 'registerNo' },
    { label: '制造日期', key: 'manufactureDate' },
  ],
  [{ label: '制造单位名称', key: 'manufacturer' }],
  [
    { label: '改造单位名称', key: 'retrofitUnit' },
    { label: '改造日期', key: 'retrofitDate' },
  ],
  [{ label: '维护保养单位名称', key: 'maintainUnit' }],
]
const technical = [
  [
    { label: '额定载重量', key: 'ratedLoad' },
    { label: '额定速度', key: 'ratedSpeed' },
  ],
  [
    { label: '层站门数', key: 'floorsStopsDoors' },
    { label: '控制方式', key: 'controlMode' },
  ],
]
const trailing = [
  { label: '整机建议', key: 'suggestion' },
  { label: '备注', key: 'remark' },
  { label: '评估日期', key: 'assessDate' },
]
</script>

<template>
  <table class="info" :class="{ 'info-entry': !readonly }" aria-label="电梯评估信息表">
    <colgroup>
      <col style="width: 12%" />
      <col style="width: 12%" />
      <col style="width: 30%" />
      <col style="width: 16%" />
      <col style="width: 15%" />
      <col style="width: 15%" />
    </colgroup>
    <tbody>
      <tr v-for="row in rows" :key="row[0].key">
        <template v-for="(field, i) in row" :key="field.key">
          <th :colspan="i === 0 ? 2 : 1" scope="row">
            {{ field.label
            }}<span v-if="!readonly && required(field.key)" class="req" aria-hidden="true"> *</span>
          </th>
          <td :colspan="row.length === 1 ? 4 : i === 0 ? 1 : 2">
            <InfoField :field="field.key" :label="field.label" :readonly="readonly" />
          </td>
        </template>
      </tr>
      <tr v-for="(row, index) in technical" :key="row[0].key">
        <th v-if="index === 0" rowspan="2" class="technical-group" scope="rowgroup">
          设备<br />技术<br />参数
        </th>
        <template v-for="(field, i) in row" :key="field.key">
          <th scope="row">{{ field.label }}</th>
          <td :colspan="i === 0 ? 1 : 2">
            <InfoField :field="field.key" :label="field.label" :readonly="readonly" />
          </td>
        </template>
      </tr>
      <tr
        v-for="field in [
          { label: '评估仪器', key: 'instruments' },
          { label: '评估依据', key: 'basis' },
        ]"
        :key="field.key"
      >
        <th scope="row">{{ field.label }}</th>
        <td colspan="5">
          <InfoField :field="field.key" :label="field.label" :readonly="readonly" />
        </td>
      </tr>
      <tr>
        <th scope="row">评估概况</th>
        <td colspan="5" class="computed-field">
          {{ overview || (readonly ? '/' : '生成报告后自动填写') }}
        </td>
      </tr>
      <tr>
        <th scope="row">评估结论</th>
        <td colspan="5" class="computed-field">
          {{ conclusion || (readonly ? '/' : '生成报告后自动填写') }}
        </td>
      </tr>
      <tr v-for="field in trailing" :key="field.key">
        <th scope="row">{{ field.label }}</th>
        <td colspan="5">
          <InfoField :field="field.key" :label="field.label" :readonly="readonly" />
        </td>
      </tr>
      <tr v-for="(label, index) in ['评估', '审核', '批准']" :key="label" class="signature-row">
        <td colspan="4">{{ label }}：<span class="signature-space" />日期：　年　月　日</td>
        <td v-if="index === 0" colspan="2" rowspan="3" class="signature-seal">
          检验机构核准证号：<br />TS7Ⅰ10007-2029<br />（检验机构检验专用章）
        </td>
      </tr>
    </tbody>
  </table>
</template>

<style scoped>
.info {
  table-layout: fixed;
}
.info th {
  width: auto;
  white-space: normal;
  overflow-wrap: anywhere;
}
.technical-group,
.signature-seal {
  text-align: center;
}
.signature-row td {
  vertical-align: middle;
}
.signature-space {
  display: inline-block;
  width: 20%;
}
.computed-field {
  color: var(--c-secondary);
}
.info-entry :deep(.input) {
  min-width: 0;
  height: 24px;
  padding: 0 3px;
  font-size: 12px;
  line-height: 18px;
}
/* Entry stays a template table on the terminal; generic phone stacking is not appropriate here. */
.info-entry {
  display: table;
  width: 100%;
}
.info-entry tbody {
  display: table-row-group;
}
.info-entry tr {
  display: table-row;
}
.info-entry th,
.info-entry td {
  display: table-cell;
  width: auto;
  padding: 2px 4px;
  border: 1px solid var(--c-line);
  font-size: 12px;
  line-height: 16px;
  white-space: normal;
}
.info-entry .signature-seal {
  font-size: 10px;
  line-height: 16px;
}
.info-entry .signature-row td {
  height: 28px;
}
.info-entry :deep(.floor-unit),
.info-entry :deep(.unit-label) {
  font-size: 11px;
}
.info-entry :deep(.floors) {
  flex-wrap: nowrap;
  gap: 2px;
}
.info-entry :deep(.floor-part) {
  flex: 1;
  min-width: 0;
  gap: 1px;
}
.info-entry :deep(.floor-input) {
  flex: 1;
  width: 0;
  padding: 0;
}
@media (max-width: 900px) {
  .info-entry th {
    white-space: normal;
  }
  .info-entry .signature-row:last-child td {
    border-bottom: 1px solid var(--c-line);
  }
}
</style>
