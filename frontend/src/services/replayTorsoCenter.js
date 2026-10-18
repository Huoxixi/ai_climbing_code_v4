// Display coordinates only: the shoulder/hip mean is not a center of mass.
const torsoJoints = [5, 6, 11, 12]
export function torsoCenter(sample) {
  if (!sample || sample.observed === false) return null
  const valid = torsoJoints.map(index => ({ point: sample.kpts_xy?.[index], score: sample.kpts_score?.[index] }))
    .filter(({ point, score }) => Array.isArray(point) && point.length === 2 && point.every(Number.isFinite)
      && Number.isFinite(score) && score >= .5 && score <= 1 && point.every(value => value > 0 && value < 1))
  if (valid.length < 3) return null
  return [0, 1].map(axis => valid.reduce((sum, { point }) => sum + point[axis], 0) / valid.length)
}

// Match build_pose_render_timeline so the dot follows the skeleton already in old movies.
const round = value => value % 1 === .5 ? 2 * Math.round(value / 2) : Math.round(value)
export function torsoCenterTimeline(samples = [], totalFrames = 0) {
  if (!Array.isArray(samples) || !(totalFrames > 0)) return new Map()
  const frames = [...new Set(samples.map(sample => sample.source_frame_id)
    .filter(frame => Number.isInteger(frame) && frame >= 0 && frame < totalFrames))].sort((a, b) => a - b)
  const gaps = frames.slice(1).map((frame, index) => frame - frames[index]).sort((a, b) => a - b)
  const middle = Math.floor(gaps.length / 2)
  const median = gaps.length ? (gaps[middle] + gaps[Math.floor((gaps.length - 1) / 2)]) / 2 : 1
  const maxGap = Math.max(1, round(median * 1.75))
  const frameSet = new Set(frames)
  const observed = samples.filter(sample => sample.observed && frameSet.has(sample.source_frame_id))
    .sort((a, b) => a.source_frame_id - b.source_frame_id)
  const timeline = new Map(observed.map(sample => [sample.source_frame_id, torsoCenter(sample)]))
  for (let index = 1; index < observed.length; index++) {
    const left = observed[index - 1], right = observed[index]
    const gap = right.source_frame_id - left.source_frame_id
    if (gap <= 1 || gap > maxGap) continue
    for (let frame = left.source_frame_id + 1; frame < right.source_frame_id; frame++) {
      const alpha = (frame - left.source_frame_id) / gap
      const pose = { kpts_xy: [], kpts_score: [] }
      for (const joint of torsoJoints) {
        const a = left.kpts_xy?.[joint], b = right.kpts_xy?.[joint]
        const sa = left.kpts_score?.[joint] || 0, sb = right.kpts_score?.[joint] || 0
        if (a && b && sa >= .15 && sb >= .15) {
          pose.kpts_xy[joint] = [0, 1].map(axis => Math.round((a[axis] * (1 - alpha) + b[axis] * alpha) * 1e6) / 1e6)
          pose.kpts_score[joint] = Math.round((sa * (1 - alpha) + sb * alpha) * 1e6) / 1e6
        } else if (a && b && (sa >= .15 || sb >= .15)) {
          pose.kpts_xy[joint] = sa >= .15 ? a : b
          pose.kpts_score[joint] = Math.round((sa >= .15 ? sa * (1 - alpha) : sb * alpha) * 1e6) / 1e6
        }
      }
      timeline.set(frame, torsoCenter(pose))
    }
  }
  if (observed.length) {
    const first = observed[0], last = observed.at(-1)
    for (let frame = Math.max(0, first.source_frame_id - maxGap); frame < first.source_frame_id; frame++) timeline.set(frame, torsoCenter(first))
    for (let frame = last.source_frame_id + 1; frame < Math.min(totalFrames, last.source_frame_id + maxGap + 1); frame++) timeline.set(frame, torsoCenter(last))
  }
  return timeline
}

export function torsoDisplayFrame(result, hasBaseVideo) {
  const source = result?.video || {}, overlay = result?.overlay || {}
  if (!(source.width > 0 && source.height > 0)) return null
  if (!hasBaseVideo) return { width: source.width, height: source.height, rect: [0, 0, source.width, source.height] }
  // New movies already contain the dot. Unknown historic layouts must not be guessed.
  if (overlay.torso_center || overlay.layout !== 'split_route_map_actions_v8' || !(overlay.width > 0 && overlay.height > 0)) return null
  const { width, height } = overlay
  const count = overlay.action_count || 0
  const columns = count ? Math.min(Math.max(1, count), Math.max(5, Math.min(10, Math.floor(width / 110)))) : 1
  const rows = Math.max(1, Math.ceil(count / columns))
  const strip = count ? Math.max(54, round(height * Math.min(.28, .075 + .065 * rows))) : Math.max(42, round(height * .10))
  const content = Math.max(2, height - strip), pane = Math.max(2, round(width * .64))
  const scale = Math.min(pane / source.width, content / source.height)
  const w = Math.max(1, round(source.width * scale)), h = Math.max(1, round(source.height * scale))
  return { width, height, rect: overlay.video_rect || [Math.max(0, Math.floor((pane - w) / 2)), Math.max(0, Math.floor((content - h) / 2)), w, h] }
}
