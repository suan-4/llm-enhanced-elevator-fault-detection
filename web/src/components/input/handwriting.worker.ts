/// <reference lib="webworker" />
declare const HanziLookup: {
  init(name: string, path: string, callback: (ok: boolean) => void): void
  AnalyzedCharacter: new (strokes: number[][][]) => unknown
  Matcher: new (name: string) => { match(character: unknown, count: number, callback: (matches: { character: string }[]) => void): void }
}
let loaded: Promise<void> | undefined
self.onmessage = async (event: MessageEvent<{ id: number; strokes: number[][][] }>) => {
  const { id, strokes } = event.data
  try {
    loaded ??= new Promise<void>((resolve, reject) => {
      importScripts('/assets/keyboard/hanzilookup.min.js')
      HanziLookup.init('local', '/assets/keyboard/mmah.json', ok => ok ? resolve() : reject(new Error('字库加载失败')))
    })
    await loaded
    new HanziLookup.Matcher('local').match(new HanziLookup.AnalyzedCharacter(strokes), 10,
      matches => self.postMessage({ id, candidates: matches.map(m => m.character) }))
  } catch {
    loaded = undefined
    self.postMessage({ id, candidates: [], error: '手写字库暂不可用，请重新打开手写' })
  }
}
export {}
