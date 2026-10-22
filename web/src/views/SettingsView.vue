<script setup lang="ts">
/* 系统设置（2026-10 调整）：
   - 报告管理 / 账号管理从侧栏并入本页，统一由左侧树状导航进入；
   - 右侧按树节点渲染内容，配置类仍是只读展示（基础版以部署 .env 为准）。 */
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import * as api from '@/api/system'
import AppDialog from '@/components/AppDialog.vue'
import AccountListView from '@/views/AccountListView.vue'
import ReportListView from '@/views/ReportListView.vue'
import { useAuthStore } from '@/stores/auth'
import { useShell } from '@/stores/shell'
import { ApiError } from '@/utils/http'
import { useToast } from '@/utils/toast'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const shell = useShell()
const { show } = useToast()

type Section = 'reports' | 'accounts' | 'config' | 'audit' | 'backup' | 'diagnose' | 'about'

interface TreeGroup {
  key: string
  label: string
  children: { key: Section; label: string }[]
}

/* 左侧树：业务管理（报告/账号）+ 系统维护（配置/日志/备份/诊断）+ 关于 */
const TREE: TreeGroup[] = [
  {
    key: 'biz',
    label: '业务管理',
    children: [
      { key: 'reports', label: '报告管理' },
      { key: 'accounts', label: '账号管理' },
    ],
  },
  {
    key: 'ops',
    label: '系统维护',
    children: [
      { key: 'config', label: '基本配置' },
      { key: 'audit', label: '审计日志' },
      { key: 'backup', label: '备份恢复' },
      { key: 'diagnose', label: '诊断' },
    ],
  },
  {
    key: 'about',
    label: '关于系统',
    children: [{ key: 'about', label: '关于本机' }],
  },
]

const open = reactive<Record<string, boolean>>({ biz: true, ops: true, about: true })

const SECTION_TITLES: Record<Section, string> = {
  reports: '报告管理',
  accounts: '账号管理',
  config: '基本配置',
  audit: '审计日志',
  backup: '备份恢复',
  diagnose: '诊断',
  about: '关于本机',
}

function normalizeSection(value: unknown): Section {
  const keys = Object.keys(SECTION_TITLES) as Section[]
  return keys.includes(value as Section) ? (value as Section) : 'config'
}

const section = ref<Section>(normalizeSection(route.query.section))
const sectionTitle = computed(() => SECTION_TITLES[section.value])

watch(
  () => route.query.section,
  (value) => {
    section.value = normalizeSection(value)
  },
)

function select(next: Section): void {
  section.value = next
  if (route.query.section !== next) {
    void router.replace({ path: '/settings', query: { ...route.query, section: next } })
  }
}

function goBack(): void {
  void router.push('/').then(() => shell.requestView('info'))
}

async function signOut(): Promise<void> {
  await auth.signOut()
  shell.active = 'info'
  shell.requested = ''
  await router.replace({ name: 'login' })
}

const info = ref<api.SystemInfo | null>(null)
const configItems = ref<api.ConfigItem[]>([])

function mb(bytes: number): string {
  if (bytes < 0) return '未知'
  return bytes < 1024 * 1024
    ? Math.round(bytes / 1024) + ' KB'
    : (bytes / 1024 / 1024).toFixed(1) + ' MB'
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
    show('备份完成：' + res.files + ' 个文件，' + mb(res.size))
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
  <div class="settings-page">
    <aside class="settings-tree">
      <div class="tree-head">
        <span class="tree-title">系统设置</span>
        <span class="tree-sub">报告 / 账号 / 运维</span>
      </div>
      <nav class="tree-body">
        <div v-for="group in TREE" :key="group.key" class="tree-group">
          <button
            class="tree-group-head"
            type="button"
            @click="open[group.key] = !open[group.key]"
          >
            <span class="caret" :class="{ open: open[group.key] }">▸</span>
            {{ group.label }}
          </button>
          <ul v-show="open[group.key]" class="tree-children">
            <li
              v-for="leaf in group.children"
              :key="leaf.key"
              :class="{ active: section === leaf.key }"
              :data-section="leaf.key"
              @click="select(leaf.key)"
            >
              {{ leaf.label }}
            </li>
          </ul>
        </div>
      </nav>
      <div class="tree-foot">
        <button class="tree-back" type="button" @click="goBack">← 返回评估</button>
        <div class="tree-user">{{ auth.user?.display_name || auth.user?.username || '' }}</div>
        <button class="tree-link" type="button" @click="signOut">注销登录</button>
      </div>
    </aside>

    <main class="settings-body">
      <ReportListView v-if="section === 'reports'" />
      <AccountListView v-else-if="section === 'accounts'" />

      <div v-else class="page-pad">
        <div class="sheet">
          <h1 class="doc-title" style="font-size: 18px">{{ sectionTitle }}</h1>

          <template v-if="section === 'config'">
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

          <template v-else-if="section === 'audit'">
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

          <template v-else-if="section === 'backup'">
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

          <template v-else-if="section === 'diagnose'">
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
            <table v-if="info" class="data-table about-table">
              <tbody>
                <tr><th>系统版本</th><td>{{ info.version }}</td></tr>
                <tr><th>大模型</th><td>{{ info.model }}</td></tr>
                <tr>
                  <th>评价条目库</th>
                  <td>
                    {{ info.catalog.version }}　共 {{ info.catalog.count }} 条　哈希 {{ info.catalog.hash }}
                  </td>
                </tr>
                <tr><th>业务库</th><td>{{ info.db.path }}（{{ mb(info.db.size) }}）</td></tr>
                <tr><th>导出目录</th><td>{{ info.export_dir }}</td></tr>
                <tr><th>备份目录</th><td>{{ info.backup_dir }}</td></tr>
                <tr><th>磁盘剩余</th><td>{{ mb(info.disk_free) }}</td></tr>
                <tr><th>工作节点号</th><td>{{ info.worker_id }}（雪花 ID 机器位）</td></tr>
                <tr><th>时钟回拨</th><td>{{ info.clock_rollbacks }} 次</td></tr>
              </tbody>
            </table>
            <p class="hint" style="margin-top: 8px">
              依据 GB/T 42615-2023《在用电梯安全评估规范》，报告模板 JTE-09-R02-3.00。
            </p>
          </template>
        </div>
      </div>
    </main>

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
.settings-page {
  display: flex;
  height: calc(100vh - 52px);
  background: var(--c-bg);
}

/* ── 左侧树 ── */
.settings-tree {
  width: 216px;
  flex: 0 0 216px;
  display: flex;
  flex-direction: column;
  background: var(--c-panel);
  border-right: 1px solid var(--c-line);
}

.tree-head {
  padding: 16px 16px 12px;
  border-bottom: 1px solid var(--c-line-soft);
}

.tree-title {
  display: block;
  font-family: var(--font-bold);
  font-size: 15px;
  font-weight: 700;
  color: var(--c-primary);
}

.tree-sub {
  display: block;
  margin-top: 2px;
  font-size: 10.5px;
  color: var(--c-muted);
}

.tree-body {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 8px;
}

.tree-group {
  margin-bottom: 2px;
}

.tree-group-head {
  display: flex;
  align-items: center;
  gap: 6px;
  width: 100%;
  padding: 8px;
  border: 0;
  border-radius: 6px;
  background: none;
  color: var(--c-secondary);
  font: inherit;
  font-size: 12.5px;
  font-weight: 700;
  text-align: left;
  cursor: pointer;
}

.tree-group-head:hover {
  color: var(--c-primary);
  background: var(--c-head);
}

.caret {
  font-size: 10px;
  transition: transform 0.15s;
}

.caret.open {
  transform: rotate(90deg);
}

.tree-children {
  list-style: none;
  margin: 0;
  padding: 0 0 4px;
}

.tree-children li {
  margin: 1px 0;
  padding: 8px 10px 8px 26px;
  border-radius: 6px;
  font-size: 12.5px;
  color: var(--c-text);
  cursor: pointer;
  white-space: nowrap;
}

.tree-children li:hover {
  background: var(--c-head);
}

.tree-children li.active {
  background: var(--c-primary-soft);
  color: var(--c-primary);
  font-weight: 700;
  box-shadow: inset 3px 0 0 var(--c-primary);
}

.tree-foot {
  padding: 12px;
  border-top: 1px solid var(--c-line);
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.tree-back {
  font: inherit;
  font-size: 12.5px;
  padding: 8px 10px;
  border: 1px solid var(--c-line);
  border-radius: var(--radius-sm);
  background: #fff;
  color: var(--c-primary);
  cursor: pointer;
}

.tree-back:hover {
  border-color: var(--c-primary);
  background: var(--c-primary-soft);
}

.tree-user {
  font-size: 11.5px;
  color: var(--c-muted);
}

.tree-link {
  padding: 0;
  border: 0;
  background: none;
  color: var(--c-secondary);
  font: inherit;
  font-size: 11.5px;
  text-align: left;
  cursor: pointer;
}

.tree-link:hover {
  color: var(--c-danger);
}

/* ── 右侧内容 ── */
.settings-body {
  flex: 1;
  min-width: 0;
  overflow-y: auto;
}

.about-table th {
  width: 132px;
  background: var(--c-head);
  color: var(--c-text);
  font-family: var(--font-bold);
  font-weight: 700;
  text-align: left;
}

@media (max-width: 900px) {
  .settings-tree {
    width: 176px;
    flex-basis: 176px;
  }

  .tree-children li {
    padding: 8px 6px 8px 22px;
    font-size: 12px;
  }

  .tree-group-head {
    padding: 7px 6px;
  }
}
</style>
