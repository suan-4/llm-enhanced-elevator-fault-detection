<script setup lang="ts">
/* 账号管理（单角色：登录即可）。
   前端先把能拦的拦掉（最后一个启用账号、当前登录账号），
   后端也会拒 —— 前端拦是为了少一次白点的挫败感。 */
import { computed, onMounted, ref } from 'vue'
import * as api from '@/api/accounts'
import AppDialog from '@/components/AppDialog.vue'
import { useAuthStore } from '@/stores/auth'
import { ApiError } from '@/utils/http'
import { useToast } from '@/utils/toast'

const { show } = useToast()
const auth = useAuthStore()

const accounts = ref<api.Account[]>([])
const total = ref(0)
const q = ref('')
const status = ref('')
const loading = ref(false)
const loadError = ref('')

const activeCount = computed(() => accounts.value.filter((a) => a.is_active).length)
const isSelf = (a: api.Account): boolean => String(a.id) === String(auth.user?.id ?? '')
/** 最后一个启用账号：停用/删除它就没人能登录了 */
const isLastActive = (a: api.Account): boolean => a.is_active && activeCount.value <= 1

function rowHint(a: api.Account): string {
  if (isSelf(a)) return '这是当前登录的账号'
  if (isLastActive(a)) return '最后一个启用账号，停用后没人能登录'
  return ''
}

function fmt(at: string | null): string {
  return at ? at.replace('T', ' ').slice(0, 16) : '—'
}

async function load(): Promise<void> {
  loading.value = true
  loadError.value = ''
  try {
    const res = await api.listAccounts({ q: q.value.trim(), status: status.value })
    accounts.value = res.items
    total.value = res.total
  } catch (err) {
    loadError.value = err instanceof ApiError ? err.detail : '加载失败'
  } finally {
    loading.value = false
  }
}

/* ── 弹层状态机 ─────────────────────────────────────── */
type DialogKind = '' | 'create' | 'edit' | 'reset' | 'confirm'
const dialog = ref<DialogKind>('')
const busy = ref(false)
const dialogError = ref('')

const createForm = ref({
  display_name: '',
  username: '',
  employee_no: '',
  password: '',
  require_change: true,
})
const editTarget = ref<api.Account | null>(null)
const editForm = ref({ display_name: '', employee_no: '' })
const resetTarget = ref<api.Account | null>(null)
const resetForm = ref({ new_password: '', require_change: true })
const confirmMessage = ref('')
let confirmAction: (() => Promise<void>) | null = null

function closeDialog(): void {
  if (busy.value) return
  dialog.value = ''
  dialogError.value = ''
}

function openCreate(): void {
  createForm.value = {
    display_name: '',
    username: '',
    employee_no: '',
    password: '',
    require_change: true,
  }
  dialogError.value = ''
  dialog.value = 'create'
}

function openEdit(a: api.Account): void {
  editTarget.value = a
  editForm.value = { display_name: a.display_name, employee_no: a.employee_no }
  dialogError.value = ''
  dialog.value = 'edit'
}

function openReset(a: api.Account): void {
  resetTarget.value = a
  resetForm.value = { new_password: '', require_change: true }
  dialogError.value = ''
  dialog.value = 'reset'
}

function openConfirm(message: string, action: () => Promise<void>): void {
  confirmMessage.value = message
  confirmAction = action
  dialogError.value = ''
  dialog.value = 'confirm'
}

const weakPassword = computed(() => {
  const value = createForm.value.password
  if (!value) return ''
  if (value.length < 8) return '口令至少 8 位'
  if (!/[A-Za-z]/.test(value) || !/\d/.test(value)) return '口令需要同时包含字母和数字'
  return ''
})

async function submitCreate(): Promise<void> {
  if (busy.value || weakPassword.value) return
  busy.value = true
  dialogError.value = ''
  try {
    await api.createAccount({
      display_name: createForm.value.display_name.trim(),
      username: createForm.value.username.trim(),
      employee_no: createForm.value.employee_no.trim(),
      password: createForm.value.password,
      require_change: createForm.value.require_change,
    })
    dialog.value = ''
    show('账号已创建')
    await load()
  } catch (err) {
    dialogError.value = err instanceof ApiError ? err.detail : '开户失败'
  } finally {
    busy.value = false
  }
}

async function submitEdit(): Promise<void> {
  const target = editTarget.value
  if (!target || busy.value) return
  busy.value = true
  dialogError.value = ''
  try {
    await api.updateAccount(target.id, {
      display_name: editForm.value.display_name.trim(),
      employee_no: editForm.value.employee_no.trim(),
    })
    dialog.value = ''
    show('已保存')
    await load()
  } catch (err) {
    dialogError.value = err instanceof ApiError ? err.detail : '保存失败'
  } finally {
    busy.value = false
  }
}

async function submitReset(): Promise<void> {
  const target = resetTarget.value
  if (!target || busy.value || resetForm.value.new_password.length < 8) return
  busy.value = true
  dialogError.value = ''
  try {
    await api.resetPassword(target.id, resetForm.value.new_password, resetForm.value.require_change)
    dialog.value = ''
    show('口令已重置，该账号已下线')
    await load()
  } catch (err) {
    dialogError.value = err instanceof ApiError ? err.detail : '重置失败'
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

function toggleActive(a: api.Account): void {
  const turningOff = a.is_active
  openConfirm(
    turningOff
      ? `确定停用「${a.display_name}」？停用后该账号立刻下线，且无法再登录。`
      : `确定启用「${a.display_name}」？`,
    async () => {
      await api.updateAccount(a.id, { is_active: !turningOff, confirm: true })
      show(turningOff ? '账号已停用' : '账号已启用')
    },
  )
}

function remove(a: api.Account): void {
  openConfirm(`确定删除「${a.display_name}」？该操作不可撤销（有报告的账号只能停用）。`, async () => {
    await api.deleteAccount(a.id)
    show('账号已删除')
  })
}

onMounted(load)
</script>

<template>
  <div class="page-pad">
    <div class="sheet">
      <h1 class="doc-title" style="font-size: 18px">账号管理</h1>

      <div class="toolbar">
        <input
          v-model="q"
          class="input"
          type="text"
          placeholder="搜索姓名或用户名"
          @keyup.enter="load"
        />
        <select v-model="status" class="select" @change="load">
          <option value="">全部状态</option>
          <option value="active">启用</option>
          <option value="disabled">停用</option>
        </select>
        <button class="btn" type="button" @click="load">查询</button>
        <span class="spacer" />
        <button class="btn btn-primary" type="button" @click="openCreate">新增账号</button>
      </div>

      <div v-if="loadError" class="err-box">{{ loadError }}</div>
      <div v-else-if="loading" class="empty-state">加载中…</div>
      <div v-else-if="!accounts.length" class="empty-state">还没有账号，点右上角「新增账号」开始。</div>

      <table v-else class="data-table">
        <thead>
          <tr>
            <th>姓名</th>
            <th>用户名</th>
            <th>工号</th>
            <th>状态</th>
            <th>最后登录</th>
            <th style="width: 250px">操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="a in accounts" :key="a.id">
            <td data-label="姓名">
              {{ a.display_name }}
              <span v-if="isSelf(a)" class="hint">（我）</span>
            </td>
            <td data-label="用户名">{{ a.username }}</td>
            <td data-label="工号">{{ a.employee_no || '—' }}</td>
            <td data-label="状态">
              <span class="status-tag" :class="a.is_active ? 'on' : 'off'">
                {{ a.is_active ? '启用' : '停用' }}
              </span>
            </td>
            <td data-label="最后登录">{{ fmt(a.last_login_at) }}</td>
            <td data-label="操作">
              <div class="actions">
                <button class="btn" type="button" @click="openEdit(a)">编辑</button>
                <button class="btn" type="button" @click="openReset(a)">重置口令</button>
                <button
                  class="btn"
                  type="button"
                  :disabled="a.is_active ? isSelf(a) || isLastActive(a) : false"
                  :title="rowHint(a)"
                  @click="toggleActive(a)"
                >
                  {{ a.is_active ? '停用' : '启用' }}
                </button>
                <button
                  class="btn"
                  type="button"
                  :disabled="isSelf(a) || isLastActive(a)"
                  :title="rowHint(a)"
                  @click="remove(a)"
                >
                  删除
                </button>
              </div>
            </td>
          </tr>
        </tbody>
      </table>
      <p v-if="accounts.length" class="hint" style="margin-top: 8px">
        共 {{ total }} 个账号（启用 {{ activeCount }} 个）。用户名创建后不可修改；有报告的账号只能停用。
      </p>
    </div>

    <!-- 新增 -->
    <AppDialog
      :open="dialog === 'create'"
      title="新增账号"
      confirm-text="创建"
      :busy="busy"
      @close="closeDialog"
      @confirm="submitCreate"
    >
      <div v-if="dialogError" class="err-box">{{ dialogError }}</div>
      <div class="field">
        <label>姓名</label>
        <input v-model="createForm.display_name" class="input" placeholder="真实姓名，进报告与留痕" />
      </div>
      <div class="field">
        <label>登录用户名</label>
        <input v-model="createForm.username" class="input" placeholder="创建后不可修改" />
      </div>
      <div class="field">
        <label>工号（可空）</label>
        <input v-model="createForm.employee_no" class="input" />
      </div>
      <div class="field">
        <label>初始口令</label>
        <input v-model="createForm.password" class="input" type="password" placeholder="至少 8 位，含字母和数字" />
        <span v-if="weakPassword" class="err">{{ weakPassword }}</span>
      </div>
      <label class="chk">
        <input v-model="createForm.require_change" type="checkbox" />
        <span>要求对方首次登录后修改口令</span>
      </label>
    </AppDialog>

    <!-- 编辑 -->
    <AppDialog
      :open="dialog === 'edit'"
      title="编辑账号"
      confirm-text="保存"
      :busy="busy"
      @close="closeDialog"
      @confirm="submitEdit"
    >
      <div v-if="dialogError" class="err-box">{{ dialogError }}</div>
      <div class="field">
        <label>姓名</label>
        <input v-model="editForm.display_name" class="input" />
      </div>
      <div class="field">
        <label>工号</label>
        <input v-model="editForm.employee_no" class="input" />
      </div>
      <p class="hint">用户名（{{ editTarget?.username }}）不可修改。</p>
    </AppDialog>

    <!-- 重置口令 -->
    <AppDialog
      :open="dialog === 'reset'"
      title="重置口令"
      confirm-text="重置"
      :busy="busy"
      @close="closeDialog"
      @confirm="submitReset"
    >
      <div v-if="dialogError" class="err-box">{{ dialogError }}</div>
      <p class="hint">重置后「{{ resetTarget?.display_name }}」的所有登录会话立即失效。</p>
      <div class="field">
        <label>新口令</label>
        <input v-model="resetForm.new_password" class="input" type="password" placeholder="至少 8 位，含字母和数字" />
      </div>
      <label class="chk">
        <input v-model="resetForm.require_change" type="checkbox" />
        <span>要求对方首次登录后修改口令</span>
      </label>
    </AppDialog>

    <!-- 二次确认 -->
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
