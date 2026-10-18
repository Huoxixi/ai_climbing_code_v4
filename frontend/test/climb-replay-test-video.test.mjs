import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const page = readFileSync(new URL('../src/components/ClimbReplayPage.vue', import.meta.url), 'utf8')
const service = readFileSync(new URL('../src/services/climbReplayService.js', import.meta.url), 'utf8')

test('本机存在三个测试案例时在 AI 复盘旁显示选择入口', () => {
  assert.match(service, /\/api\/climb-replay\/test-videos/)
  assert.match(page, /testVideoCases\.length/)
  assert.match(page, /v-for="item in testVideoCases\.slice\(samplePage\*4,\(samplePage\+1\)\*4\)"/)
  assert.match(page, /本地测试案例/)
  assert.match(page, /不会随生产发布/)
})

test('测试视频复用正式上传校验且不自动同意第三方处理', () => {
  assert.match(page, /useFile\(new File/)
  assert.match(page, /请从画面取色后点击上传并识别岩点/)
  assert.doesNotMatch(page, /useTestVideo[\s\S]{0,800}consentGranted: true/)
})
