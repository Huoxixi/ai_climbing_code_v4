const positive = value => {
  const number = Number(value)
  return Number.isFinite(number) && number > 0 ? number : null
}

export function analysisDuration(job) {
  return positive(job?.result?.visual_replay?.analysis_duration_seconds)
    ?? positive(job?.video?.duration_seconds)
    ?? positive(job?.result?.video?.duration_seconds)
}

export function analysisSeekTime(job, time) {
  const seconds = Number(time)
  const duration = analysisDuration(job)
  const fps = positive(job?.video?.fps ?? job?.result?.video?.fps) || 30
  return Math.max(0, Math.min(Number.isFinite(seconds) ? seconds : 0,
    duration === null ? Infinity : Math.max(0, duration - 1 / fps)))
}

export function visualReplayState(job) {
  const visual = job?.result?.visual_replay
  if (!visual) return { visible: false, ready: false, busy: false, stale: false, canRetry: false, start: null, message: '' }
  const busy = ['queued', 'running'].includes(visual.status)
  const stale = visual.stale === true || visual.needs_regeneration === true
    || visual.status === 'stale' || visual.previous_status === 'stale'
  const start = positive(visual.tail_start_seconds ?? visual.start_seconds)
  const ready = visual.status === 'ready' && !stale && start !== null
  const canRetry = visual.can_retry === true && !busy
  let message = ''
  if (busy) message = '正在制作线路回放，基础复盘可继续观看。'
  else if (stale) message = canRetry ? '用点记录已更新，请重新制作线路回放。' : '用点记录已更新；所需素材已不可用，仍可查看基础复盘。'
  else if (['failed', 'cancelled'].includes(visual.status)) message = canRetry
    ? '线路回放暂未生成，可重试。基础复盘可继续观看。'
    : '线路回放暂未生成，所需素材已不可用。基础复盘可继续观看。'
  else if (visual.status === 'unavailable') message = visual.message || '当前素材不足以制作线路回放，保留基础复盘。'
  return { visible: true, ready, busy, stale, canRetry, start, message }
}
