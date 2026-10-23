/* 导出逻辑集中在这里：底部操作条上的「导出 PDF / 导出 Word」按钮
   与结果卡片共用同一份状态，避免按钮和提示分处两地。 */
import { nextTick, ref } from 'vue'
import { afterPaint, beginInteraction } from './performance'
import { openExport } from '@/api/kiosk'
import { exportReport } from '@/api/report'
import { getReport } from '@/api/reports'
import { useReportStore } from '@/stores/report'
import { useToast } from './toast'
import { ApiError } from './http'

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

  async function run(fmt: 'pdf' | 'docx'): Promise<void> {
    if (busy.value) return
    if (store.generated?.assessment_issues.length) {
      show('评定尚有待确认内容，请先核对预览中的具体问题')
      return
    }
    busy.value = true
    result.value = null
    const timing = beginInteraction(`export_${fmt}`)
    let requested: { id: string; version: number; digest: string } | null = null
    try {
      await store.flush()
      const reportId = store.reportId
      const version = store.version
      const snapshot = store.generated
      if (!reportId || !snapshot?.result_digest || !['generated', 'filed'].includes(store.status)) {
        throw new Error('请先生成有效报告，或重新打开报告预览后导出')
      }
      requested = { id: reportId, version, digest: snapshot.result_digest }
      const res = await timing.measure('export_http', () => exportReport({
        fmt,
        report_id: reportId,
        version,
        result_digest: snapshot.result_digest,
      }))
      store.markExportUncertain(reportId, false)
      if (store.reportId === reportId && store.version === version
          && store.generated?.result_digest === snapshot.result_digest) {
        store.status = res.status
        store.markExportUncertain(reportId, false)
      }
      result.value = { filename: res.filename, path: res.path, size: formatSize(res.size) }
      show('导出成功，可点击「打开文件」直接查看')
      await timing.measure('render', async () => { await nextTick(); await afterPaint() })
      timing.finish('ok')
    } catch (err) {
      if (requested) {
        store.markExportUncertain(requested.id, !(err instanceof ApiError && err.status > 0))
      }
      if (requested && store.reportId === requested.id && store.version === requested.version
          && store.generated?.result_digest === requested.digest) {
        store.markExportUncertain(requested.id, true)
        try {
          const current = (await getReport(requested.id)).report
          if (store.reportId === requested.id && store.version === requested.version
              && store.generated?.result_digest === requested.digest) {
            store.status = current.status
            // A lost HTTP connection does not cancel the conversion thread.
            // A still-generated record cannot prove that export has finished.
            const responseFinished = err instanceof ApiError && err.status > 0
            store.markExportUncertain(requested.id, current.status === 'generated' && !responseFinished)
            const matches = current.files?.filter(file =>
              file.fmt === fmt && file.version === requested!.version
              && file.result_digest === requested!.digest) ?? []
            const saved = matches[matches.length - 1]
            if (current.status === 'filed' && saved) {
              result.value = { filename: saved.filename, path: saved.path, size: formatSize(saved.size) }
              show('已核实报告导出成功并归档')
              timing.finish('ok')
              return
            }
          }
        } catch {
          show('连接中断，尚不能确认导出结果；恢复连接后请重试导出或重新打开报告')
          timing.finish('error')
          return
        }
      }
      timing.finish('error')
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
