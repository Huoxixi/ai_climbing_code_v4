import { clone } from './photoBoard.js'

export function createDraftAutosave({ save, onSaved, onState, persist, delay = 2000, schedule = setTimeout, unschedule = clearTimeout }) {
  let timer, pending = null, inFlight = null, blocked = false, allowed = true, generation = 0
  let version = 1, disposed = false
  function state(value, error) { if (!disposed) onState(value, error) }
  function arm() {
    unschedule(timer)
    if (!blocked && allowed && !disposed) timer = schedule(flush, delay)
  }
  async function flush() {
    unschedule(timer)
    if (inFlight) { await inFlight; return !blocked && pending && allowed ? flush() : undefined }
    if (!pending || blocked || !allowed || disposed) return
    const snapshot = clone(pending), currentGeneration = generation
    state('saving')
    inFlight = (async () => {
      try {
        const saved = await save(snapshot, version)
        version = saved.version
        if (currentGeneration === generation) { pending = null; persist(null); state('saved') }
        else { pending.version = version; persist(pending); state(allowed ? 'dirty' : 'lease'); arm() }
        if (!disposed) onSaved(saved, currentGeneration === generation)
      } catch (error) {
        const status = error?.response?.status
        blocked = status === 409 || status === 423 || status === 401
        state(status === 409 ? 'conflict' : status === 423 || status === 401 ? 'lease' : 'error', error)
      } finally { inFlight = null }
    })()
    return inFlight
  }
  return {
    get dirty() { return Boolean(pending) },
    reset(nextVersion) { version = nextVersion; pending = null; blocked = false; generation++; unschedule(timer); state('saved') },
    change(draft) { generation++; pending = clone(draft); pending.version = version; persist(pending); if (!blocked) state(allowed ? 'dirty' : 'lease'); arm() },
    setAllowed(value) { allowed = value; if (!allowed) { unschedule(timer); if (pending) state('lease') } },
    restore(draft, conflict = false) { pending = clone(draft); version = draft.version; blocked = conflict; persist(pending); state(conflict ? 'conflict' : allowed ? 'dirty' : 'lease'); if (!conflict) arm() },
    retry() { if (allowed) { blocked = false; return flush() } },
    flush,
    dispose() { disposed = true; unschedule(timer); if (pending) persist(pending) },
  }
}
