/** 去掉条款编号前缀：`a)` `b)` `1)` `f)` 等。
 *
 *  模板 docx 的「评价内容与要求」是按 a) b) c) 分条罗列的，
 *  这些字母只是原文的排版标记，录入与报告里都不显示。
 *  数据源（backend/app/data/jte_items.json）保持原样不动，
 *  只在载入时归一化，便于随时与模板对账。 */
export function stripClauseMarker(text: string): string {
  return text.replace(/^\s*[A-Za-z0-9]{1,2}[)）]\s*/, '')
}
