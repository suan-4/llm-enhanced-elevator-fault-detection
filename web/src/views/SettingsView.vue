<script setup lang="ts">
/* 系统设置（2026-10 调整）：
   - 账号管理从侧栏并入本页，由左侧树状导航进入；报告管理已移到主页面第三个导航；
   - 右侧按树节点渲染内容，配置类仍是只读展示（基础版以部署 .env 为准）。 */
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import * as api from '@/api/system'
import AppDialog from '@/components/AppDialog.vue'
import AccountListView from '@/views/AccountListView.vue'
import { useAuthStore } from '@/stores/auth'
import { useShell } from '@/stores/shell'
import { ApiError } from '@/utils/http'
import { useKiosk } from '@/utils/kiosk'
import { useToast } from '@/utils/toast'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const shell = useShell()
const kiosk = useKiosk()
const { show } = useToast()

type Section = 'accounts' | 'config' | 'audit' | 'backup' | 'diagnose' | 'about'

interface TreeGroup {
  key: string
  label: string
  children: { key: Section; label: string }[]
}

/* 左侧树：业务管理（账号）+ 系统维护（配置/日志/备份/诊断）+ 关于。
   报告管理已移到主页面第三个导航（就地查看，不跳路由）。 */
const TREE: TreeGroup[] = [
  {
    key: 'biz',
    label: '业务管理',
    children: [{ key: 'accounts', label: '账号管理' }],
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

const treeOpen = ref(false)

function select(next: Section): void {
  section.value = next
  treeOpen.value = false
  if (route.query.section !== next) {
    void router.replace({ path: '/settings', query: { ...route.query, section: next } })
  }
}

async function signOut(): Promise<void> {
  await auth.signOut()
  shell.active = 'info'
  shell.requested = ''
  await router.replace({ name: 'login' })
}

const info = ref<api.SystemInfo | null>(null)
const configItems = ref<api.ConfigItem[]>([])
const configDraft = ref<Record<string, api.ConfigValue>>({})
const configBusy = ref(false)
const configError = ref('')
const configRestart = ref<string[]>([])
const pickerInfo = ref<api.FolderPickerInfo | null>(null)
const pickerBusy = ref('')

const pickerAvailable = computed(() => pickerInfo.value?.available !== false)
const pickerTitle = computed(() => {
  const info = pickerInfo.value
  if (!pickerAvailable.value) {
    return '当前环境无法打开系统目录选择窗口（可在输入框直接填写路径）'
  }
  if (!info || !info.available) return '点击后尝试打开系统目录选择框'
  return '使用 ' + info.method + ' 打开系统目录选择框'
})

/** 把服务端当前值填进表单草稿 */
function fillConfigDraft(): void {
  const next: Record<string, api.ConfigValue> = {}
  for (const item of configItems.value) {
    if (item.editable) next[item.key] = item.value
  }
  configDraft.value = next
}

/** 拉取基本配置后刷新表单（只读系统信息走「关于本机」的 info 接口，不在这里展示） */
function applyConfigPayload(payload: api.SystemConfig): void {
  configItems.value = payload.items
  fillConfigDraft()
}

/** 表单值按配置项类型归一：字符串比较时不会被 7 与 "7" 误判为改动 */
function normalizeConfig(item: api.ConfigItem, raw: api.ConfigValue | undefined): api.ConfigValue {
  if (item.type === 'int') {
    const parsed = typeof raw === 'number' ? raw : Number.parseInt(String(raw ?? '').trim(), 10)
    return Number.isFinite(parsed) ? parsed : 0
  }
  if (item.type === 'bool') return raw === true || raw === 'true'
  return String(raw ?? '')
}

const configDirty = computed(() =>
  configItems.value.some(
    (item) =>
      item.editable &&
      String(normalizeConfig(item, configDraft.value[item.key])) !== String(item.value),
  ),
)

async function saveConfig(): Promise<void> {
  if (configBusy.value || !configDirty.value) return
  configBusy.value = true
  configError.value = ''
  try {
    const values: Record<string, api.ConfigValue> = {}
    for (const item of configItems.value) {
      if (item.editable) values[item.key] = normalizeConfig(item, configDraft.value[item.key])
    }
    const res = await api.updateSystemConfig(values)
    applyConfigPayload(res)
    // 是否允许退出是全局 kiosk 状态，保存后立刻刷新，避免旧按钮继续显示。
    await kiosk.load()
    configRestart.value = (res.restart_required || []).map(
      (key) => configItems.value.find((item) => item.key === key)?.label || key,
    )
    if (configRestart.value.length) show('配置已保存，部分项需重启后端生效', 4200)
    else show('配置已保存')
  } catch (err) {
    configError.value = err instanceof ApiError ? err.detail : '保存配置失败'
  } finally {
    configBusy.value = false
  }
}

function resetConfigDraft(): void {
  configError.value = ''
  configRestart.value = []
  fillConfigDraft()
}

/** 目录项：调起服务端所在机器的系统目录选择框（Linux/Windows 均适配） */
async function chooseDirectory(item: api.ConfigItem): Promise<void> {
  if (pickerBusy.value || configBusy.value) return
  pickerBusy.value = item.key
  try {
    const current = String(configDraft.value[item.key] ?? '').trim()
    const res = await api.pickDirectory(current || undefined)
    if (res.path) {
      configDraft.value[item.key] = res.path
      show('已选择目录：' + res.path)
    }
  } catch (err) {
    show(err instanceof ApiError ? err.detail : '无法打开目录选择窗口', 4000, 'danger')
  } finally {
    pickerBusy.value = ''
  }
}

function mb(bytes: number): string {
  if (bytes < 0) return '未知'
  return bytes < 1024 * 1024
    ? Math.round(bytes / 1024) + ' KB'
    : (bytes / 1024 / 1024).toFixed(1) + ' MB'
}

async function loadInfo(): Promise<void> {
  try {
    info.value = await api.systemInfo()
    applyConfigPayload(await api.systemConfig())
    try {
      pickerInfo.value = await api.folderPickerInfo()
    } catch {
      pickerInfo.value = null
    }
  } catch (err) {
    show(err instanceof ApiError ? err.detail : '读取系统信息失败')
  }
}

const auditEvent = ref('')
const AUDIT_EVENTS: { value: string; label: string }[] = [
  { value: 'login_ok', label: '登录成功' },
  { value: 'login_fail', label: '登录失败' },
  { value: 'report_generate', label: '生成报告' },
  { value: 'report_export', label: '导出报告' },
  { value: 'report_void', label: '作废报告' },
  { value: 'report_delete', label: '删除报告' },
  { value: 'account_create', label: '新增账号' },
  { value: 'account_update', label: '修改账号' },
  { value: 'account_delete', label: '删除账号' },
  { value: 'config_update', label: '修改配置' },
  { value: 'backup_create', label: '新建备份' },
  { value: 'backup_restore', label: '恢复备份' },
]
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
  <div class="settings-page" :class="{ 'tree-open': treeOpen }">
    <button
      v-if="!treeOpen"
      class="tree-fab"
      type="button"
      title="设置导航"
      aria-label="打开设置导航"
      @click="treeOpen = true"
    >
      ☰
    </button>
    <div v-if="treeOpen" class="tree-mask" aria-hidden="true" @click="treeOpen = false" />
    <aside class="settings-tree" :class="{ open: treeOpen }">
      <div class="tree-head">
        <div class="tree-head-text">
          <span class="tree-title">系统设置</span>
          <span class="tree-sub">报告 / 账号 / 运维</span>
        </div>
        <button class="tree-close" type="button" title="收起" aria-label="收起导航" @click="treeOpen = false">
          ×
        </button>
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
        <div class="tree-user">{{ auth.user?.display_name || auth.user?.username || '' }}</div>
        <button class="tree-link" type="button" @click="signOut">注销登录</button>
      </div>
    </aside>

    <main class="settings-body">
      <AccountListView v-if="section === 'accounts'" />

      <div v-else class="page-pad">
        <div class="sheet">
          <h1 class="doc-title settings-title">{{ sectionTitle }}</h1>

          <template v-if="section === 'config'">
            <div v-if="configError" class="err-box">{{ configError }}</div>
            <table class="data-table config-table">
              <thead>
                <tr>
                  <th class="config-key">配置项</th>
                  <th class="config-val">当前值</th>
                  <th class="config-desc">说明</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="item in configItems" :key="item.key">
                  <td data-label="配置项">
                    {{ item.label }}
                    <span v-if="item.restart" class="restart-tag">重启生效</span>
                  </td>
                  <td data-label="当前值">
                    <template v-if="item.editable">
                      <div v-if="item.ui === 'directory'" class="dir-field">
                        <input v-model="configDraft[item.key]" class="input" type="text" />
                        <button
                          class="btn dir-pick"
                          type="button"
                          :title="pickerTitle"
                          :disabled="configBusy || pickerBusy === item.key || !pickerAvailable"
                          @click="chooseDirectory(item)"
                        >
                          {{ pickerBusy === item.key ? '选择中…' : '选择…' }}
                        </button>
                      </div>
                      <select
                        v-else-if="item.type === 'bool'"
                        v-model="configDraft[item.key]"
                        class="select"
                      >
                        <option :value="true">启用</option>
                        <option :value="false">禁用</option>
                      </select>
                      <input
                        v-else
                        v-model="configDraft[item.key]"
                        class="input"
                        :type="item.type === 'int' ? 'number' : 'text'"
                        :min="item.min"
                        :max="item.max"
                      />
                    </template>
                    <span v-else>{{ item.value }}</span>
                  </td>
                  <td data-label="说明">{{ item.desc }}</td>
                </tr>
              </tbody>
            </table>

            <div class="config-actions">
              <button
                class="btn btn-primary config-save"
                type="button"
                :disabled="configBusy || !configDirty"
                @click="saveConfig"
              >
                {{ configBusy ? '保存中…' : '保存配置' }}
              </button>
              <button
                class="btn config-reset"
                type="button"
                :disabled="configBusy || !configDirty"
                @click="resetConfigDraft"
              >
                撤销修改
              </button>
              <span v-if="configDirty" class="hint">有未保存的修改</span>
              <span v-else class="hint">
                修改后点「保存配置」；目录项可点「选择…」调起系统文件夹选择框（Linux/Windows 适配）
              </span>
            </div>
            <div v-if="configRestart.length" class="restart-box">
              以下配置已保存，需要重启后端服务后生效：{{ configRestart.join('、') }}
            </div>
          </template>

          <template v-else-if="section === 'audit'">
            <div class="toolbar">
              <select v-model="auditEvent" class="select" @change="loadAudit">
                <option value="">全部事件</option>
                <option v-for="evt in AUDIT_EVENTS" :key="evt.value" :value="evt.value">
                  {{ evt.label }}
                </option>
              </select>
              <input v-model="auditActor" class="input" placeholder="操作者姓名或 ID" @keyup.enter="loadAudit" />
              <button class="btn" type="button" @click="loadAudit">查询</button>
            </div>
            <div v-if="auditLoading" class="empty-state">加载中…</div>
            <div v-else-if="!auditRows.length" class="empty-state">没有符合条件的日志。</div>
            <table v-else class="data-table audit-table">
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
                  <th>业务库路径</th>
                  <td>{{ info.db.path }}（{{ mb(info.db.size) }}）</td>
                </tr>
                <tr>
                  <th>评价条目库</th>
                  <td>
                    {{ info.catalog.version }}　共 {{ info.catalog.count }} 条　哈希 {{ info.catalog.hash }}
                  </td>
                </tr>
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

/* ── 左侧树（悬浮、可展开/折叠） ── */
.settings-tree {
  width: 216px;
  flex: 0 0 216px;
  display: flex;
  flex-direction: column;
  background: var(--c-panel);
  border-right: 1px solid var(--c-line);
  position: fixed;
  top: 52px;
  bottom: 0;
  left: 0;
  z-index: 130;
  transform: translateX(-104%);
  transition: transform 0.22s ease;
  box-shadow: 6px 0 22px rgba(0, 0, 0, 0.16);
}

.settings-tree.open {
  transform: none;
}

.tree-fab {
  position: fixed;
  left: 0;
  top: 64px;
  z-index: 125;
  width: 34px;
  height: 64px;
  padding: 0;
  border: 1px solid var(--c-line);
  border-left: 0;
  border-radius: 0 10px 10px 0;
  background: var(--c-panel);
  color: var(--c-primary);
  font-size: 18px;
  cursor: pointer;
  box-shadow: 4px 0 14px rgba(0, 0, 0, 0.1);
}

.tree-mask {
  position: fixed;
  inset: 52px 0 0 0;
  z-index: 120;
  background: rgba(15, 25, 38, 0.28);
}

.tree-close {
  margin-left: auto;
  padding: 0 4px;
  border: 0;
  background: none;
  color: var(--c-muted);
  font-size: 20px;
  line-height: 1;
  cursor: pointer;
}

.tree-home {
  display: none;
}

.tree-head {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 16px 16px 12px;
  border-bottom: 1px solid var(--c-line-soft);
}

.tree-home {
  flex: 0 0 auto;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  padding: 0;
  border: 1px solid var(--c-line);
  border-radius: 8px;
  background: #fff;
  color: var(--c-primary);
  cursor: pointer;
  transition: background 0.15s, border-color 0.15s;
}

.tree-home:hover {
  border-color: var(--c-primary);
  background: var(--c-primary-soft);
}

.tree-head-text {
  display: flex;
  flex-direction: column;
  min-width: 0;
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

.config-key {
  width: 190px;
}

.config-val {
  width: 320px;
}

.config-table .input,
.config-table .select {
  max-width: 300px;
}

.dir-field {
  display: flex;
  align-items: center;
  gap: 8px;
}

.dir-field .input {
  flex: 1;
  min-width: 0;
}

.dir-pick {
  flex: 0 0 auto;
  white-space: nowrap;
}

.restart-tag {
  display: inline-block;
  margin-left: 6px;
  padding: 0 6px;
  border-radius: 8px;
  background: var(--c-primary-soft);
  color: var(--c-primary);
  font-size: 10.5px;
  white-space: nowrap;
}

.config-actions {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  margin-top: 12px;
}

.restart-box {
  margin-top: 10px;
  padding: 8px 12px;
  border-radius: var(--radius-sm);
  background: var(--c-primary-soft);
  color: var(--c-primary);
  font-size: 12.5px;
}

.about-table th {
  width: 132px;
  background: var(--c-head);
  color: var(--c-text);
  font-family: var(--font-bold);
  font-weight: 700;
  text-align: left;
}

/* 横屏矮视口（板端 960×600）：设置页的树与内容同步收缩 */
@media (min-width: 901px) and (max-height: 700px) {
  /* 横屏矮视口：左树改成按内容高度的卡片，不再拉成整列白底 + 下方一大片空白 */
  .settings-page {
    align-items: flex-start;
    gap: 8px;
    padding: 8px;
  }

  .settings-tree {
    height: auto;
    max-height: calc(100vh - 52px - 16px);
    border: 1px solid var(--c-line);
    border-radius: var(--radius);
    box-shadow: var(--shadow);
    overflow: hidden;
  }

  .tree-body {
    flex: 0 0 auto;
    overflow-y: auto;
  }

  .settings-body {
    flex: 1 1 auto;
    min-width: 0;
    height: calc(100vh - 52px - 16px);
  }

  /* 左右两张卡片顶边对齐：去掉 page-pad 与 sheet 的上外边距，
     否则内容卡片会比左侧树卡片低 20px */
  .settings-body .page-pad {
    padding: 0;
  }

  .settings-body .page-pad .sheet {
    width: 100%;
    margin: 0 auto;
  }

  .settings-title {
    font-size: 16px;
  }

  /* 基本配置表：收窄「配置项/当前值」，把宽度让给「说明」，避免说明被挤成多行 */
  .config-key {
    width: 118px;
  }

  .config-val {
    width: 236px;
  }

  /* 横屏审计日志：覆盖模板固定列宽，给备注留足空间 */
  .audit-table th:nth-child(1),
  .audit-table td:nth-child(1) {
    width: 112px !important;
  }

  .audit-table th:nth-child(2),
  .audit-table td:nth-child(2) {
    width: 98px !important;
  }

  .audit-table th:nth-child(3),
  .audit-table td:nth-child(3) {
    width: 70px !important;
  }

  .audit-table th:nth-child(4),
  .audit-table td:nth-child(4) {
    width: 118px !important;
  }

  .audit-table th:nth-child(5),
  .audit-table td:nth-child(5) {
    width: auto !important;
    min-width: 150px;
  }

  .config-table th,
  .config-table td {
    padding: 3px 6px;
    font-size: 11.5px;
    line-height: 1.4;
  }

  .config-table .input,
  .config-table .select {
    height: 28px;
    font-size: 12px;
  }

  .config-table .dir-pick {
    height: 28px;
    padding: 0 8px;
    font-size: 12px;
  }

  .config-table .restart-tag {
    margin-left: 4px;
    padding: 0 4px;
    font-size: 9.5px;
  }

  .dir-field {
    gap: 6px;
  }

  .settings-tree {
    width: 176px;
    flex-basis: 176px;
  }

  .tree-head {
    gap: 8px;
    padding: 10px 12px 8px;
  }

  .tree-home {
    width: 26px;
    height: 26px;
  }

  .tree-title {
    font-size: 13.5px;
  }

  .tree-sub {
    font-size: 9.5px;
  }

  .tree-body {
    padding: 6px;
  }

  .tree-group-head {
    padding: 6px;
    font-size: 11.5px;
  }

  .tree-children li {
    padding: 6px 8px 6px 22px;
    font-size: 11.5px;
  }

  .tree-foot {
    padding: 8px;
    gap: 6px;
  }

  .tree-user {
    font-size: 10.5px;
  }
}

@media (max-width: 900px) {
  /* 竖屏悬浮树也做成和横屏一致的圆角卡片 */
  .settings-tree {
    width: 160px;
    flex-basis: 160px;
    top: 60px;
    bottom: 8px;
    left: 8px;
    border: 1px solid var(--c-line);
    border-radius: var(--radius);
    box-shadow: var(--shadow);
    overflow: hidden;
  }

  .tree-head {
    padding: 10px 8px 8px;
    gap: 6px;
  }

  .tree-home {
    width: 26px;
    height: 26px;
  }

  .tree-title {
    font-size: 13.5px;
  }

  .tree-sub {
    font-size: 9.5px;
  }

  .tree-body {
    padding: 6px;
  }

  .tree-children li {
    padding: 6px 4px 6px 18px;
    font-size: 11.5px;
  }

  .tree-group-head {
    padding: 6px;
    font-size: 11.5px;
  }

  .settings-body .page-pad {
    padding: 8px;
  }

  .settings-body .doc-title {
    font-size: 16px;
  }

  /* 基本配置/审计/备份/诊断表：竖屏也保持表格版式，不再拆成竖排卡片 */
  .settings-body .data-table {
    display: table;
  }

  .settings-body .data-table thead {
    display: table-header-group;
  }

  .settings-body .data-table tbody {
    display: table-row-group;
  }

  .settings-body .data-table tr {
    display: table-row;
    margin: 0;
    border-radius: 0;
    overflow: visible;
  }

  .settings-body .data-table th,
  .settings-body .data-table td {
    display: table-cell;
    padding: 3px 5px;
    font-size: 11.5px;
    vertical-align: top;
  }

  .settings-body .data-table td::before {
    content: none;
  }

  .settings-body .data-table .actions .btn {
    height: 22px;
    padding: 0 5px;
    font-size: 10.5px;
  }

  .config-table .config-key {
    width: 96px;
  }

  .config-table .config-val {
    width: auto;
  }

  /* 竖屏基本配置：第二列（当前值）输入框占满，选择按钮贴右 */
  .config-table td:nth-child(2) .input,
  .config-table td:nth-child(2) .select {
    width: 100%;
    max-width: none;
  }

  .config-table td:nth-child(2) .dir-field {
    display: flex;
    align-items: center;
    gap: 6px;
    width: 100%;
  }

  .config-table td:nth-child(2) .dir-field .input {
    flex: 1 1 auto;
    min-width: 0;
    width: auto;
  }

  .config-table td:nth-child(2) .dir-pick {
    flex: 0 0 auto;
    margin-left: auto;
  }

  .config-table th:nth-child(3),
  .config-table td:nth-child(3) {
    display: none;
  }

  /* 各管理页工具栏（报告/账号/审计/备份）：竖屏收成一两行 */
  .settings-body .toolbar,
  .settings-body :deep(.toolbar) {
    gap: 6px;
    margin-bottom: 8px;
  }

  .settings-body .toolbar .input,
  .settings-body :deep(.toolbar .input) {
    flex: 1 1 130px;
    min-width: 0;
    height: 30px;
    font-size: 12px;
  }

  .settings-body .toolbar .select,
  .settings-body :deep(.toolbar .select) {
    flex: 0 1 120px;
    min-width: 0;
    height: 30px;
    font-size: 12px;
  }

  .settings-body .toolbar .btn,
  .settings-body :deep(.toolbar .btn) {
    flex: 0 0 auto;
    height: 30px;
    padding: 0 10px;
    font-size: 12px;
  }

  .settings-body .toolbar .chk,
  .settings-body :deep(.toolbar .chk) {
    font-size: 11.5px;
    white-space: nowrap;
  }

  /* 竖屏设置内容占满宽度 */
  .settings-body .page-pad {
    padding: 6px;
  }

  .settings-body .page-pad .sheet {
    width: 100%;
    max-width: 100%;
    margin: 0;
  }

  .settings-body .data-table {
    width: 100%;
  }

  /* 审计日志列宽：备注列给足宽度 */
  .audit-table th:nth-child(1),
  .audit-table td:nth-child(1) {
    width: 84px;
  }

  .audit-table th:nth-child(2),
  .audit-table td:nth-child(2) {
    width: 62px;
  }

  .audit-table th:nth-child(3),
  .audit-table td:nth-child(3) {
    width: 58px;
  }

  .audit-table th:nth-child(4),
  .audit-table td:nth-child(4) {
    width: 70px;
  }

  .audit-table th:nth-child(5),
  .audit-table td:nth-child(5) {
    width: auto;
    min-width: 110px;
  }
}
</style>
