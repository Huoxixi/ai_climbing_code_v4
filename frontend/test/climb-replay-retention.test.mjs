import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const page = readFileSync(new URL('../src/components/ClimbReplayPage.vue', import.meta.url), 'utf8')
const service = readFileSync(new URL('../src/services/climbReplayService.js', import.meta.url), 'utf8')

test('上传默认选择自动清理并把保留方式提交给服务端', () => {
  assert.match(page, /retentionMode = ref\('delete_after_processing'\)/)
  assert.match(page, /成功后 24 小时内删除；失败或取消后保留 72 小时/)
  assert.match(page, /私密保留原视频/)
  assert.match(service, /retention_mode:retentionMode/)
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
