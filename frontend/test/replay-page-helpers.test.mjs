import assert from 'node:assert/strict'
import test from 'node:test'
import { inspectVideo } from '../src/services/replayVideoMetadata.js'
import * as helpers from '../src/services/replayPageLabels.js'

test('replay labels preserve public error priority and fallback text', () => {
  assert.equal(helpers.errorText({ response: { status: 404, data: { detail: 'ignored' } }, message: 'ignored' }), '本地复盘服务尚未启用，请重新启动本地服务。')
  assert.equal(helpers.errorText({ response: { data: { detail: '当前任务已删除' } }, message: 'ignored' }), '当前任务已删除')
  assert.equal(helpers.errorText(new Error('连接中断')), '连接中断')
  assert.equal(helpers.errorText(null), '操作失败，请稍后重试。')
})

test('replay labels distinguish local pose, historical cloud pose and missing versions', () => {
  assert.equal(helpers.poseVersionLabel({ models: { pose: 'rtmw-l-384x288-v1' } }), 'RTMW-L · 本地骨架')
  assert.equal(helpers.poseVersionLabel({ models: { pose: { name: 'aliyun-viapi-old' } } }), '阿里云骨架 · 历史版本')
  assert.equal(helpers.poseVersionLabel({ analysis: { models: { pose: { name: 'aliyun-viapi-old' } } } }), '阿里云骨架 · 历史版本')
  assert.equal(helpers.poseVersionLabel({ models: { pose: 'other-saved-model' } }), '历史骨架版本')
  assert.equal(helpers.poseVersionLabel(null), '待使用 RTMW-L 分析')
})

test('replay clocks retain tenth-second display and negative input handling', () => {
  assert.equal(helpers.formatClock(61.25), '1:01.2')
  assert.equal(helpers.formatClock('120.5'), '2:00.5')
  assert.equal(helpers.formatClock(-1), '0:00.0')
  assert.equal(helpers.formatClock(null), '0:00.0')
})

test('replay history labels preserve deletion priority and unknown status', () => {
  for (const [status, expected] of [['queued', '排队中'], ['running', '处理中'], ['awaiting_hold_review', '待确认岩点'], ['succeeded', '已完成'], ['failed', '失败'], ['cancelled', '已取消'], ['legacy-status', 'legacy-status']]) {
    assert.equal(helpers.jobStatusLabel({ status }), expected)
  }
  assert.equal(helpers.jobStatusLabel({ status: 'succeeded', deletion: { state: 'queued' } }), '删除中')
})

test('replay dates keep local Chinese calendar display and invalid-date errors', () => {
  assert.equal(helpers.dateLabel(new Date(2026, 0, 2, 3, 4).toISOString()), '1/2 03:04')
  assert.equal(helpers.dateLabel(''), '')
  assert.throws(() => helpers.dateLabel('invalid-date'), RangeError)
})

async function withMetadataEnvironment(mode, metadata, run) {
  const calls = [], url = 'blob:constructed-metadata'
  let timeout
  const probe = { ...metadata,
    removeAttribute: name => calls.push(['remove', name]),
    load: () => calls.push(['load']),
  }
  Object.defineProperty(probe, 'src', { set(value) {
    calls.push(['src', value])
    queueMicrotask(() => mode === 'timeout' ? timeout() : mode === 'error' ? probe.onerror() : probe.onloadedmetadata())
  } })
  const replacements = [
    [globalThis, 'document', { createElement: tag => { assert.equal(tag, 'video'); return probe } }],
    [globalThis, 'window', {
      setTimeout: (callback, milliseconds) => { assert.equal(milliseconds, 8000); timeout = callback; return 27 },
      clearTimeout: id => calls.push(['clear', id]),
    }],
    [URL, 'createObjectURL', file => { calls.push(['create', file]); return url }],
    [URL, 'revokeObjectURL', value => calls.push(['revoke', value])],
  ]
  const originals = replacements.map(([owner, key]) => Object.getOwnPropertyDescriptor(owner, key))
  try {
    for (const [owner, key, value] of replacements) Object.defineProperty(owner, key, { configurable: true, writable: true, value })
    await run({ calls, probe, url })
    assert.equal(probe.onloadedmetadata, null)
    assert.equal(probe.onerror, null)
    assert.deepEqual(calls.slice(-4), [['clear', 27], ['remove', 'src'], ['load'], ['revoke', url]])
  } finally {
    replacements.forEach(([owner, key], index) => originals[index] ? Object.defineProperty(owner, key, originals[index]) : delete owner[key])
  }
}

test('video metadata success returns measured dimensions and releases the probe', async () => {
  await withMetadataEnvironment('success', { videoWidth: 1920, videoHeight: 1080, duration: 12.5 }, async ({ calls, probe, url }) => {
    const file = new Blob(['constructed video'])
    assert.deepEqual(await inspectVideo(file), { width: 1920, height: 1080, duration: 12.5 })
    assert.deepEqual(calls[0], ['create', file])
    assert.ok(calls.some(call => call[0] === 'src' && call[1] === url))
    assert.equal(probe.preload, 'metadata')
  })
})

for (const [name, mode, metadata, message] of [
  ['codec error', 'error', {}, '浏览器无法预览此视频编码'],
  ['eight-second timeout', 'timeout', {}, '视频信息读取超时'],
  ['zero dimensions', 'success', { videoWidth: 0, videoHeight: 1080, duration: 12 }, '无法读取视频尺寸或时长，请重新选择文件。'],
  ['non-finite duration', 'success', { videoWidth: 1920, videoHeight: 1080, duration: Infinity }, '无法读取视频尺寸或时长，请重新选择文件。'],
]) test(`video metadata ${name} preserves the error and releases resources`, async () => {
  await withMetadataEnvironment(mode, metadata, async () => {
    await assert.rejects(inspectVideo(new Blob(['constructed video'])), { message })
  })
})
