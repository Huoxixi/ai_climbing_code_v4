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

test('服务器后台整理期间禁用重复提交并保留任务查询', () => {
  assert.match(page, /!isSubmitting\.value/)
  assert.match(page, /正在创建后台任务/)
  assert.match(page, /if \(previewUrl\.value\) URL\.revokeObjectURL\(previewUrl\.value\)\s+previewUrl\.value = ''\s+selectedFile\.value = null/)
  assert.match(page, /const sourcePlayable = computed\(\(\) => sourceAvailable\.value &&/)
  assert.match(page, /activeJob\.value\.preparation\.status === 'completed'/)
  assert.match(page, /可以稍后在任务列表查看结果/)
  assert.match(service, /\/complete`\)/)
  assert.doesNotMatch(service.match(/complete: \(uploadId\)[^\n]*/)?.[0] || '', /timeout:180000/)
})

test('超长视频可以在页面内选择分析片段，超分辨率由服务端生成分析副本', () => {
  assert.match(page, /默认分析前 90 秒，也可以在这里调整片段/)
  assert.match(page, /trimStartSeconds/)
  assert.match(page, /trimEndSeconds/)
  assert.match(page, /手机里的原文件不会修改/)
  assert.match(page, /上传的仍是完整文件/)
  assert.match(service, /trim_start_seconds/)
  assert.match(service, /trim_end_seconds/)
})
