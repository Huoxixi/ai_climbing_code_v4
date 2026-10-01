import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const page = readFileSync(new URL('../src/components/ClimbReplayPage.vue', import.meta.url), 'utf8')

test('AI 复盘同时读取成功结果和失败尝试中的计量证据', () => {
  assert.match(page, /result\.value\?\.analysis \|\| currentRun\.value\?\.analysis/)
  assert.match(page, /analysis_runs/)
  assert.match(page, /successful_pose_frames/)
  assert.match(page, /failed_requests/)
  assert.match(page, /unprocessed_frames/)
})

test('处理记录展示版本、采样、费用依据和耗时而不包装成真实账单', () => {
  assert.match(page, /处理记录与费用估算/)
  assert.match(page, /pipeline_version/)
  assert.match(page, /api_version/)
  assert.match(page, /formatCost\(analysisCost\.estimated_amount\)/)
  assert.match(page, /analysisCost\.basis/)
  assert.match(page, /formatDuration\(analysisTimings\.pose\)/)
  assert.match(page, /formatDuration\(analysisTimings\.overlay\)/)
})
