import assert from 'node:assert/strict'
import test from 'node:test'
import { analysisDuration, analysisSeekTime, visualReplayState } from '../src/services/visualReplayPresentation.js'

const job = (visual = {}) => ({ video: { fps: 24, duration_seconds: 5 }, result: { visual_replay: {
  status: 'ready', analysis_duration_seconds: 5, tail_start_seconds: 5,
  tail_duration_seconds: 8, total_duration_seconds: 13, can_retry: true, ...visual,
} } })

test('尾段跳转与原动作时间分开，越界动作定位不能进入动画', () => {
  assert.equal(visualReplayState(job()).start, 5)
  assert.equal(visualReplayState(job()).ready, true)
  assert.equal(analysisDuration(job()), 5)
  assert.equal(analysisSeekTime(job(), 2.5), 2.5)
  assert.equal(analysisSeekTime(job(), 12), 5 - 1 / 24)
  assert.equal(analysisSeekTime(job(), -4), 0)
  assert.equal(analysisSeekTime(job(), NaN), 0)
})

test('失效尾段在排队、失败和再次重试中不可作为当前结果观看', () => {
  for (const status of ['stale', 'queued', 'running', 'failed', 'ready']) {
    const state = visualReplayState(job({ status, stale: true }))
    assert.equal(state.stale, true)
    assert.equal(state.ready, false)
    assert.equal(state.canRetry, !['queued', 'running'].includes(status))
  }
  assert.equal(visualReplayState(job({ status: 'running', previous_status: 'stale' })).stale, true)
})

test('制作失败仍说明基础视频可用，过期素材不能无限重试', () => {
  const failure = visualReplayState(job({ status: 'failed' }))
  assert.match(failure.message, /可重试.*基础复盘可继续观看/)
  assert.equal(failure.canRetry, true)
  const expired = visualReplayState(job({ status: 'failed', can_retry: false }))
  assert.equal(expired.canRetry, false)
  assert.match(expired.message, /所需素材已不可用/)
  assert.equal(visualReplayState({ result: {} }).visible, false)
  assert.equal(analysisDuration({ video: { duration_seconds: 7 } }), 7)
})
