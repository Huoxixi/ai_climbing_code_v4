import { computed } from 'vue'
import { visualReplayState } from '../services/visualReplayPresentation.js'
import { dateLabel } from '../services/replayPageLabels.js'

// Read saved job state without eagerly evaluating its evidence or changing records.
export function useReplayJobState({ activeJob, deletionReceipt, uploadProgress, limbNames }) {
  const isBusy = computed(() => ['queued', 'running'].includes(activeJob.value?.status))
  const isJobDeleting = computed(() => deletionReceipt.value
    ? deletionReceipt.value.state === 'queued'
    : activeJob.value?.deletion?.state === 'queued')
  const result = computed(() => activeJob.value?.result || null)
  const reviewResult = computed(() => activeJob.value?.hold_edit_draft || result.value || activeJob.value?.hold_draft || null)
  const allHoldsConfirmed = computed(() => !!activeJob.value?.holds_revision
    && activeJob.value.holds_confirmation?.revision === activeJob.value.holds_revision)
  const visualState = computed(() => visualReplayState(activeJob.value))
  const manualHoldOperations = computed(() => {
    const holds = reviewResult.value?.holds || []
    const fps = Number(activeJob.value?.video?.fps)
    let ordinal = 0
    return (activeJob.value?.hold_review_history || [])
      .filter((entry) => ['add_hold_at_point', 'promote_candidate', 'edit_hold_contour'].includes(entry.operation))
      .map((entry) => {
        ordinal += 1
        const hold = holds.find((item) => ['user_confirmed_video_click', 'user_confirmed_video_candidate'].includes(item.identity_source)
          && item.review_version === entry.version)
        const box = entry.bbox || hold?.bbox
        const pointXy = entry.point_xy || (box ? [box[0] + box[2] / 2, box[1] + box[3] / 2] : null)
        const timeSeconds = entry.time_seconds != null ? Number(entry.time_seconds)
          : (hold?.source_frame != null && Number.isFinite(fps) && fps > 0 ? Number(hold.source_frame) / fps : null)
        return { ...entry, ordinal, active:Boolean(hold), point_xy:pointXy, time_seconds:timeSeconds }
      })
  })
  const activeManualHoldCount = computed(() => manualHoldOperations.value.filter((entry) => entry.active).length)
  const sourceMedia = computed(() => activeJob.value?.media?.source_video || null)
  const sourceAvailable = computed(() => sourceMedia.value?.status === 'available')
  const sourcePlayable = computed(() => sourceAvailable.value &&
    (!activeJob.value?.preparation || activeJob.value.preparation.status === 'completed'))
  const overlayMedia = computed(() => activeJob.value?.media?.overlay_video || null)
  const overlayAvailable = computed(() => overlayMedia.value?.status === 'available')
  const reviewedOverlayAvailable = computed(() => activeJob.value?.media?.reviewed_overlay_video?.status === 'available')
  const currentRun = computed(() => {
    const attempt = activeJob.value?.attempt || 1
    return [...(activeJob.value?.analysis_runs || [])].reverse().find((run) => run.attempt === attempt)
  })
  const analysisEvidence = computed(() => result.value?.analysis || currentRun.value?.analysis || null)
  const statusTitle = computed(() => isJobDeleting.value ? '正在删除整次记录' : ({
    queued: '任务正在排队', running: activeJob.value?.stage || '正在分析视频',
    succeeded: '分析完成', failed: '分析未完成', cancelled: '任务已取消',
    awaiting_hold_review: '等待全部岩点确认',
  }[activeJob.value?.status] || '准备中'))
  const statusDetail = computed(() => {
    if (isJobDeleting.value) return '正在停止任务并删除原视频、复盘指标与派生文件。'
    if (activeJob.value?.status === 'failed') return activeJob.value.error || '请检查视频和本地骨架模型后重试。'
    if (activeJob.value?.status === 'cancelled') return sourceAvailable.value ? '原视频仍可用于重新分析。' : '原视频已删除，本次任务不能重新分析。'
    if (activeJob.value?.status === 'succeeded') return '结果为机器估算，请结合原视频复核。'
    if (activeJob.value?.status === 'awaiting_hold_review') return '检查岩点后点击“确认全部岩点”，再点击“开始复盘”。'
    if (activeJob.value?.status === 'queued') return uploadProgress.value < 100 ? `视频上传 ${uploadProgress.value}%` : '前方任务完成后会自动开始。'
    return '系统正在处理视频并识别动作；可以稍后在任务列表查看结果。'
  })
  const sourceRetentionLabel = computed(() => {
    const source = sourceMedia.value
    if (!source) return '未记录原视频保留状态'
    if (source.status === 'deleted') return `已于 ${dateLabel(source.deleted_at)} 删除，复盘指标仍保留`
    return '原片保留中，仅当前账号可见，可主动删除'
  })
  const overlayRetentionLabel = computed(() => {
    const overlay = overlayMedia.value
    if (!overlay) return '尚未生成'
    if (overlay.status === 'available') return '私密保留，可单独导出或删除'
    if (overlay.status === 'superseded') return '重新分析后旧叠加视频已替换'
    if (overlay.status === 'deleted') return `已于 ${dateLabel(overlay.deleted_at)} 删除`
    return '当前不可用'
  })
  const elapsedLabel = computed(() => {
    const seconds = result.value?.attempt?.elapsed_seconds
    return Number.isFinite(seconds) ? `${seconds.toFixed(1)} 秒` : '待复核'
  })
  const limbRows = computed(() => Object.entries(limbNames).map(([key, label]) => {
    const value = result.value?.attempt?.per_limb?.[key]
    return { key, label, seconds: `${Number(value?.contact_seconds || 0).toFixed(1)} 秒`,
      holds: value?.holds?.length ? `岩点 ${value.holds.join('、')}` : '未确认接触' }
  }))
  return {
    isBusy, isJobDeleting, result, reviewResult, allHoldsConfirmed,
    visualState, manualHoldOperations, activeManualHoldCount, sourceMedia, sourceAvailable,
    sourcePlayable, overlayMedia, overlayAvailable, reviewedOverlayAvailable, currentRun,
    analysisEvidence, statusTitle, statusDetail, sourceRetentionLabel, overlayRetentionLabel,
    elapsedLabel, limbRows,
  }
}

// Call after the page declares actionEvents; every returned value remains a computed ref.
export function useReplayPlaybackState(
  { activeJob, previewUrl, preferredPlaybackKind, testVideoCases, actionEvents },
  { sourcePlayable, overlayAvailable, reviewedOverlayAvailable, visualState },
  climbReplayService,
) {
  const comparisonCase = computed(() => testVideoCases.value.find((item) => (
    item.comparison_available
    && !visualState.value.visible
    && activeJob.value?.status === 'succeeded'
    && item.filename === activeJob.value?.original_name
    && item.comparison_route_color === activeJob.value?.route_color
    && Number(item.comparison_action_count) === actionEvents.value.length
  )) || null)
  const replayVideoAvailable = computed(() => reviewedOverlayAvailable.value || Boolean(comparisonCase.value) || overlayAvailable.value)
  const replayVideoUrl = computed(() => {
    if (activeJob.value?.id && reviewedOverlayAvailable.value) return climbReplayService.mediaUrl(activeJob.value.id, 'reviewed-overlay-video')
    if (comparisonCase.value) return climbReplayService.comparisonVideoUrl(comparisonCase.value.id)
    if (activeJob.value?.id && overlayAvailable.value) {
      return climbReplayService.mediaUrl(activeJob.value.id, 'overlay-video')
    }
    return ''
  })
  const playbackKind = computed(() => {
    if (previewUrl.value) return 'preview'
    if (preferredPlaybackKind.value === 'overlay' && replayVideoAvailable.value) return 'overlay'
    if (preferredPlaybackKind.value === 'source' && sourcePlayable.value) return 'source'
    if (replayVideoAvailable.value) return 'overlay'
    if (sourcePlayable.value) return 'source'
    return 'none'
  })
  const playbackUrl = computed(() => {
    if (previewUrl.value) return previewUrl.value
    if (!activeJob.value?.id) return ''
    if (playbackKind.value === 'overlay') return replayVideoUrl.value
    if (playbackKind.value === 'source') return climbReplayService.mediaUrl(activeJob.value.id, 'source-video')
    return ''
  })
  const playerMode = computed(() => {
    if (['preview', 'source'].includes(playbackKind.value)) return 'interactive'
    if (playbackKind.value === 'overlay') return 'rendered'
    return 'none'
  })
  const storedOverlayDownloadUrl = computed(() => activeJob.value?.id && overlayAvailable.value
    ? climbReplayService.mediaUrl(activeJob.value.id, 'overlay-video', true)
    : '')
  const replayDownloadUrl = computed(() => {
    if (activeJob.value?.id && reviewedOverlayAvailable.value) return climbReplayService.mediaUrl(activeJob.value.id, 'reviewed-overlay-video', true)
    if (comparisonCase.value) return climbReplayService.comparisonVideoUrl(comparisonCase.value.id, true)
    return storedOverlayDownloadUrl.value
  })
  return {
    comparisonCase, replayVideoAvailable, replayVideoUrl, playbackKind, playbackUrl,
    playerMode, storedOverlayDownloadUrl, replayDownloadUrl,
  }
}
