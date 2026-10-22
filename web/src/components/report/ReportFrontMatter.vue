<script setup lang="ts">
import source from '../../../../backend/app/data/jte_frontmatter.json'
import { useReportStore } from '@/stores/report'
const store = useReportStore()
const fields = [
  { label: '委托单位名称', key: 'clientName' },
  { label: '使用单位名称', key: 'userName' },
  { label: '设备品种', key: 'deviceVariety' },
  { label: '产品编号', key: 'productNo' },
  { label: '评估日期', key: 'assessDate' },
]
</script>
<template>
  <div class="paper-holder">
    <div class="paper report-cover">
      <div class="document-number">报告编号：{{ store.generated?.report_no || '/' }}</div>
      <b class="quality-code">质量体系文件编号：{{ source.document_code }}</b>
      <img
        :src="source.logo"
        alt="广东省特种设备检测研究院 GDSEI"
        class="cover-logo"
        @load="$emit('layout')"
      />
      <h1>{{ source.title }}</h1>
      <dl class="cover-fields">
        <div v-for="field in fields" :key="field.key">
          <dt>{{ field.label }}</dt>
          <dd>：{{ store.form[field.key] || '/' }}</dd>
        </div>
      </dl>
      <div class="cover-institution">{{ source.institution }}</div>
    </div>
  </div>
  <div class="paper-holder">
    <div class="paper report-notice">
      <div class="document-number">报告编号：{{ store.generated?.report_no || '/' }}</div>
      <h1>注 意 事 项</h1>
      <ol>
        <li v-for="line in source.notice" :key="line">{{ line }}</li>
      </ol>
      <div class="institution-contact">评估机构地址：<br />邮政编码：<br />联系电话：</div>
    </div>
  </div>
</template>
<style scoped>
.report-cover,
.report-notice {
  position: relative;
  min-height: var(--paper-height);
}
.document-number {
  text-align: right;
  font-size: 9pt;
  margin: -8mm 0 3mm;
}
.quality-code {
  display: block;
  font-size: 10.5pt;
}
.cover-logo {
  display: block;
  width: 36mm;
  height: auto;
  margin: 12mm 0 16mm 7mm;
}
.report-cover h1 {
  font-family: var(--font-report);
  font-size: 22pt;
  font-weight: 400;
  white-space: nowrap;
  margin-bottom: 35mm;
}
.cover-fields {
  margin: 0 5mm;
  font-size: 15pt;
}
.cover-fields > div {
  display: flex;
  align-items: baseline;
  min-height: 12mm;
}
.cover-fields dt {
  width: 51mm;
  text-align-last: justify;
  flex-shrink: 0;
}
.cover-fields dd {
  flex: 1;
  margin-left: 2mm;
  border-bottom: 1px solid #000;
  overflow-wrap: anywhere;
}
.cover-institution {
  position: absolute;
  bottom: 18mm;
  left: 16mm;
  right: 16mm;
  text-align: center;
  font-size: 20pt;
}
.report-notice h1 {
  font-family: var(--font-report);
  font-size: 22pt;
  font-weight: 400;
  margin: 2mm 0 16mm;
}
.report-notice ol {
  margin: 0;
  padding-left: 8mm;
  line-height: 2;
  font-size: 12pt;
}
.report-notice li {
  padding-left: 1mm;
  margin-bottom: 1mm;
}
.institution-contact {
  margin-top: 28mm;
  line-height: 2;
  font-size: 12pt;
}
</style>
