import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import { parse } from 'vue/compiler-sfc'
import { replayPageState } from './fixtures/replayPageState.mjs'

const page = readFileSync(new URL('../src/components/ClimbReplayPage.vue', import.meta.url), 'utf8')
const service = readFileSync(new URL('../src/services/climbReplayService.js', import.meta.url), 'utf8')

test('测试素材入口退出用户模板，历史对照视频服务仍保持兼容', () => {
  // 2026-10-09《AI复盘_模块修正与验收》明确移除测试素材入口。
  const template = parse(page).descriptor.template.content
  assert.match(service, /\/api\/climb-replay\/test-videos/)
  assert.doesNotMatch(template, /testVideoCases|useTestVideo|本地测试案例|samplesOpen/)
  const { state, testVideoCases } = replayPageState({ id: 'saved', status: 'succeeded', original_name: 'wall.mp4', route_color: '黄色' })
  testVideoCases.value = [{ id: 'case', comparison_available: true, filename: 'wall.mp4', comparison_route_color: '黄色', comparison_action_count: 0 }]
  assert.equal(state.replayVideoUrl.value, 'case/comparison')
  assert.match(service, /test-videos\/\$\{encodeURIComponent\(caseId\)\}\/comparison/)
})

test('测试视频复用正式上传校验且不自动同意第三方处理', () => {
  assert.match(page, /useFile\(new File/)
  assert.match(page, /请从画面取色后点击上传并识别岩点/)
  assert.doesNotMatch(page, /useTestVideo[\s\S]{0,800}consentGranted: true/)
})
