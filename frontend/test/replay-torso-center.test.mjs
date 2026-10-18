import test from 'node:test'
import assert from 'node:assert/strict'
import { torsoCenter, torsoCenterTimeline, torsoDisplayFrame } from '../src/services/replayTorsoCenter.js'

function pose(frame, x = .5) {
  const sample = { observed: true, source_frame_id: frame, kpts_xy: Array.from({ length: 17 }, () => [0, 0]), kpts_score: Array(17).fill(0) }
  for (const [index, dx, y] of [[5, -.1, .2], [6, .1, .2], [11, -.1, .6], [12, .1, .6]]) {
    sample.kpts_xy[index] = [x + dx, y]; sample.kpts_score[index] = .9
  }
  return sample
}

test('躯干中心只使用至少三个可靠肩髋点，缺测和无效坐标不显示', () => {
  const sample = pose(0)
  assert.deepEqual(torsoCenter(sample), [.5, .4])
  sample.kpts_score[5] = .1
  const center = torsoCenter(sample)
  assert.ok(Math.abs(center[0] - 1.6 / 3) < 1e-9)
  sample.kpts_xy[6] = [NaN, .2]
  assert.equal(torsoCenter(sample), null)
  assert.equal(torsoCenter({ ...pose(0), observed: false }), null)
  for (const value of [0, 1, Infinity, null, '0.4']) {
    const bad = pose(0); bad.kpts_xy[5] = [value, .2]; bad.kpts_score[6] = .49
    assert.equal(torsoCenter(bad), null)
  }
})

test('中心点跟随已有骨架的帧间平滑，长时间缺测后隐藏', () => {
  const samples = [pose(0, .3), pose(4, .5), { source_frame_id: 8, observed: false }, { source_frame_id: 12, observed: false }, pose(16, .7)]
  const timeline = torsoCenterTimeline(samples, 26)
  assert.ok(Math.abs(timeline.get(2)[0] - .4) < 1e-9)
  assert.equal(timeline.get(10), undefined)
  assert.ok(Math.abs(timeline.get(16)[0] - .7) < 1e-9)
  assert.equal(timeline.get(24), undefined)
  const occluded = pose(4); occluded.kpts_score[5] = occluded.kpts_score[6] = 0
  assert.equal(torsoCenterTimeline([pose(0), occluded], 8).get(4), null)
})

test('中心点正确映射到左右复盘的真人区域，未知布局与已烧录版本不叠画', () => {
  const result = { video: { width: 400, height: 300 }, overlay: { layout: 'split_route_map_actions_v8', width: 400, height: 300, action_count: 1 } }
  assert.deepEqual(torsoDisplayFrame(result, true), { width: 400, height: 300, rect: [0, 27, 256, 192] })
  assert.deepEqual(torsoDisplayFrame(result, false).rect, [0, 0, 400, 300])
  assert.equal(torsoDisplayFrame({ ...result, overlay: { ...result.overlay, torso_center: 'v1' } }, true), null)
  assert.equal(torsoDisplayFrame({ ...result, overlay: { ...result.overlay, layout: 'unknown' } }, true), null)
})
