import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const page = readFileSync(new URL('../src/components/ClimbReplayPage.vue', import.meta.url), 'utf8')
const service = readFileSync(new URL('../src/services/climbReplayService.js', import.meta.url), 'utf8')

test('AI 复盘从服务端读取告知版本并随上传提交明确同意', () => {
  assert.match(service, /\/api\/climb-replay\/consent-policy/)
  assert.match(service, /consent_version:consentVersion/)
  assert.match(service, /consent_granted:consentGranted/)
  assert.match(page, /consentVersion: consentPolicy\.value\.version/)
  assert.match(page, /重试时需要重新同意/)
})

test('AI 复盘重试要求新授权并提供服务端撤回入口', () => {
  assert.match(service, /\/consent\/withdraw/)
  assert.match(service, /consent_granted:true/)
  assert.match(page, /sampleConsent\.value = false/)
  assert.match(page, /撤回本次授权/)
  assert.match(page, /重新分析会再次发送抽样画面/)
})
