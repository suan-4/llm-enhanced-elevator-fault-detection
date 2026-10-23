<script setup lang="ts">
/* 主页面第三个区域：报告管理 + 报告查看的组合子组件。
   点「查看」不跳路由，只在右侧区域把列表替换成查看页；查看页返回按钮回到列表。
   生成报告后由父组件调用 showReport(id) 自动进入查看。 */
import { ref } from 'vue'
import ReportListView from '@/views/ReportListView.vue'
import ReportInlineViewer from '@/components/report/ReportInlineViewer.vue'
import { useReportStore } from '@/stores/report'
import { useToast } from '@/utils/toast'
import type * as api from '@/api/reports'

const emit = defineEmits<{ continueEdit: [id: string] }>()
const store = useReportStore()
const { show } = useToast()

const mode = ref<'list' | 'view'>('list')
const reportId = ref('')
const listRef = ref<InstanceType<typeof ReportListView> | null>(null)

/** 列表/查看切换时回到内容顶部，避免沿用上一屏的滚动位置（看起来像闪一下） */
function scrollMainTop(): void {
  const main = document.querySelector('.main') as HTMLElement | null
  main?.scrollTo({ top: 0 })
}

async function showList(): Promise<void> {
  // 列表一直挂载（v-show）：先刷数据再切回来，避免"加载中"闪一下
  await listRef.value?.reload()
  mode.value = 'list'
  await scrollMainTop()
}

/** 先把报告装进 store，装好再切视图：列表不会先变空白再出现报告 */
async function showReport(reportOrId: api.ReportSummary | string): Promise<void> {
  const id = typeof reportOrId === 'string' ? reportOrId : reportOrId.id
  if (store.reportId !== id) {
    try {
      await store.openReport(id)
    } catch (err) {
      show(err instanceof Error ? err.message : '报告加载失败')
      return
    }
  }
  reportId.value = id
  mode.value = 'view'
  await scrollMainTop()
}

function onContinueEdit(report: api.ReportSummary): void {
  emit('continueEdit', report.id)
}

/** 主页面切进「报告管理」时调用：之前停在查看页就继续看那一份报告，
    停在列表就刷新列表；准备好之后再让父组件显示区域，避免切换闪烁。 */
async function prepareEnter(): Promise<void> {
  if (mode.value === 'view' && reportId.value) {
    await showReport(reportId.value)
  } else {
    await showList()
  }
}

defineExpose({ showList, showReport, prepareEnter })
</script>

<template>
  <div class="report-center">
    <ReportListView
      v-show="mode === 'list'"
      ref="listRef"
      @view="showReport"
      @continue-edit="onContinueEdit"
    />
    <ReportInlineViewer
      v-if="mode === 'view'"
      :key="reportId"
      :report-id="reportId"
      @back="showList"
    />
  </div>
</template>

<style scoped>
.report-center {
  min-height: 100%;
}
</style>
