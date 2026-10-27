import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import { poseVersionLabel } from '../src/services/replayPageLabels.js'

const page = readFileSync(new URL('../src/components/ClimbReplayPage.vue', import.meta.url), 'utf8')
const service = readFileSync(new URL('../src/services/climbReplayService.js', import.meta.url), 'utf8')

test('AI 复盘点击上传时提交当前本地处理版本，无额外授权页', () => {
  assert.match(service, /\/api\/climb-replay\/consent-policy/)
  assert.match(service, /consent_version:consentVersion/)
  assert.match(service, /consent_granted:consentGranted/)
  assert.match(page, /consentVersion: consentPolicy\.value\.version/)
  assert.match(page, /consentGranted: true/)
  assert.doesNotMatch(page, /sampleConsent|保留与授权|视频设置|consent-shortcut/)
})

test('AI 复盘确认岩点后有独立开始入口，阿里云仅作历史版本兼容', () => {
  assert.match(service, /\/consent\/withdraw/)
  assert.match(service, /consent_granted:true/)
  assert.doesNotMatch(page, /paidSampleConsent|开始付费分析|阿里云付费接口/)
  assert.match(page, /@click="startAnalysis\(false\)">开始复盘/)
  assert.match(page, /climbReplayService\.startAnalysis\(jobId, consentPolicy\.value\.version/)
  assert.match(page, /poseVersionLabel\(result\)/)
  assert.equal(poseVersionLabel({ models: { pose: 'aliyun-viapi-old' } }), '阿里云骨架 · 历史版本')
  assert.match(service, /\/analysis\/start/)
})
