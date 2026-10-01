// Source seconds throughout. Segment boundaries never depend on playback speed.
export function segmentDecision(group, time, { seeking = false, loop = false } = {}) {
  if (!group) return 'full'
  if (seeking && (time < group.start_seconds - .02 || time > group.end_seconds + .02)) return 'exit'
  if (!seeking && time >= group.end_seconds - .015) return loop ? 'repeat' : 'pause'
  return 'segment'
}

export function metricText(metric) {
  const value = metric.approximate ? Number(metric.value).toFixed(1) : metric.value
  return `${metric.label} ${metric.approximate ? '约 ' : ''}${value} ${metric.unit}`
}
