import test from 'node:test'
import assert from 'node:assert/strict'
import { segmentDecision, metricText } from '../src/services/actionPlayback.js'
const group = { start_seconds: 6.2, end_seconds: 8.8 }
test('native seeking outside either edge exits; an internal seek remains in segment', () => {
  assert.equal(segmentDecision(group, 5, { seeking: true }), 'exit')
  assert.equal(segmentDecision(group, 9, { seeking: true }), 'exit')
  assert.equal(segmentDecision(group, 7, { seeking: true }), 'segment')
})
test('segment finish pauses or repeats without a full-video end event', () => {
  assert.equal(segmentDecision(group, 8.8), 'pause')
  assert.equal(segmentDecision(group, 8.8, { loop: true }), 'repeat')
  assert.equal(segmentDecision(null, 8.8), 'full')
})
test('source duration remains approximate without adding playback or summary time', () => {
  assert.equal(metricText({ label: '视频记录时长', value: 14.26666, unit: '秒', approximate: true }), '视频记录时长 约 14.3 秒')
})
