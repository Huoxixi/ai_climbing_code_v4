import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const page = readFileSync(new URL('../src/components/ClimbReplayPage.vue', import.meta.url), 'utf8')
const service = readFileSync(new URL('../src/services/climbReplayService.js', import.meta.url), 'utf8')

test('上传固定保留原片，旧自动清理选项与倒计时退出页面', () => {
  assert.match(page, /retentionMode = ref\('keep_private_original'\)/)
  assert.doesNotMatch(page, /分析后自动删除|计划于.*自动删除|成功后 24 小时内删除/)
  assert.match(page, /原片与清晰播放副本保存在本机/)
  assert.match(service, /retention_mode:'keep_private_original'/)
})

test('原视频删除与整次记录删除使用不同接口并说明影响', () => {
  assert.match(service, /\/media\/source-video/)
  assert.match(service, /apiClient\.delete\(`\/api\/climb-replay\/jobs\/\$\{id\}`\)/)
  assert.match(page, /永久删除原视频，保留复盘指标/)
  assert.match(page, /永久删除原视频、姿态、事件、指标和派生文件/)
  assert.match(page, /此操作不可恢复/)
})

test('整次删除轮询独立回执且删除期间阻止重复提交', () => {
  assert.match(service, /\/api\/climb-replay\/deletions\/\$\{id\}/)
  assert.match(page, /scheduleDeletionPoll/)
  assert.match(page, /deletionReceipt\.value\.state === 'queued'/)
  assert.match(page, /:disabled="isDeleting \|\| isJobDeleting"/)
  assert.match(page, /删除回执已生成/)
})
