import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import { parse } from 'vue/compiler-sfc'
import { replayPageState } from './fixtures/replayPageState.mjs'

const page = readFileSync(new URL('../src/components/ClimbReplayPage.vue', import.meta.url), 'utf8')
const service = readFileSync(new URL('../src/services/climbReplayService.js', import.meta.url), 'utf8')

test('手机常见视频格式可选择并在上传前得到一致校验', () => {
  assert.match(page, /video\/quicktime/)
  assert.match(page, /\.mov/)
  assert.match(page, /\.m4v/)
  assert.match(page, /\.3gp/)
  assert.match(page, /\.mkv/)
  assert.match(page, /MP4 \/ MOV · 最大 500 MB/)
  assert.match(page, /请选择 MP4、MOV、M4V、WebM、3GP 或 MKV 视频/)
  assert.match(service, /video\.type \|\| 'application\/octet-stream'/)
})

test('服务器后台整理期间禁用重复提交并保留任务查询', () => {
  assert.match(page, /!isSubmitting\.value/)
  assert.match(page, /正在创建后台任务/)
  assert.match(page, /if \(previewUrl\.value\) URL\.revokeObjectURL\(previewUrl\.value\)\s+previewUrl\.value = ''\s+selectedFile\.value = null/)
  const { state, activeJob } = replayPageState({ media: { source_video: { status: 'available' } }, preparation: { status: 'running' } })
  assert.equal(state.sourceAvailable.value, true)
  assert.equal(state.sourcePlayable.value, false)
  activeJob.value.preparation.status = 'completed'
  assert.equal(state.sourcePlayable.value, true)
  assert.equal(state.statusDetail.value, '系统正在处理视频并识别动作；可以稍后在任务列表查看结果。')
  assert.match(service, /\/complete`\)/)
  assert.doesNotMatch(service.match(/complete: \(uploadId\)[^\n]*/)?.[0] || '', /timeout:180000/)
})

test('超长视频使用前90秒的简化流程，服务仍保留片段参数兼容', () => {
  // 2026-10-08《AI复盘_单一取色面板》移除视频设置，超长视频仅提示前90秒。
  const template = parse(page).descriptor.template.content
  assert.match(template, /本次分析前 90 秒/)
  assert.doesNotMatch(template, /v-model(?:\.number)?="trim(?:Start|End)Seconds"/)
  assert.match(page, /trimStartSeconds/)
  assert.match(page, /trimEndSeconds/)
  assert.match(page, /trimStartSeconds\.value = 0/)
  assert.match(page, /trimEndSeconds\.value = Math\.min\(MAX_VIDEO_SECONDS, videoMeta\.value\.duration\)/)
  assert.match(service, /trim_start_seconds/)
  assert.match(service, /trim_end_seconds/)
})
