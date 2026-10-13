/* 系统管理接口：信息、配置（只读）、审计、诊断、备份、恢复。 */
import { request } from '@/utils/http'

export interface CatalogInfo {
  version: string
  count: number
  hash: string
  ok: boolean
}

export interface SystemInfo {
  success: boolean
  version: string
  model: string
  catalog: CatalogInfo
  db: { path: string; size: number; schema_version: number; tables: string[] }
  export_dir: string
  backup_dir: string
  disk_free: number
  worker_id: number
  clock_rollbacks: number
}

export interface ConfigItem {
  key: string
  value: string
  editable: boolean
  desc: string
}

export interface AuditEvent {
  id: string
  at: string
  actor_id: string | null
  actor_name: string
  event: string
  target: string
  result: string
  note: string
}

export interface DiagnoseCheck {
  name: string
  status: 'ok' | 'warn' | 'fail'
  detail: string
  advice?: string
}

export interface BackupEntry {
  dir: string
  name: string
  created_at: string
  files: number
  size: number
}

export function systemInfo(): Promise<SystemInfo> {
  return request('/system/info')
}

export function systemConfig(): Promise<{ success: boolean; items: ConfigItem[] }> {
  return request('/system/config')
}

export function auditEvents(
  params: {
    event?: string
    actor?: string
    date_from?: string
    date_to?: string
    page?: number
    size?: number
  } = {},
): Promise<{ success: boolean; total: number; items: AuditEvent[] }> {
  const query = new URLSearchParams()
  if (params.event) query.set('event', params.event)
  if (params.actor) query.set('actor', params.actor)
  if (params.date_from) query.set('date_from', params.date_from)
  if (params.date_to) query.set('date_to', params.date_to)
  query.set('page', String(params.page ?? 1))
  query.set('size', String(params.size ?? 50))
  return request(`/system/audit?${query.toString()}`)
}

export function diagnose(): Promise<{
  success: boolean
  overall: 'ok' | 'warn' | 'fail'
  checks: DiagnoseCheck[]
  at: string
}> {
  return request('/system/diagnose')
}

export function listBackups(): Promise<{ success: boolean; total: number; items: BackupEntry[] }> {
  return request('/system/backups')
}

export function runBackup(targetDir?: string): Promise<{
  success: boolean
  dir: string
  files: number
  size: number
}> {
  const query = targetDir ? `?target_dir=${encodeURIComponent(targetDir)}` : ''
  return request(`/system/backup${query}`, { method: 'POST' })
}

export function runRestore(sourceDir: string): Promise<{
  success: boolean
  pre_backup: string
  restart_required: boolean
}> {
  return request(`/system/restore?source_dir=${encodeURIComponent(sourceDir)}&confirm=true`, {
    method: 'POST',
  })
}
