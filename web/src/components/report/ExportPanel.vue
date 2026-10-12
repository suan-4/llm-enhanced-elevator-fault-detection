<script setup lang="ts">
import { ref } from 'vue'
import { exportReport } from '@/api/report'
import { openExport } from '@/api/kiosk'
import { useReportStore } from '@/stores/report'
import { useToast } from '@/utils/toast'

const store = useReportStore()
const { show } = useToast()

const busy = ref(false)
const result = ref<{ filename: string; path: string; size: string } | null>(null)

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

/** 报告正文 HTML：取当前渲染出的纸张节点，避免重复实现一遍模板 */
function papersHtml(): string {
  return Array.from(document.querySelectorAll('.paper'))
    .map((el) => el.outerHTML)
    .join('\n')
}

function metaRows(): string[][] {
  const f = store.form
  return [
    ['委托单位名称', f.clientName],
    ['使用单位名称', f.userName],
    ['设备类别', f.deviceCategory],
    ['产品编号', f.productNo],
  ]
}

async function run(fmt: 'pdf' | 'docx'): Promise<void> {
  busy.value = true
  result.value = null
  try {
    const res = await exportReport({
      fmt,
      title: '在用曳引驱动电梯安全评估报告',
      meta: metaRows(),
      body_html: papersHtml(),
      filename: '电梯安全评估报告',
    })
    result.value = { filename: res.filename, path: res.path, size: formatSize(res.size) }
    show('导出成功，可点击「打开文件」直接查看')
  } catch (err) {
    show(err instanceof Error ? err.message : '导出失败')
  } finally {
    busy.value = false
  }
}

async function open(kind: 'file' | 'dir'): Promise<void> {
  if (!result.value) return
  try {
    await openExport(kind === 'file' ? result.value.path : result.value.path.replace(/[/\\][^/\\]+$/, ''))
  } catch (err) {
    show(err instanceof Error ? err.message : '无法打开')
  }
}
</script>

<template>
  <div class="export-zone">
    <div class="zt">导出报告</div>
    <div class="export-row">
      <button class="btn btn-lg btn-primary" type="button" :disabled="busy" @click="run('pdf')">
        {{ busy ? '导出中…' : '导出 PDF' }}
      </button>
      <button class="btn btn-lg" type="button" :disabled="busy" @click="run('docx')">
        导出 Word
      </button>
    </div>

    <div v-if="result" class="export-result">
      <div>
        <b>导出成功</b>
        <span>　{{ result.filename }}　（{{ result.size }}）</span>
      </div>
      <div class="export-row" style="margin-top: 8px">
        <button class="btn btn-primary" type="button" @click="open('file')">打开文件</button>
        <button class="btn" type="button" @click="open('dir')">打开所在文件夹</button>
        <button class="btn" type="button" @click="result = null">关闭</button>
      </div>
    </div>
  </div>
</template>
