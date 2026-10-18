import test from 'node:test'
import assert from 'node:assert/strict'
import { replayFrameGeometry, projectPoint, referenceToFrame } from '../src/services/replayFrameGeometry.js'
const result = { video: { width: 640, height: 960 }, overlay: { width: 1000, height: 800, layout: 'split_route_map_actions_v8', action_count: 18 },
  holds: [{ bbox: [.3,.1,.2,.1] }, { bbox: [.6,.7,.1,.1] }] }
test('old baked action strip is excluded while video and route keep the same source geometry', () => {
  const f = replayFrameGeometry(result)
  assert.equal(f.height, 960)
  assert.equal(f.width, 1280)
  assert.deepEqual(f.video,[0,0,640,960])
  assert.deepEqual(f.panel,[640,0,640,960])
  assert.ok(f.video[0]+f.video[2] <= 640)
  assert.ok(Math.abs(f.video[2]/f.video[3] - 640/960) < .002)
  const mapped = projectPoint([.3,.1],f.map)
  assert.ok(mapped[0] >= f.mapClip[0] && mapped[0] <= f.mapClip[0]+f.mapClip[2])
  assert.ok(mapped[1] >= f.mapClip[1] && mapped[1] <= f.mapClip[1]+f.mapClip[3])
  assert.equal(replayFrameGeometry({ ...result, overlay: { ...result.overlay, layout:'unknown' } }),null)
})
test('saved v9 video is cropped without rewriting media, route uses matching source scale', () => {
  const f = replayFrameGeometry({ ...result,overlay:{ width:1000,height:800,layout:'split_route_map_stats_v9',route_map_rect:[500,-100,700,1050],video_rect:[83,0,533,800] } })
  assert.equal(f.height,960)
  assert.deepEqual(f.oldVideo,[83,0,533,800])
  assert.deepEqual(f.map,[640,0,640,960])
})
test('unused holds invert camera translation and perspective back into the real frame', () => {
  const source={width:640,height:960}
  assert.deepEqual(referenceToFrame([.5,.4],[[1,0,-64],[0,1,0],[0,0,1]],source),[.6,.4])
  assert.equal(referenceToFrame([.5,.4],[[0,0,0],[0,0,0],[0,0,0]],source),null)
  assert.equal(referenceToFrame([.5,.4],null,source),null)
})

