/* 知识图谱 v2 检索（MVP） */
import { request } from '@/utils/http'

export interface KgCandidate {
  rank: number
  score: number
  path_id: string
  path_summary: string
  system: string
  component: string
  states: string[]
  mechanism_steps: string[]
  trigger_condition: string
  barrier_condition: string
  risk: string
  inspection: string
  acceptance_basis: string
  action: string
  verification: string
  clause: { standard_code?: string; clause_no?: string; title?: string; legal_status?: string }
  confidence: number
  verified: string
  evidence_class: string
  source_refs: unknown[]
  matched_terms: string[]
}

export interface KgSummary {
  text: string
  systems: string[]
  components: string[]
  mechanisms: string[]
  count: number
}

export interface KgCandidatesResponse {
  success: boolean
  item_no: string
  item_name: string
  item_system: string
  query: string
  query_terms: string[]
  candidates: KgCandidate[]
  summary: KgSummary
  meta: { engine: string; kg_version: string; retrieved_at: string }
}

export interface KgCandidatesRequest {
  item_no: string
  item_name?: string
  reasons?: string[]
  other_text?: string
  top_k?: number
}

export function fetchKgStatus(): Promise<{ success: boolean; available: boolean; paths: number; items: number }> {
  return request('/kg/status')
}

export function fetchKgCandidates(payload: KgCandidatesRequest): Promise<KgCandidatesResponse> {
  return request('/kg/candidates', { method: 'POST', body: payload })
}

export interface KgSelectRequest {
  report_id?: string | null
  item_no: string
  item_name?: string
  query: string
  path_id: string | null
  decision: 'selected' | 'no_candidate'
  rank?: number | null
  top3: { rank: number; path_id: string; path_summary: string; component: string; system: string; score: number }[]
}

export function selectKgPath(payload: KgSelectRequest): Promise<{ success: boolean; id: number }> {
  return request('/kg/select', { method: 'POST', body: payload })
}
