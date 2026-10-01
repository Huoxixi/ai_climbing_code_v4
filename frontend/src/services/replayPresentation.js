// Display timing is independent of source-time measurements.
export const SUMMARY_INTRO = .6
export const SUMMARY_STEP = .8
export const SUMMARY_HOLD = 3
const routeKeys = ['route_total','route_used','route_usage']
export const routeMetrics = metrics => metrics.filter(m => routeKeys.includes(m.key))
const chapterSeconds = count => count ? SUMMARY_INTRO + (count - 1) * SUMMARY_STEP + SUMMARY_HOLD : 0
export const routeSeconds = metrics => chapterSeconds(routeMetrics(metrics).length)
export const summaryMetrics = (metrics, motion) => metrics.filter(m => !routeKeys.includes(m.key) && (!motion || !['moving', 'relative_still'].includes(m.key)))
export const rhythmStart = (metrics, motion) => routeSeconds(metrics) + chapterSeconds(summaryMetrics(metrics, motion).length)
export const summarySeconds = (metrics, motion) => rhythmStart(metrics, motion) + (motion ? 6 : 0)
export const metricValue = metric => metric.display_value || (metric.value == null ? '尚未确认' : `${metric.approximate ? '约 ' : ''}${metric.approximate ? Number(metric.value).toFixed(1) : metric.value}`)
const limbs = { left_hand: '左手', right_hand: '右手', left_foot: '左脚', right_foot: '右脚' }
const legacyText = event => {
  const hand = event.limb.endsWith('hand')
  return { move_up: hand ? '向上伸手' : '抬脚', move: hand ? '伸手' : '移脚', adjust: hand ? '调整手部位置' : '调整脚部位置' }[event.action]
}

// This changes only display wording. Evidence, captions, and source times stay intact.
export function shortActionLabel(event, time = event?.start_seconds) {
  if (!event) return '动作待复核'
  const confirmed = event.event_status === 'human_confirmed' || event.evidence_status === 'human_confirmed'
  const poseOnly = !confirmed && (event.evidence_status === 'trajectory_observed' || event.event_status === 'trajectory_observed')
  if (poseOnly && event.trajectory_details?.status !== 'observed') return '动作待复核'
  if (!confirmed && !poseOnly && event.evidence_status !== 'locally_verified') return '动作待复核'
  const phase = poseOnly && event.trajectory_details?.phases?.findLast(p => p.start_seconds <= time && time <= p.end_seconds)
  const part = event.caption_parts?.findLast(p => p.start_seconds <= time)
  let text = phase?.text || part?.text || event.text || event.display_name || legacyText({ ...event, limb: event.limbCode || event.limb || '' }) || ''
  if (/待复核|证据不足|连续性冲突|不能确定|无法可靠分离/.test(text)) return '动作待复核'
  const trajectory = event.trajectory_details
  const directions = { up: '向上', down: '向下', left: '向左', right: '向右', up_left: '向左上方', up_right: '向右上方', down_left: '向左下方', down_right: '向右下方' }
  const wallPrefix = /^墙面参考中(向(?:[左右][上下]方|[上下左右]))移位；/
  const wallFromSummary = trajectory?.summary?.match(wallPrefix)?.[1] || part?.text?.match(wallPrefix)?.[1] || text.match(wallPrefix)?.[1]
  const wallDirection = directions[trajectory?.wall_direction] || wallFromSummary
  const motionText = text.startsWith('墙面参考中') ? text.split('；').slice(1).join('；') : text
  const writtenDirection = motionText.match(/向(?:[左右][上下]方|[上下左右])/)?.[0]
  if (!confirmed && trajectory?.status === 'observed' && writtenDirection) {
    // A torso-relative direction must not be relabeled as a direction on the wall.
    if (directions[trajectory.wall_direction] && wallFromSummary && directions[trajectory.wall_direction] !== wallFromSummary) return '动作待复核'
    if (Object.hasOwn(trajectory, 'wall_direction') && !directions[trajectory.wall_direction]) return '动作待复核'
    if (wallDirection && writtenDirection !== wallDirection && (wallFromSummary || directions[trajectory.direction] && trajectory.wall_direction !== trajectory.direction)) {
      const limb = event.limbCode || event.limb
      if (!limbs[limb]) return '动作待复核'
      const joint = text.match(/手臂伸展|手臂屈曲|伸展手臂|膝部伸展|伸展膝部|屈膝/)?.[0]
      text = wallDirection + (limb.endsWith('hand') ? '移手' : '移脚') + (joint ? `，${joint}` : '')
    }
  }
  text = text
    .replace(/^墙面参考中[^；]*；\s*/, '')
    .replace(/^扣除躯干共同旋转后[，,]\s*/, '')
    .replace(/相对(?:肩部|髋部|躯干|肩|髋)(?:的)?/g, '')
    .replace(/[（(][^）)]*二维骨架观察[）)]/g, '')
    .replace(/[（(]人工确认[）)]/g, '')
    .replace(/^(?:左手|右手|左脚|右脚)/, '')
    .replace(/[，,；;]\s*接触(?:仍)?未确认/g, '')
    .replace(/ · .*/, '')
    .replace(/^末端位置暂未明显变化$/, '肢体暂稳')
    .replace(/^末端位置趋于稳定$/, '肢体趋稳')
    .replace(/^末端位置变化继续$/, '继续移动')
    .trim()
  return text || '动作待复核'
}

export function currentCaptions(groups, time) {
  const timeline = groups.flatMap((group, index) => (group.events || [])
    .filter(e => ['locally_verified', 'human_confirmed', 'trajectory_observed'].includes(e.evidence_status) && limbs[e.limb])
    .map(event => ({ ...event, groupIndex: index, groupId: group.id })))
    .sort((a, b) => a.start_seconds - b.start_seconds)
  return timeline.flatMap(event => {
    const next = Math.min(...timeline.filter(e => e.limb === event.limb && e.start_seconds > event.start_seconds).map(e => e.start_seconds))
    const nextAfter = Math.min(...timeline.filter(e => e.start_seconds > event.start_seconds && e.start_seconds >= event.end_seconds).map(e => e.start_seconds))
    const tail = timeline.some(e => e !== event && e.start_seconds < event.end_seconds && e.end_seconds > event.end_seconds) ? event.end_seconds : event.end_seconds + .55
    if (!(time >= event.start_seconds && time < Math.min(tail, next, nextAfter))) return []
    const part = event.caption_parts?.findLast(p => p.start_seconds <= time)
    let text = part?.text || legacyText(event)
    if (!text) return []
    const relation = event.relations?.find(r => r.status !== 'candidate' && r.code !== 'SIMULTANEOUS' && r.start_seconds <= time && time <= r.end_seconds + .55)
    if (relation) text += ` · ${relation.name}`
    return [{ ...event, key: `${event.id || event.groupId}-${event.start_seconds}-${event.limb}-${part?.start_seconds ?? 0}`, limbCode: event.limb, limb: limbs[event.limb], text }]
  })
}

export function currentExplanation(groups, time) {
  const entries = currentCaptions(groups, time)
  if (!entries.length) return null
  return { ...entries[0], key: entries.map(e => e.key).join('|'), entries,
    limb: entries.map(e => e.limb).join(' · '), text: entries.map(e => e.text).join('；'),
    start_seconds: Math.min(...entries.map(e => e.start_seconds)), end_seconds: Math.max(...entries.map(e => e.end_seconds)) }
}
