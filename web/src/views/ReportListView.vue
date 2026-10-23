<script setup lang="ts">
/* 报告管理：查报告、继续编辑、复制为新建、作废、删除。
   行内操作按状态给（设计 §4.7）：草稿只能继续编辑/删除；
   已生成/已归档只能查看、复制、作废；已作废只剩查看与删除。
   组件内嵌在主页面的「报告管理」区域：查看/继续编辑只发事件，
   由父组件在右侧区域内就地切换，不跳转路由。 */
import { onMounted, ref } from 'vue'
import * as api from '@/api/reports'
import AppDialog from '@/components/AppDialog.vue'
import { ApiError } from '@/utils/http'
import { useToast } from '@/utils/toast'

/* 内嵌在主页面的「报告管理」：查看/继续编辑交给父组件就地切换，
   不再跳转路由，也不再自己往 report store 里装历史报告。 */
const emit = defineEmits<{
  view: [report: api.ReportSummary]
  continueEdit: [report: api.ReportSummary]
}>()

const { show } = useToast()

const reports = ref<api.ReportSummary[]>([])
const total = ref(0)
const q = ref('')
const status = ref('')
const mine = ref(false)
const loading = ref(false)
const loadError = ref('')

const STATUS_TEXT: Record<string, string> = {
  draft: '草稿',
  generated: '已生成',
  filed: '已归档',
  void: '已作废',
}
const STATUS_CLASS: Record<string, string> = {
  draft: 'draft',
  generated: 'on',
  filed: 'on',
  void: 'off',
}

function fmt(at: string | null | undefined): string {
  return at ? at.replace('T', ' ').slice(0, 16) : '—'
}

async function load(): Promise<void> {
  loading.value = true
  loadError.value = ''
  try {
    const res = await api.listReports({
      q: q.value.trim(),
      status: status.value,
      mine: mine.value,
    })
    reports.value = res.items
    total.value = res.total
  } catch (err) {
    loadError.value = err instanceof ApiError ? err.detail : '加载失败'
  } finally {
    loading.value = false
  }
}

/* ── 弹层 ───────────────────────────────────────────── */
const dialog = ref<'' | 'void' | 'confirm'>('')
const busy = ref(false)
const dialogError = ref('')
const voidTarget = ref<api.ReportSummary | null>(null)
const voidReason = ref('')
const confirmMessage = ref('')
let confirmAction: (() => Promise<void>) | null = null

function closeDialog(): void {
  if (busy.value) return
  dialog.value = ''
  dialogError.value = ''
}

function openVoid(report: api.ReportSummary): void {
  voidTarget.value = report
  voidReason.value = ''
  dialogError.value = ''
  dialog.value = 'void'
}

function openConfirm(message: string, action: () => Promise<void>): void {
  confirmMessage.value = message
  confirmAction = action
  dialogError.value = ''
  dialog.value = 'confirm'
}

async function submitVoid(): Promise<void> {
  const target = voidTarget.value
  if (!target || busy.value || !voidReason.value.trim()) return
  busy.value = true
  dialogError.value = ''
  try {
    await api.voidReport(target.id, voidReason.value.trim())
    dialog.value = ''
    show('报告已作废（编号保留，不再复用）')
    await load()
  } catch (err) {
    dialogError.value = err instanceof ApiError ? err.detail : '作废失败'
  } finally {
    busy.value = false
  }
}

async function runConfirm(): Promise<void> {
  if (!confirmAction || busy.value) return
  busy.value = true
  dialogError.value = ''
  try {
    await confirmAction()
    dialog.value = ''
    await load()
  } catch (err) {
    dialogError.value = err instanceof ApiError ? err.detail : '操作失败'
  } finally {
    busy.value = false
  }
}

/* ── 行内操作 ───────────────────────────────────────── */
function open(report: api.ReportSummary): void {
  // 草稿：父组件切回录入页继续填写；已生成/归档/作废：父组件就地展开查看
  if (report.status === 'draft') emit('continueEdit', report)
  else emit('view', report)
}

function clone(report: api.ReportSummary): void {
  openConfirm(`按「${report.client_name || '这份报告'}」的抬头新建一份空白评估？评价结果不会带过去。`,
    async () => {
      await api.cloneReport(report.id)
      show('已按抬头新建草稿，返回评估后继续填写')
    })
}

function remove(report: api.ReportSummary): void {
  openConfirm(`确定删除这份${STATUS_TEXT[report.status]}报告？删除后不可恢复。`, async () => {
    await api.deleteReport(report.id)
    show('已删除')
  })
}

const canEdit = (r: api.ReportSummary): boolean => r.status === 'draft'
const canVoid = (r: api.ReportSummary): boolean => r.status === 'generated' || r.status === 'filed'
const canDelete = (r: api.ReportSummary): boolean => r.status === 'draft' || r.status === 'void'

onMounted(load)

/* 被「报告管理/查看」组合组件复用：返回列表前先刷新，旧列表保持可见不闪 */
defineExpose({ reload: load })
</script>

<template>
  <div class="page-pad">
    <div class="sheet">
      <h1 class="doc-title" style="font-size: 18px">报告管理</h1>

      <div class="toolbar">
        <input
          v-model="q"
          class="input"
          type="text"
          placeholder="报告编号 / 使用单位"
          @keyup.enter="load"
        />
        <select v-model="status" class="select" @change="load">
          <option value="">全部状态</option>
          <option value="draft">草稿</option>
          <option value="generated">已生成</option>
          <option value="void">已作废</option>
        </select>
        <label class="chk" style="padding: 0">
          <input v-model="mine" type="checkbox" @change="load" />
          <span>只看我创建的</span>
        </label>
        <button class="btn" type="button" @click="load">查询</button>
      </div>

      <div v-if="loadError" class="err-box">{{ loadError }}</div>
      <div v-else-if="loading && !reports.length" class="empty-state">加载中…</div>
      <div v-else-if="!reports.length" class="empty-state">
        还没有报告。回到评估录入页新建一份吧。
      </div>

      <table v-else class="data-table">
        <thead>
          <tr>
            <th style="width: 190px">报告编号</th>
            <th style="width: 80px">状态</th>
            <th>使用单位</th>
            <th style="width: 120px">产品编号</th>
            <th style="width: 110px">评估日期</th>
            <th style="width: 140px">创建时间</th>
            <th style="width: 260px">操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="r in reports" :key="r.id">
            <td data-label="报告编号">
              <span :class="{ 'void-no': r.status === 'void' }">
                {{ r.report_no || '（未生成）' }}
              </span>
            </td>
            <td data-label="状态">
              <span class="status-tag" :class="STATUS_CLASS[r.status]">
                {{ STATUS_TEXT[r.status] }}
              </span>
            </td>
            <td data-label="使用单位">{{ r.user_name || r.client_name || '—' }}</td>
            <td data-label="产品编号">{{ r.product_no || '—' }}</td>
            <td data-label="评估日期">{{ r.assessed_on || '—' }}</td>
            <td data-label="创建时间">{{ fmt(r.created_at) }}</td>
            <td data-label="操作">
              <div class="actions">
                <button class="btn" type="button" @click="open(r)">
                  {{ canEdit(r) ? '继续编辑' : '查看' }}
                </button>
                <button class="btn" type="button" @click="clone(r)">复制为新建</button>
                <button v-if="canVoid(r)" class="btn" type="button" @click="openVoid(r)">
                  作废
                </button>
                <button v-if="canDelete(r)" class="btn" type="button" @click="remove(r)">
                  删除
                </button>
                <span v-if="r.status === 'void' && r.void_reason" class="hint">
                  作废原因：{{ r.void_reason }}
                </span>
              </div>
            </td>
          </tr>
        </tbody>
      </table>
      <p v-if="reports.length" class="hint" style="margin-top: 8px">
        共 {{ total }} 份。已生成/已归档的报告只能作废，不能直接删除（编号与痕迹要保留）。
      </p>
    </div>

    <AppDialog
      :open="dialog === 'void'"
      title="作废报告"
      confirm-text="确认作废"
      danger
      :busy="busy"
      @close="closeDialog"
      @confirm="submitVoid"
    >
      <div v-if="dialogError" class="err-box">{{ dialogError }}</div>
      <p class="hint">
        作废后编号 <b>{{ voidTarget?.report_no }}</b> 会被保留、不再分配给别人；报告记录仍可查。
      </p>
      <div class="field">
        <label>作废原因（必填）</label>
        <input v-model="voidReason" class="input" placeholder="例如：录入有误，重新出具" />
      </div>
    </AppDialog>

    <AppDialog
      :open="dialog === 'confirm'"
      title="请确认"
      confirm-text="确定"
      danger
      :busy="busy"
      @close="closeDialog"
      @confirm="runConfirm"
    >
      <div v-if="dialogError" class="err-box">{{ dialogError }}</div>
      <p>{{ confirmMessage }}</p>
    </AppDialog>
  </div>
</template>

<style scoped>
.void-no {
  color: var(--c-muted);
  text-decoration: line-through;
}
</style>
