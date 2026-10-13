<script setup lang="ts">
/* 系统设置：基本配置（只读）/ 审计日志 / 备份恢复 / 诊断 / 关于。
   基础版配置仍以部署时 .env 为准，所以这里是只读展示 —— 可写界面放 P1。 */
import { computed, onMounted, ref } from 'vue'
import * as api from '@/api/system'
import AppDialog from '@/components/AppDialog.vue'
import { ApiError } from '@/utils/http'
import { useToast } from '@/utils/toast'

const { show } = useToast()

type Tab = 'config' | 'audit' | 'backup' | 'diagnose' | 'about'
const TABS: { key: Tab; label: string }[] = [
  { key: 'config', label: '基本配置' },
  { key: 'audit', label: '审计日志' },
  { key: 'backup', label: '备份恢复' },
  { key: 'diagnose', label: '诊断' },
  { key: 'about', label: '关于' },
]
const tab = ref<Tab>('config')

const info = ref<api.SystemInfo | null>(null)
const configItems = ref<api.ConfigItem[]>([])

function mb(bytes: number): string {
  if (bytes < 0) return '未知'
  return bytes < 1024 * 1024
    ? `${Math.round(bytes / 1024)} KB`
    : `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

async function loadInfo(): Promise<void> {
  try {
    info.value = await api.systemInfo()
    configItems.value = (await api.systemConfig()).items
  } catch (err) {
    show(err instanceof ApiError ? err.detail : '读取系统信息失败')
  }
}

const auditEvent = ref('')
const auditActor = ref('')
const auditRows = ref<api.AuditEvent[]>([])
const auditTotal = ref(0)
const auditLoading = ref(false)

async function loadAudit(): Promise<void> {
  auditLoading.value = true
  try {
    const res = await api.auditEvents({
      event: auditEvent.value.trim(),
      actor: auditActor.value.trim(),
      size: 50,
    })
    auditRows.value = res.items
    auditTotal.value = res.total
  } catch (err) {
    show(err instanceof ApiError ? err.detail : '读取日志失败')
  } finally {
    auditLoading.value = false
  }
}

const diag = ref<{ overall: string; checks: api.DiagnoseCheck[]; at: string } | null>(null)
const diagBusy = ref(false)
const STATUS_TEXT: Record<string, string> = { ok: '正常', warn: '注意', fail: '异常' }

async function runDiagnose(): Promise<void> {
  diagBusy.value = true
  try {
    const res = await api.diagnose()
    diag.value = { overall: res.overall, checks: res.checks, at: res.at }
  } catch (err) {
    show(err instanceof ApiError ? err.detail : '诊断失败')
  } finally {
    diagBusy.value = false
  }
}

const backups = ref<api.BackupEntry[]>([])
const backupBusy = ref(false)
const targetDir = ref('')
const restoreTarget = ref<api.BackupEntry | null>(null)
const dialog = ref<'' | 'restore'>('')
const dialogError = ref('')

async function loadBackups(): Promise<void> {
  try {
    backups.value = (await api.listBackups()).items
  } catch {
    backups.value = []
  }
}

async function doBackup(): Promise<void> {
  if (backupBusy.value) return
  backupBusy.value = true
  try {
    const res = await api.runBackup(targetDir.value.trim() || undefined)
    show(`备份完成：${res.files} 个文件，${mb(res.size)}`)
    await loadBackups()
  } catch (err) {
    show(err instanceof ApiError ? err.detail : '备份失败')
  } finally {
    backupBusy.value = false
  }
}

function askRestore(entry: api.BackupEntry): void {
  restoreTarget.value = entry
  dialogError.value = ''
  dialog.value = 'restore'
}

async function doRestore(): Promise<void> {
  if (!restoreTarget.value) return
  backupBusy.value = true
  dialogError.value = ''
  try {
    await api.runRestore(restoreTarget.value.dir)
    dialog.value = ''
    show('已恢复，请重启服务后生效')
  } catch (err) {
    dialogError.value = err instanceof ApiError ? err.detail : '恢复失败'
  } finally {
    backupBusy.value = false
  }
}

const overallText = computed(() => (diag.value ? STATUS_TEXT[diag.value.overall] : ''))

onMounted(async () => {
  await Promise.all([loadInfo(), loadAudit(), loadBackups()])
})
</script>

<template>
  <div class="page-pad">
    <div class="sheet">
      <h1 class="doc-title" style="font-size: 18px">系统设置</h1>

      <div class="tabs">
        <button
          v-for="t in TABS"
          :key="t.key"
          class="tab"
          :class="{ on: tab === t.key }"
          type="button"
          @click="tab = t.key"
        >
          {{ t.label }}
        </button>
      </div>

      <template v-if="tab === 'config'">
        <table class="data-table">
          <thead>
            <tr>
              <th style="width: 140px">项目</th>
              <th style="width: 220px">当前值</th>
              <th>说明</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="c in configItems" :key="c.key">
              <td data-label="项目">{{ c.key }}</td>
              <td data-label="当前值">{{ c.value }}</td>
              <td data-label="说明">{{ c.desc }}</td>
            </tr>
          </tbody>
        </table>
        <p class="hint" style="margin-top: 8px">
          基础版配置以部署时的 .env 为准，这里是只读展示；可改配置的界面放下一期。
        </p>
      </template>

      <template v-else-if="tab === 'audit'">
        <div class="toolbar">
          <input v-model="auditEvent" class="input" placeholder="事件类型，如 login_ok" @keyup.enter="loadAudit" />
          <input v-model="auditActor" class="input" placeholder="操作者姓名或 ID" @keyup.enter="loadAudit" />
          <button class="btn" type="button" @click="loadAudit">查询</button>
        </div>
        <div v-if="auditLoading" class="empty-state">加载中…</div>
        <div v-else-if="!auditRows.length" class="empty-state">没有符合条件的日志。</div>
        <table v-else class="data-table">
          <thead>
            <tr>
              <th style="width: 150px">时间</th>
              <th style="width: 150px">事件</th>
              <th style="width: 110px">操作者</th>
              <th>对象</th>
              <th>备注</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="e in auditRows" :key="e.id">
              <td data-label="时间">{{ e.at.replace('T', ' ') }}</td>
              <td data-label="事件">{{ e.event }}</td>
              <td data-label="操作者">{{ e.actor_name || '—' }}</td>
              <td data-label="对象">{{ e.target || '—' }}</td>
              <td data-label="备注">{{ e.note || '—' }}</td>
            </tr>
          </tbody>
        </table>
        <p v-if="auditRows.length" class="hint" style="margin-top: 8px">
          共 {{ auditTotal }} 条（最新在前）。日志只追加，界面不提供删除。
        </p>
      </template>

      <template v-else-if="tab === 'backup'">
        <div class="toolbar">
          <input v-model="targetDir" class="input" placeholder="备份到（留空用配置目录）" />
          <button class="btn btn-primary" type="button" :disabled="backupBusy" @click="doBackup">
            {{ backupBusy ? '处理中…' : '立即备份' }}
          </button>
          <button class="btn" type="button" @click="loadBackups">刷新列表</button>
        </div>
        <div v-if="!backups.length" class="empty-state">
          还没有备份。备份会打包业务库与导出文件，并逐文件记录 SHA-256。
        </div>
        <table v-else class="data-table">
          <thead>
            <tr>
              <th style="width: 170px">备份时间</th>
              <th style="width: 100px">文件数</th>
              <th style="width: 110px">大小</th>
              <th>目录</th>
              <th style="width: 120px">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="b in backups" :key="b.dir">
              <td data-label="备份时间">{{ (b.created_at || b.name).replace('T', ' ') }}</td>
              <td data-label="文件数">{{ b.files }}</td>
              <td data-label="大小">{{ mb(b.size) }}</td>
              <td data-label="目录">{{ b.dir }}</td>
              <td data-label="操作">
                <div class="actions">
                  <button class="btn" type="button" @click="askRestore(b)">恢复</button>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
        <p class="hint" style="margin-top: 8px">
          恢复前会自动把当前状态另存一份；恢复完成后需要重启服务才生效。
        </p>
      </template>

      <template v-else-if="tab === 'diagnose'">
        <div class="toolbar">
          <button class="btn btn-primary" type="button" :disabled="diagBusy" @click="runDiagnose">
            {{ diagBusy ? '检查中…' : '运行诊断' }}
          </button>
          <span v-if="diag" class="hint">整体：{{ overallText }}（{{ diag.at.replace('T', ' ') }}）</span>
        </div>
        <div v-if="!diag" class="empty-state">点「运行诊断」逐项检查依赖与服务。</div>
        <table v-else class="data-table">
          <thead>
            <tr>
              <th style="width: 130px">检查项</th>
              <th style="width: 90px">结果</th>
              <th>说明</th>
              <th>建议</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="c in diag.checks" :key="c.name">
              <td data-label="检查项">{{ c.name }}</td>
              <td data-label="结果">
                <span class="status-tag" :class="c.status === 'ok' ? 'on' : 'off'">
                  {{ STATUS_TEXT[c.status] }}
                </span>
              </td>
              <td data-label="说明">{{ c.detail }}</td>
              <td data-label="建议">{{ c.advice || '—' }}</td>
            </tr>
          </tbody>
        </table>
      </template>

      <template v-else>
        <table v-if="info" class="data-table">
          <tbody>
            <tr><td data-label="系统版本">{{ info.version }}</td></tr>
            <tr><td data-label="大模型">{{ info.model }}</td></tr>
            <tr>
              <td data-label="评价条目库">
                {{ info.catalog.version }}　共 {{ info.catalog.count }} 条　哈希 {{ info.catalog.hash }}
              </td>
            </tr>
            <tr><td data-label="业务库">{{ info.db.path }}（{{ mb(info.db.size) }}）</td></tr>
            <tr><td data-label="导出目录">{{ info.export_dir }}</td></tr>
            <tr><td data-label="备份目录">{{ info.backup_dir }}</td></tr>
            <tr><td data-label="磁盘剩余">{{ mb(info.disk_free) }}</td></tr>
            <tr><td data-label="工作节点号">{{ info.worker_id }}（雪花 ID 机器位）</td></tr>
            <tr><td data-label="时钟回拨">{{ info.clock_rollbacks }} 次</td></tr>
          </tbody>
        </table>
        <p class="hint" style="margin-top: 8px">
          依据 GB/T 42615-2023《在用电梯安全评估规范》，报告模板 JTE-09-R02-3.00。
        </p>
      </template>
    </div>

    <AppDialog
      :open="dialog === 'restore'"
      title="恢复备份"
      confirm-text="确认恢复"
      danger
      :busy="backupBusy"
      @close="dialog = ''"
      @confirm="doRestore"
    >
      <div v-if="dialogError" class="err-box">{{ dialogError }}</div>
      <p>
        将用 <b>{{ restoreTarget?.name }}</b> 覆盖当前业务库。恢复前会自动备份现状，
        完成后需要重启服务。
      </p>
    </AppDialog>
  </div>
</template>

<style scoped>
.tabs {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
  margin-bottom: 12px;
  border-bottom: 1px solid var(--c-line);
  padding-bottom: 8px;
}

.tab {
  font: inherit;
  font-size: 13px;
  padding: 6px 14px;
  border: 1px solid var(--c-line);
  border-radius: var(--radius-sm);
  background: #fff;
  color: var(--c-secondary);
  cursor: pointer;
}

.tab.on {
  background: var(--c-primary);
  border-color: var(--c-primary);
  color: #fff;
}
</style>
