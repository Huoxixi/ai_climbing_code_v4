import assert from 'node:assert/strict'
import test from 'node:test'
import { computed, ref } from 'vue'
import { replayPageState as setup } from './fixtures/replayPageState.mjs'
const available = { status: 'available' }
const saved = (media = {}) => ({ id: 'saved', status: 'succeeded', original_name: 'wall.mp4', route_color: '黄色', media: structuredClone(media) })

test('page state creation is lazy and a local preview bypasses unread job state', () => {
  const activeJob = computed(() => { throw new Error('job must stay unread') })
  const { state, calls } = setup(null, { activeJob, previewUrl: ref('blob:preview') })
  assert.equal(state.playbackUrl.value, 'blob:preview')
  assert.equal(state.playbackKind.value, 'preview')
  assert.equal(state.playerMode.value, 'interactive')
  assert.deepEqual(calls, [])
})

test('result and review selectors preserve object identity and draft priority', () => {
  const { state, activeJob } = setup({ result: { marker: 'result' }, hold_draft: { marker: 'initial' }, hold_edit_draft: { marker: 'edit' } })
  assert.equal(state.result.value, activeJob.value.result)
  assert.equal(state.reviewResult.value, activeJob.value.hold_edit_draft)
  delete activeJob.value.hold_edit_draft
  assert.equal(state.reviewResult.value, activeJob.value.result)
  delete activeJob.value.result
  assert.equal(state.reviewResult.value, activeJob.value.hold_draft)
  activeJob.value = null
  assert.equal(state.result.value, null)
  assert.equal(state.reviewResult.value, null)
})

test('busy and deletion selectors retain receipt precedence and react to updates', () => {
  const { state, activeJob, deletionReceipt } = setup({ status: 'queued', deletion: { state: 'queued' } })
  assert.equal(state.isBusy.value, true)
  assert.equal(state.isJobDeleting.value, true)
  deletionReceipt.value = { state: 'completed' }
  assert.equal(state.isJobDeleting.value, false)
  deletionReceipt.value = null
  activeJob.value.status = 'succeeded'
  assert.equal(state.isBusy.value, false)
  assert.equal(state.isJobDeleting.value, true)
})

test('source availability remains distinct from completed preparation', () => {
  const { state, activeJob } = setup(saved({ source_video: available }))
  assert.equal(state.sourceMedia.value, activeJob.value.media.source_video)
  assert.equal(state.sourceAvailable.value, true)
  assert.equal(state.sourcePlayable.value, true)
  activeJob.value.preparation = { status: 'running' }
  assert.equal(state.sourceAvailable.value, true)
  assert.equal(state.sourcePlayable.value, false)
  activeJob.value.preparation.status = 'completed'
  assert.equal(state.sourcePlayable.value, true)
  activeJob.value.media.source_video.status = 'deleted'
  assert.equal(state.sourcePlayable.value, false)
})

test('hold confirmation requires a present revision and exact matching receipt', () => {
  const { state, activeJob } = setup({ holds_revision: 'revision-1', holds_confirmation: { revision: 'revision-2' } })
  assert.equal(state.allHoldsConfirmed.value, false)
  activeJob.value.holds_confirmation.revision = 'revision-1'
  assert.equal(state.allHoldsConfirmed.value, true)
  activeJob.value.holds_revision = ''
  assert.equal(state.allHoldsConfirmed.value, false)
})

test('analysis evidence uses the latest current attempt and preserves saved-result identity', () => {
  const { state, activeJob } = setup({ attempt: 2, analysis_runs: [
    { attempt: 1, analysis: { marker: 'old' } },
    { attempt: 2, analysis: { marker: 'earlier' } },
    { attempt: 2, analysis: { marker: 'latest' } },
  ] })
  assert.equal(state.currentRun.value, activeJob.value.analysis_runs[2])
  assert.equal(state.analysisEvidence.value.marker, 'latest')
  activeJob.value.result = { analysis: { marker: 'success' } }
  assert.equal(state.analysisEvidence.value, activeJob.value.result.analysis)
  delete activeJob.value.result
  activeJob.value.attempt = 3
  assert.equal(state.currentRun.value, undefined)
  assert.equal(state.analysisEvidence.value, null)
})

test('task status wording retains upload progress, source recovery and deletion priority', () => {
  const { state, activeJob, uploadProgress, deletionReceipt } = setup(saved({ source_video: available }))
  assert.equal(state.statusTitle.value, '分析完成')
  assert.equal(state.statusDetail.value, '结果为机器估算，请结合原视频复核。')
  activeJob.value.status = 'queued'; uploadProgress.value = 36
  assert.equal(state.statusDetail.value, '视频上传 36%')
  uploadProgress.value = 100
  assert.equal(state.statusDetail.value, '前方任务完成后会自动开始。')
  activeJob.value.status = 'cancelled'
  assert.equal(state.statusDetail.value, '原视频仍可用于重新分析。')
  activeJob.value.media.source_video.status = 'deleted'
  assert.equal(state.statusDetail.value, '原视频已删除，本次任务不能重新分析。')
  activeJob.value.status = 'failed'; activeJob.value.error = '构造失败'
  assert.equal(state.statusDetail.value, '构造失败')
  deletionReceipt.value = { state: 'queued' }
  assert.equal(state.statusTitle.value, '正在删除整次记录')
  assert.equal(state.statusDetail.value, '正在停止任务并删除原视频、复盘指标与派生文件。')
})

test('retention labels preserve source privacy and separate overlay lifecycle states', () => {
  const { state, activeJob } = setup(saved())
  assert.equal(state.sourceRetentionLabel.value, '未记录原视频保留状态')
  assert.equal(state.overlayRetentionLabel.value, '尚未生成')
  activeJob.value.media = { source_video: { status: 'available' }, overlay_video: { status: 'available' } }
  assert.equal(state.sourceRetentionLabel.value, '原片保留中，仅当前账号可见，可主动删除')
  assert.equal(state.overlayRetentionLabel.value, '私密保留，可单独导出或删除')
  activeJob.value.media.overlay_video.status = 'superseded'
  assert.equal(state.overlayRetentionLabel.value, '重新分析后旧叠加视频已替换')
  const deletedAt = new Date(2026, 0, 2, 3, 4).toISOString()
  activeJob.value.media = { source_video: { status: 'deleted', deleted_at: deletedAt }, overlay_video: { status: 'deleted', deleted_at: deletedAt } }
  assert.equal(state.sourceRetentionLabel.value, '已于 1/2 03:04 删除，复盘指标仍保留')
  assert.equal(state.overlayRetentionLabel.value, '已于 1/2 03:04 删除')
})

test('summary values retain numeric qualification, limb order and empty defaults', () => {
  const { state, activeJob } = setup({ result: { attempt: { elapsed_seconds: 12.25, per_limb: { left_hand: { contact_seconds: 3.25, holds: [1, 2] } } } } })
  assert.equal(state.elapsedLabel.value, '12.3 秒')
  assert.deepEqual(state.limbRows.value[0], { key: 'left_hand', label: '左手', seconds: '3.3 秒', holds: '岩点 1、2' })
  assert.deepEqual(state.limbRows.value.map(row => row.key), ['left_hand', 'right_hand', 'left_foot', 'right_foot'])
  assert.equal(state.limbRows.value[1].holds, '未确认接触')
  activeJob.value.result.attempt.elapsed_seconds = '12.25'
  assert.equal(state.elapsedLabel.value, '待复核')
  assert.equal(state.limbRows.value, state.limbRows.value)
})

test('manual hold history preserves active identity, ordinal filtering and recorded points', () => {
  const { state, activeJob } = setup({ video: { fps: 25 }, hold_draft: { holds: [{ identity_source: 'user_confirmed_video_click', review_version: 2, source_frame: 50, bbox: [0.1, 0.2, 0.4, 0.6] }] }, hold_review_history: [
    { operation: 'unrelated', version: 0 },
    { operation: 'add_hold_at_point', version: 1, point_xy: [0.4, 0.6], time_seconds: 3 },
    { operation: 'edit_hold_contour', version: 2 },
  ] })
  const original = JSON.stringify(activeJob.value)
  assert.equal(state.manualHoldOperations.value.length, 2)
  assert.equal(state.manualHoldOperations.value[0].point_xy, activeJob.value.hold_review_history[1].point_xy)
  assert.equal(state.manualHoldOperations.value[0].active, false)
  assert.equal(state.manualHoldOperations.value[1].ordinal, 2)
  assert.equal(state.manualHoldOperations.value[1].time_seconds, 2)
  assert.deepEqual(state.manualHoldOperations.value[1].point_xy, [0.30000000000000004, 0.5])
  assert.equal(state.activeManualHoldCount.value, 1)
  assert.equal(JSON.stringify(activeJob.value), original)
})

test('media selection keeps revision, legacy overlay, source and empty fallbacks', () => {
  const { state, activeJob, preferredPlaybackKind, calls } = setup(saved({ source_video: available, overlay_video: available, reviewed_overlay_video: available }))
  assert.deepEqual(calls, [])
  assert.equal(state.playbackKind.value, 'overlay')
  assert.equal(state.playbackUrl.value, 'saved/reviewed-overlay-video')
  assert.equal(state.replayDownloadUrl.value, 'saved/reviewed-overlay-video?download')
  preferredPlaybackKind.value = 'source'
  assert.equal(state.playbackUrl.value, 'saved/source-video')
  delete activeJob.value.media.reviewed_overlay_video
  preferredPlaybackKind.value = 'overlay'
  assert.equal(state.playbackUrl.value, 'saved/overlay-video')
  assert.equal(state.storedOverlayDownloadUrl.value, 'saved/overlay-video?download')
  delete activeJob.value.media.overlay_video
  assert.equal(state.playbackKind.value, 'source')
  assert.equal(state.playerMode.value, 'interactive')
  delete activeJob.value.media.source_video
  assert.equal(state.playbackKind.value, 'none')
  assert.equal(state.playbackUrl.value, '')
  assert.equal(state.playerMode.value, 'none')
})

test('nonempty historical comparison matches exact saved inputs and retains download fallback', () => {
  const { state, activeJob, testVideoCases, actionEvents } = setup(saved({ source_video: available, overlay_video: available }))
  actionEvents.value = [{ id: 'event' }]
  testVideoCases.value = [{ id: 'case', comparison_available: true, filename: 'wall.mp4', comparison_route_color: '黄色', comparison_action_count: '1' }]
  assert.equal(state.comparisonCase.value, testVideoCases.value[0])
  assert.equal(state.replayVideoUrl.value, 'case/comparison')
  assert.equal(state.replayDownloadUrl.value, 'case/comparison?download')
  actionEvents.value.push({ id: 'second' })
  assert.equal(state.comparisonCase.value, null)
  assert.equal(state.replayVideoUrl.value, 'saved/overlay-video')
  testVideoCases.value[0].comparison_action_count = 2
  activeJob.value.result = { visual_replay: { status: 'failed' } }
  assert.equal(state.comparisonCase.value, null)
  delete activeJob.value.result
  activeJob.value.route_color = '红色'
  assert.equal(state.comparisonCase.value, null)
})

test('comparison short circuit does not evaluate action evidence before all prior matches', () => {
  let reads = 0
  const actionEvents = computed(() => { reads++; return [] })
  const { state, testVideoCases, activeJob } = setup(saved(), { actionEvents })
  testVideoCases.value = [{ id: 'case', comparison_available: false, filename: 'wall.mp4', comparison_route_color: '黄色', comparison_action_count: 0 }]
  assert.equal(state.comparisonCase.value, null)
  assert.equal(reads, 0)
  testVideoCases.value[0].comparison_available = true
  activeJob.value.status = 'failed'
  assert.equal(state.comparisonCase.value, null)
  assert.equal(reads, 0)
  activeJob.value.status = 'succeeded'
  assert.equal(state.comparisonCase.value.id, 'case')
  assert.equal(reads, 1)
})

test('URL selectors remain cached, reactive and free from writes', () => {
  const { state, activeJob, calls, previewUrl } = setup(saved({ overlay_video: available }))
  assert.equal(calls.length, 0)
  assert.equal(state.replayVideoUrl.value, 'saved/overlay-video')
  assert.equal(state.replayVideoUrl.value, 'saved/overlay-video')
  assert.equal(calls.length, 1)
  activeJob.value.id = 'next'
  assert.equal(state.replayVideoUrl.value, 'next/overlay-video')
  assert.equal(calls.length, 2)
  previewUrl.value = 'blob:new'
  assert.equal(state.playbackUrl.value, 'blob:new')
  assert.equal(calls.length, 2)
  assert.equal(activeJob.value.media.overlay_video.status, 'available')
})
