/* 导出逻辑集中在这里：底部操作条上的「导出 PDF / 导出 Word」按钮
   与结果卡片共用同一份状态，避免按钮和提示分处两地。 */
import { ref } from 'vue'
import { openExport } from '@/api/kiosk'
import { exportReport } from '@/api/report'
import { useReportStore } from '@/stores/report'
import { useToast } from './toast'

export interface ExportResult {
  filename: string
  path: string
  size: string
}

const busy = ref(false)
const result = ref<ExportResult | null>(null)

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

export function useExport() {
  const store = useReportStore()
  const { show } = useToast()

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
    if (busy.value) return
    busy.value = true
    result.value = null
    try {
      const res = await exportReport({
        fmt,
        title: '在用曳引驱动电梯安全评估报告',
        meta: metaRows(),
        body_html: papersHtml(),
        // 有编号就用编号命名（现场对号入座），否则退回通用名
        filename: store.generated?.report_no
          ? `${store.generated.report_no}_${store.form.clientName || '电梯安全评估报告'}`
          : '电梯安全评估报告',
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
    const target =
      kind === 'file' ? result.value.path : result.value.path.replace(/[/\\][^/\\]+$/, '')
    try {
      await openExport(target)
    } catch (err) {
      show(err instanceof Error ? err.message : '无法打开')
    }
  }

  function dismiss(): void {
    result.value = null
  }

  return { busy, result, run, open, dismiss }
}
