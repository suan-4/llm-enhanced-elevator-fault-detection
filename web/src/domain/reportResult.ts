import type { JteItem } from '@/types/api'
import type { AppendixRow } from '@/types/report'
import type { RiskValue } from './riskAssign'
import { CAT_MEASURE } from './riskScore'
import { reasonsText, type ItemState } from './validation'

/** One final category per item; keep every risk and its own measure. */
export function buildAppendixRows(
  items: JteItem[], stateOf: (no: string) => ItemState, risks: Record<string, RiskValue>,
): AppendixRow[] {
  return items.flatMap((item) => {
    const state = stateOf(item.no)
    const risk = risks[item.no]
    if (state.result !== '不符合' || !risk) return []
    if (risk.selected_risks) {
      return risk.selected_risks.map(detail => ({
        key: `${item.no}:${detail.key}`, no: item.no,
        risk,
        text: detail.text, measure: detail.measure,
      }))
    }
    return [{ key: `${item.no}:legacy`, no: item.no, risk, text: reasonsText(state), measure: CAT_MEASURE[risk.category] }]
  })
}
