export function editText(value: string, start: number, end: number, text: string,
  deleting = false, maxLength = -1, numeric = false): { value: string; cursor: number } {
  start = Math.max(0, Math.min(start, value.length))
  end = Math.max(start, Math.min(end, value.length))
  if (deleting && start === end && start > 0) {
    const prefix = value.slice(0, start)
    type Segment = { index: number }
    const intl = Intl as unknown as { Segmenter?: new (locale: string, options: { granularity: string }) => { segment(value: string): Iterable<Segment> } }
    if (intl.Segmenter) {
      const parts = [...new intl.Segmenter('zh', { granularity: 'grapheme' }).segment(prefix)]
      start = parts[parts.length - 1]?.index ?? 0
    } else {
      const parts = Array.from(prefix)
      start -= parts[parts.length - 1]?.length ?? 1
    }
  }
  if (numeric && !/^[0-9.]*$/.test(text)) return { value, cursor: start }
  if (maxLength >= 0) {
    const space = Math.max(0, maxLength - (value.length - (end - start)))
    let accepted = ''
    for (const char of text) {
      if (accepted.length + char.length > space) break
      accepted += char
    }
    text = accepted
  }
  const result = value.slice(0, start) + text + value.slice(end)
  if (numeric && !/^\d*\.?\d*$/.test(result)) return { value, cursor: start }
  return { value: result, cursor: start + text.length }
}
