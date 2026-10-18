// Only a completed replay consumes the automatic pass; the card host advances it.
export function createReplaySummaryController({ onChange = () => {} } = {}) {
  const seen = new Set()
  let recordId, disposed = false
  let state = { phase: 'hidden', elapsed: 0, reducedMotion: false }
  const publish = next => { state = next; onChange({ ...state }) }
  function collapse() { if (!disposed && state.phase !== 'hidden') publish({ ...state, phase: 'collapsed' }) }
  return {
    get state() { return { ...state } },
    setRecord(id) { if (!disposed && id !== recordId) { recordId = id; publish({ phase: seen.has(id) ? 'collapsed' : 'hidden', elapsed: 0, reducedMotion: false }) } },
    ended(seconds, reducedMotion = false) {
      if (disposed || !recordId || seen.has(recordId) || !(seconds > 0)) return false
      seen.add(recordId); publish({ phase: 'automatic', elapsed: 0, reducedMotion }); return true
    },
    open() { if (!disposed && recordId) publish({ phase: 'manual', elapsed: 0, reducedMotion: state.reducedMotion }) },
    collapse,
    interrupt() { if (state.phase === 'automatic') collapse() },
    dispose() { disposed = true },
  }
}
