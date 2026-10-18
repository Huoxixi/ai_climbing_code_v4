// One pass through the ending cards. Interaction stops it; hover/hidden pauses.
export function createReplayCardAutoplay({ current, advance, finish, delay = 6000,
  schedule = (fn, ms) => setTimeout(fn, ms), cancel = id => clearTimeout(id) }) {
  let timer, running = false, paused = false, disposed = false
  const clear = () => { if (timer !== undefined) cancel(timer); timer = undefined }
  function arm() {
    if (!running || paused || disposed || timer !== undefined) return
    timer = schedule(() => {
      timer = undefined
      if (!running || paused || disposed) return
      const { index, count } = current()
      if (index + 1 >= count) { running = false; finish() }
      else { advance(); arm() }
    }, delay)
  }
  return {
    start() { if (!disposed) { running = true; clear(); arm() } },
    stop() { running = false; clear() },
    pause(value) { paused = value; clear(); arm() },
    reset() { clear(); arm() },
    dispose() { disposed = true; running = false; clear() },
  }
}
