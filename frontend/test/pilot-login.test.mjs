import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const loginSource = readFileSync(new URL('../src/components/PilotLogin.vue', import.meta.url), 'utf8')
const rootSource = readFileSync(new URL('../src/RootApp.vue', import.meta.url), 'utf8')

test('登录页只公开两位老师的用户名，不公开或预填密码', () => {
  assert.match(loginSource, /马老师试用账号/)
  assert.match(loginSource, /邓老师试用账号/)
  assert.match(loginSource, /ma-trial/)
  assert.match(loginSource, /deng-trial/)
  assert.match(loginSource, /密码请向负责人获取/)
  assert.match(loginSource, /复制用户名/)
  assert.match(loginSource, /navigator\.clipboard\.writeText/)
  assert.doesNotMatch(loginSource, /owner.*试用账号/)
  assert.doesNotMatch(loginSource, /password:\s*['"][^'"]+/)
})

test('根界面在会话失效后返回登录页并维护编辑权心跳', () => {
  assert.match(rootSource, /\/api\/auth\/session/)
  assert.match(rootSource, /\/api\/auth\/logout/)
  assert.match(rootSource, /\/api\/pilot\/edit-lease\/heartbeat/)
  assert.match(rootSource, /setInterval\(heartbeat,\s*30_000\)/)
  assert.match(rootSource, /status === 401/)
  assert.match(rootSource, /status === 423/)
})
