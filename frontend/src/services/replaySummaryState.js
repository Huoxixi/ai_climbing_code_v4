// One automatic recap per record; manual opening is never put on a timer.
export function createReplaySummaryController({
  onChange = () => {}, now = () => Date.now(),
  schedule = (fn, delay) => setTimeout(fn, delay), cancel = id => clearTimeout(id),
} = {}) {
  const seen = new Set()
  let recordId, timer, started, duration, disposed = false
  let state = { phase: 'hidden', elapsed: 0, reducedMotion: false }
  const clear = () => { if (timer != null) cancel(timer); timer = null }
  const publish = next => { state = next; onChange({ ...state }) }
  function collapse() {
    if (disposed) return
    clear()
    if (state.phase !== 'hidden') publish({ ...state, phase: 'collapsed' })
  }
  function advance() {
    if (disposed || state.phase !== 'automatic') return
    const elapsed = Math.max(0, (now() - started) / 1000)
    if (elapsed >= duration) { collapse(); return }
    publish({ ...state, elapsed })
    timer = schedule(advance, Math.min(200, (duration - elapsed) * 1000))
  }
  return {
    get state() { return { ...state } },
    setRecord(id) {
      if (disposed || id === recordId) return
      clear(); recordId = id
      publish({ phase: seen.has(id) ? 'collapsed' : 'hidden', elapsed: 0, reducedMotion: false })
    },
    ended(seconds, reducedMotion = false) {
      if (disposed || !recordId || seen.has(recordId) || !(seconds > 0)) return false
      seen.add(recordId); clear(); started = now()
      duration = reducedMotion ? Math.max(8, Math.min(16, seconds)) : seconds
      publish({ phase: 'automatic', elapsed: 0, reducedMotion })
      timer = schedule(advance, Math.min(200, duration * 1000))
      return true
    },
    open() {
      if (disposed || !recordId) return
      seen.add(recordId); clear()
      publish({ phase: 'manual', elapsed: 0, reducedMotion: state.reducedMotion })
    },
    collapse,
    interrupt() { if (state.phase === 'automatic') collapse() },
    dispose() { clear(); disposed = true },
  }
}
