import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
const login = readFileSync(new URL('../src/components/PilotLogin.vue', import.meta.url), 'utf8')
const root = readFileSync(new URL('../src/RootApp.vue', import.meta.url), 'utf8')
const shell = readFileSync(new URL('../src/components/AppShell.vue', import.meta.url), 'utf8')
const settings = readFileSync(new URL('../src/components/SettingsPage.vue', import.meta.url), 'utf8')
test('注册登录入口移除旧试用身份且不预填密码', () => {
  assert.doesNotMatch(login, /ma-trial|deng-trial|马老师|邓老师/)
  assert.match(login, /邀请码/)
  assert.match(login, /确认密码/)
  assert.match(login, /new-password/)
  assert.doesNotMatch(login, /password:\s*['"][^'"]+/)
})
test('注册接入真实接口并在切换账号后重建个人工作区', () => {
  assert.match(root, /\/api\/auth\/register/)
  assert.match(root, /:key="session.username"/)
  assert.match(root, /registrationEnabled/)
})
test('登录失效返回登录页并保留退出入口', () => {
  assert.match(root, /\/api\/auth\/session/)
  assert.match(root, /\/api\/auth\/logout/)
  assert.match(root, /status === 401/)
})
test('登录和设置页使用攀岩助手响应式原型且保留服务入口', () => {
  assert.match(login, /登录攀岩助手/)
  assert.match(login, /login-climber-pexels-5916407\.jpg/)
  assert.match(login, /login-photo-fade/)
  assert.match(shell, /攀岩助手/)
  assert.match(shell, /close-settings/)
  assert.match(settings, /DeepSeek API/)
  assert.match(settings, /settings-grid/)
})
