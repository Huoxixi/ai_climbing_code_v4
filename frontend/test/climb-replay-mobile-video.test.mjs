import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const page = readFileSync(new URL('../src/components/ClimbReplayPage.vue', import.meta.url), 'utf8')
const service = readFileSync(new URL('../src/services/climbReplayService.js', import.meta.url), 'utf8')

test('手机常见视频格式可选择并在上传前得到一致校验', () => {
  assert.match(page, /video\/quicktime/)
  assert.match(page, /\.mov/)
  assert.match(page, /\.m4v/)
  assert.match(page, /\.3gp/)
  assert.match(page, /\.mkv/)
  assert.match(page, /MP4、MOV 等常见视频/)
  assert.match(page, /请选择 MP4、MOV、M4V、WebM、3GP 或 MKV 视频/)
  assert.match(service, /video\.type \|\| 'application\/octet-stream'/)
})

test('服务器转换期间禁用重复提交并使用长请求时限', () => {
  assert.match(page, /!isSubmitting\.value/)
  assert.match(page, /正在转换视频/)
  assert.match(service, /timeout:180000/)
})
