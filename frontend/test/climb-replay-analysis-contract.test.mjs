import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import { ref } from 'vue'
import { parse, compileScript, compileTemplate } from 'vue/compiler-sfc'
import { useReplayJobState } from '../src/composables/useReplayPageState.js'

const pages = ['ClimbReplayPage.vue', 'LocalClimbReplayPage.vue'].map(name => {
  const source = readFileSync(new URL(`../src/components/${name}`, import.meta.url), 'utf8')
  return { name, ...parse(source) }
})

test('AI 复盘仍按当前尝试读取成功与失败证据，旧尝试不能覆盖当前结果', () => {
  for (const { name, descriptor } of pages) {
    const { bindings } = compileScript(descriptor, { id: name })
    assert.ok(bindings.currentRun && bindings.analysisEvidence, name)
    assert.match(descriptor.scriptSetup.content, /useReplayJobState\(\{ activeJob, deletionReceipt, uploadProgress, limbNames \}\)/)
    const activeJob = ref({ attempt: 2, analysis_runs: [
      { attempt: 1, analysis: { marker: 'old' } },
      { attempt: 2, analysis: { marker: 'failed-current', usage: { failed_requests: 1 } } },
    ] })
    const { analysisEvidence: evidence } = useReplayJobState({ activeJob, deletionReceipt: ref(null), uploadProgress: ref(0), limbNames: {} })
    assert.equal(evidence.value.marker, 'failed-current', name)
    activeJob.value.result = { analysis: { marker: 'success', usage: { successful_pose_frames: 2 } } }
    assert.equal(evidence.value.marker, 'success', name)
    activeJob.value.result = null
    activeJob.value.attempt = 3
    assert.equal(evidence.value, null, name)
  }
})

test('用户流程隐藏已退役的处理诊断与费用表，保留播放器和任务状态', () => {
  // 2026-10-09《AI复盘_模块修正与验收》：诊断和实验信息不再放进产品流程。
  for (const { name, descriptor, errors } of pages) {
    assert.deepEqual(errors, [], name)
    assert.deepEqual(compileTemplate({ source: descriptor.template.content, filename: name, id: name }).errors, [], name)
    assert.doesNotMatch(descriptor.template.content, /处理记录与费用估算|successful_pose_frames|failed_requests|unprocessed_frames|pipeline_version|api_version|analysisCost|analysisTimings/)
    assert.match(descriptor.template.content, /<UnifiedReplayPlayer/)
    assert.match(descriptor.template.content, /class="analysis-state"/)
  }
})
