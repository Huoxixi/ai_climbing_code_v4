<template>
  <section class="unified-replay" aria-label="视频复盘" @keydown.esc="closeSummaryOnEscape">
    <div class="unified-stage" :class="{ locating: seekingFeedback }" :aria-busy="seekingFeedback">
      <ReplayVisualStage ref="visualStage" :src="mediaUrl" :summary="showData"
        @timeupdate="tick" @seeking="onSeeking" @seeked="onSeeked" @ended="onEnded" @loadedmetadata="loaded"
        @play="onPlay" @pause="stopFrames" @error="error = '视频无法播放，请重新载入记录。'">
        <Transition name="data-focus" @before-leave="beforeSummaryLeave">
          <ReplayPageSummary v-if="showData" :id="summaryId" ref="summaryPanel" :metrics="metrics" :motion-summary="state?.result?.motion_summary"
            :elapsed="summaryState.elapsed" :manual="summaryState.phase === 'manual'" :reduced-motion="summaryState.reducedMotion"
            @collapse="collapseSummary" @locate="locateMetric" />
        </Transition>
      </ReplayVisualStage>
    </div>
    <nav v-if="groups.length" class="action-strip" aria-label="动作时间轴">
      <button v-for="(group, index) in groups" :key="group.id" type="button"
        :style="{ left: `${group.start_seconds / duration * 100}%`, width: `${(group.end_seconds - group.start_seconds) / duration * 100}%` }"
        :class="{ selected: selected?.id === group.id }" :aria-pressed="selected?.id === group.id"
        :aria-label="`动作 ${index + 1}，${clock(group.start_seconds)} 至 ${clock(group.end_seconds)}，${group.description}`"
        @click="select(group)">{{ index + 1 }}</button>
      <i class="source-playhead" :style="{ left: `${Math.min(100, currentTime / duration * 100)}%` }" aria-hidden="true" />
    </nav>
    <div class="replay-controls">
      <template v-if="selected">
        <button type="button" :disabled="selectedIndex <= 0" @click="step(-1)">上一段</button>
        <button type="button" @click="select(selected, false)">重看</button>
        <button type="button" :disabled="selectedIndex < 0 || selectedIndex >= groups.length - 1" @click="step(1)">下一段</button>
        <button type="button" @click="exitSegment">整段观看</button>
      </template>
      <label>速度 <select v-model.number="speed" aria-label="播放速度" @change="setSpeed"><option :value=".5">0.5×</option><option :value=".75">0.75×</option><option :value="1">1×</option></select></label>
      <label v-if="selected"><input v-model="loop" type="checkbox" />循环</label>
      <button type="button" :disabled="!metrics.length" :aria-expanded="showData" :aria-controls="summaryId" @click="toggleSummary">复盘总结</button>
      <button v-if="metrics.some(m => m.key === 'longest_still' && Number.isFinite(m.start_seconds))" type="button" @click="locateMetric(metrics.find(m => m.key === 'longest_still'))">回看最长停留</button>
      <button type="button" :disabled="!state?.result_version" :aria-expanded="exportOpen" @click="exportOpen = !exportOpen">导出</button>
    </div>
    <ReplayActionNotes v-if="groups.length" :groups="groups" :time="currentTime" />
    <p v-if="state?.revision_count" class="range-label">页面动作解析与总结已按修正更新；基础画面中的动作图保留原分析。</p>
    <details v-if="selectedIndex >= 0 && state?.result_version && state?.vocabulary" class="action-correction">
      <summary>修正动作</summary>
      <ReplayActionDetail :group="groups[selectedIndex]" :holds="state.result.holds" :vocabulary="state.vocabulary"
        :disabled="busy || exportBusy || submitting" :revision-count="state.revision_count" @save="saveAction" @undo="undoAction" @locate="locateEvidence" />
    </details>
    <div v-if="exportOpen" class="export-options">
      <label>范围 <select v-model="exportScope" aria-label="导出范围"><option value="full">完整复盘</option><option value="group" :disabled="!selected || selectedIndex < 0">当前动作</option></select></label>
      <label>速度 <select v-model.number="exportSpeed" aria-label="导出速度"><option :value=".75">0.75×</option><option :value=".5">0.5×</option><option :value="1">1×</option></select></label>
      <p>{{ exportScope === 'full' ? `0:00–${clock(duration)}` : `${clock(selected?.start_seconds)}–${clock(selected?.end_seconds)} · 仅当前动作` }} · {{ exportSpeed }}× · 视频保留基础画面，动作文字和总结仅在页面展示。</p>
      <button type="button" :disabled="exportBusy || (exportScope === 'group' && selectedIndex < 0)" @click="exportVideo">{{ exportBusy ? '正在导出…' : '生成导出文件' }}</button>
      <button v-if="exportBusy" type="button" @click="cancelExport">停止导出</button>
      <a v-if="state?.export_media" :href="downloadUrl" download>下载{{ state.export_media.scope === 'full' ? '完整复盘' : '动作片段' }} · {{ state.export_media.speed }}×</a>
    </div>
    <Teleport to="body">
      <Transition name="orb-arrive">
        <button v-if="metrics.length && summaryState.phase === 'collapsed'" ref="summaryOrb" class="replay-data-orb summary-orb" type="button"
          aria-label="展开复盘总结" :aria-controls="summaryId" :aria-expanded="false" @click="openSummary"><span>复盘</span><span>总结</span></button>
      </Transition>
    </Teleport>
    <div v-if="sourceAvailable && !state?.result_version && !busy" class="organize-prompt">
      <p>整理动作后，可按段慢放和查看基础数据。</p>
      <button type="button" :disabled="submitting" @click="generate(false)">整理动作</button>
    </div>
    <p v-if="!sourceAvailable" class="range-label">原片已不可用，当前播放保留的旧视频。</p>
    <div v-if="busy" class="task-state" role="status">正在整理动作与核对骨架轨迹… <button type="button" @click="cancel">停止</button></div>
    <p v-if="error || taskError" role="alert">{{ error || taskError }}</p>
    <details class="replay-more">
      <summary>更多</summary>
      <div v-if="sourceAvailable && state?.cloud_configured" class="local-check">
        <p>核对动作名称会将每段的局部画面发送至阿里云百炼。费用按实际用量估算，本次预算预留 ¥0.20。</p>
        <label><input v-model="cloudConsent" type="checkbox" />同意发送本次画面并确认费用</label>
        <button type="button" :disabled="!cloudConsent || busy || submitting" @click="generate(true)">核对动作名称</button>
      </div>
      <p v-if="state?.stale">识别依据已更新，请重新整理动作。</p>
      <button v-if="sourceAvailable && state?.result_version" type="button" :disabled="busy" @click="generate(false)">重新整理</button>
      <p v-if="state?.task?.usage?.length">本次云请求 {{ state.task.usage.length }} 次；费用记录保留在任务中。</p>
      <p v-if="state?.cost?.known_amount != null">已知费用约 ¥{{ state.cost.known_amount }}<span v-if="!state.cost.usage_complete">，仍有请求的费用未确认</span></p>
      <p v-for="entry in state?.history_costs || []" :key="entry.id">历史请求 {{ entry.cost.request_count }} 次 · {{ entry.cost.known_amount == null ? '费用待确认' : `已知约 ¥${entry.cost.known_amount}` }}</p>
      <p v-if="metrics.some(m => m.basis === 'automatic_contacts')">四肢岩点数来自自动接触候选，同点已去重；局部遮挡和侧别误识别仍会影响计数。</p>
      <p v-if="metrics.some(m => m.basis === 'automatic_and_action_review_contacts')">岩点统计结合自动接触候选与本次人工修正；未修正的自动接触仍需核对。</p>
      <button type="button" @click="loadLegacy">查看旧报告与旧视频</button>
      <div v-if="legacy" class="legacy-record">
        <p>{{ legacy.report?.summary || '这条记录没有旧报告。' }}</p>
        <p v-for="row in legacy.report?.observations || []" :key="row.id">{{ row.observation || row.text }}</p>
        <p v-for="row in legacy.report?.improvements || []" :key="row.id">{{ row.adjustment }}</p>
        <a v-if="legacy.template?.media_ready" :href="service.templateVideoMediaUrl(job.id, true, legacy.template.media_version)" download>下载旧模板视频</a>
        <a v-if="legacyUrl" :href="legacyUrl" download>下载旧复盘视频</a>
      </div>
      <slot name="more" />
    </details>
  </section>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import service from '../services/climbReplayService'
import { segmentDecision } from '../services/actionPlayback.js'
import { summarySeconds } from '../services/replayPresentation.js'
import { createReplaySummaryController } from '../services/replaySummaryState.js'
import ReplayVisualStage from './ReplayVisualStage.vue'
import ReplayActionDetail from './ReplayActionDetail.vue'
import ReplayActionNotes from './ReplayActionNotes.vue'
import ReplayPageSummary from './ReplayPageSummary.vue'
const props = defineProps({ job: { type: Object, required: true }, legacyUrl: { type: String, default: '' } })
const visualStage = ref(null), video = computed(() => visualStage.value?.video)
const state = ref(null), selected = ref(null), speed = ref(.75), loop = ref(false)
const summaryState = ref({ phase: 'hidden', elapsed: 0, reducedMotion: false })
const summaryController = createReplaySummaryController({ onChange: next => { summaryState.value = next } })
const summaryPanel = ref(null), summaryOrb = ref(null)
const showData = computed(() => ['automatic', 'manual'].includes(summaryState.value.phase))
const summaryId = computed(() => `replay-summary-${props.job.id}`)
const error = ref(''), submitting = ref(false), cloudConsent = ref(false)
const exportOpen = ref(false), exportScope = ref('full'), exportSpeed = ref(.75)
const legacy = ref(null)
const currentTime = ref(0), seekingFeedback = ref(false)
let timer, seekTimer, frameCallback, generation = 0, internalSeek = false, internalSeekTarget = 0, preserveSummarySeek = false
const sourceAvailable = computed(() => props.job.media?.source_video?.status === 'available')
const groups = computed(() => state.value?.result?.groups || [])
const metrics = computed(() => state.value?.result?.metrics || [])
const duration = computed(() => state.value?.result?.source_duration_seconds || props.job.result?.video?.duration_seconds || 0)
const selectedIndex = computed(() => groups.value.findIndex(g => g.id === selected.value?.id))
const busy = computed(() => ['queued', 'running'].includes(state.value?.task?.status))
const exportBusy = computed(() => ['queued', 'running'].includes(state.value?.export?.status))
const taskError = computed(() => state.value?.task?.error || state.value?.export?.error)
// Preserve the approved base frame with its skeleton, route map and sequence.
const mediaUrl = computed(() => state.value?.media_ready ? service.actionMediaUrl(props.job.id, state.value.result_version)
  : props.legacyUrl || (sourceAvailable.value ? service.mediaUrl(props.job.id, 'source-video') : ''))
const downloadUrl = computed(() => service.actionMediaUrl(props.job.id, state.value?.export_media?.id, true, true))
const clock = t => `${Math.floor((t || 0) / 60)}:${((t || 0) % 60).toFixed(1).padStart(4, '0')}`
function setSpeed() { if (video.value) video.value.playbackRate = speed.value }
function loaded() { setSpeed() }
function exitVideoFullscreen() {
  // Native video fullscreen excludes the surrounding summary layer.
  if (document.fullscreenElement === video.value) Promise.resolve(document.exitFullscreen?.()).catch(() => {})
  if (video.value?.webkitDisplayingFullscreen) video.value.webkitExitFullscreen?.()
}
function showSummaryOnce() {
  if (summaryController.ended(summarySeconds(metrics.value, state.value?.result?.motion_summary), window.matchMedia('(prefers-reduced-motion: reduce)').matches)) {
    video.value?.pause(); exitVideoFullscreen()
  }
}
async function openSummary() {
  video.value?.pause(); exitVideoFullscreen(); summaryController.open()
  await nextTick(); summaryPanel.value?.focusClose()
}
function collapseSummary() { summaryController.collapse() }
function closeSummaryOnEscape(event) {
  if (showData.value) { event.preventDefault(); event.stopPropagation(); collapseSummary() }
}
function toggleSummary() { if (showData.value) collapseSummary(); else openSummary() }
function beforeSummaryLeave(element) {
  const hadFocus = element.contains(document.activeElement)
  const box = element.getBoundingClientRect()
  // Let the recap travel beyond the video frame towards the fixed disc.
  Object.assign(element.style, { position: 'fixed', inset: 'auto', boxSizing: 'border-box', left: `${box.left}px`, top: `${box.top}px`, width: `${box.width}px`, height: `${box.height}px`, zIndex: '101' })
  element.style.setProperty('--orb-x', `${window.innerWidth - 54 - (box.left + box.width / 2)}px`)
  element.style.setProperty('--orb-y', `${window.innerHeight - 54 - (box.top + box.height / 2)}px`)
  element.style.setProperty('--orb-scale-x', `${64 / Math.max(1, box.width)}`)
  element.style.setProperty('--orb-scale-y', `${64 / Math.max(1, box.height)}`)
  nextTick(() => {
    const orb = summaryOrb.value
    if (!orb) return
    const target = orb.getBoundingClientRect()
    element.style.setProperty('--orb-x', `${target.left + target.width / 2 - (box.left + box.width / 2)}px`)
    element.style.setProperty('--orb-y', `${target.top + target.height / 2 - (box.top + box.height / 2)}px`)
    if (hadFocus) orb.focus()
  })
}
function exitSegment() { selected.value = null; loop.value = false; speed.value = .75; setSpeed() }
async function play() { try { await video.value?.play() } catch { /* Native play control remains available. */ } }
function seek(time, preserveSummary = false) {
  if (!video.value) return
  if (!preserveSummary) summaryController.interrupt()
  internalSeek = true; internalSeekTarget = time; preserveSummarySeek = preserveSummary; video.value.currentTime = time
}
function select(group) {
  if (!video.value) return
  selected.value = group
  setSpeed(); seek(group.start_seconds); play()
}
function step(offset) { const group = groups.value[selectedIndex.value + offset]; if (group) select(group) }
function tick() {
  if (video.value) currentTime.value = video.value.currentTime
  if (!video.value || video.value.seeking) return
  // Old retained videos may contain a summary tail. Stop at the original climbing end.
  if (!selected.value && duration.value > 0 && video.value.duration > duration.value + .05 && currentTime.value >= duration.value - .015) {
    video.value.pause(); seek(Math.max(0, duration.value - .02), true); showSummaryOnce(); return
  }
  const decision = segmentDecision(selected.value, video.value.currentTime, { loop: loop.value })
  if (decision === 'repeat') { seek(selected.value.start_seconds); play() }
  else if (decision === 'pause') { video.value.pause() }
}
function onSeeking() {
  clearTimeout(seekTimer); seekingFeedback.value = true
  const ownSeek = internalSeek && Math.abs(video.value.currentTime - internalSeekTarget) < .05
  if (!(ownSeek && preserveSummarySeek)) summaryController.interrupt()
  if (!ownSeek && segmentDecision(selected.value, video.value.currentTime, { seeking: true }) === 'exit') exitSegment()
}
function onSeeked() { currentTime.value = video.value?.currentTime || 0; internalSeek = false; preserveSummarySeek = false; seekTimer = setTimeout(() => { seekingFeedback.value = false }, 120) }
function onEnded() {
  if (selected.value) { if (loop.value) { seek(selected.value.start_seconds); play() } return }
  showSummaryOnce()
}
function locateMetric(m) { collapseSummary(); select({ id: 'metric-stop', start_seconds: Math.max(0, m.start_seconds - .3), end_seconds: Math.min(duration.value, m.end_seconds + .4) }) }
function stopFrames() { if (frameCallback != null) video.value?.cancelVideoFrameCallback?.(frameCallback); frameCallback = null }
function startFrames() {
  stopFrames()
  if (!video.value?.requestVideoFrameCallback) return
  const next = () => { tick(); if (video.value && !video.value.paused) frameCallback = video.value.requestVideoFrameCallback(next) }
  frameCallback = video.value.requestVideoFrameCallback(next)
}
function onPlay() { summaryController.interrupt(); startFrames() }
async function refresh(id, token) {
  try {
    const data = await service.actions(id)
    if (token !== generation) return
    state.value = data
    clearTimeout(timer)
    if (busy.value || exportBusy.value) timer = setTimeout(() => refresh(id, token), 1000)
  } catch (e) { if (token === generation) error.value = e.response?.data?.detail || '无法读取复盘状态，请重新载入记录。' }
}
async function perform(fn) {
  const token = generation, id = props.job.id
  error.value = ''; submitting.value = true
  try { await fn(id); if (token === generation) await refresh(id, token) }
  catch (e) { if (token === generation) error.value = e.response?.data?.detail || '操作未完成，请重试。' }
  finally { if (token === generation) submitting.value = false }
}
function generate(cloud) { return perform(id => service.generateActions(id, { cloud_consent: cloud, consent_version: cloud ? state.value?.consent_version : null, budget_confirmed: cloud })) }
function cancel() { return perform(id => service.cancelActions(id)) }
function cancelExport() { return perform(id => service.cancelActionExport(id)) }
function saveAction(payload) { return perform(id => service.reviewAction(id, { ...payload, result_version: state.value.result_version })) }
function undoAction() { return perform(id => service.undoActionReview(id, { result_version: state.value.result_version })) }
function locateEvidence(time) { if (video.value) { video.value.pause(); seek(time) } }
async function loadLegacy() {
  const token = generation, id = props.job.id
  try {
    const [report, template] = await Promise.all([service.coaching(id), service.templateVideo(id)])
    if (token === generation) legacy.value = { report: report.report, template }
  } catch { if (token === generation) error.value = '旧记录暂时无法读取，请稍后重试。' }
}
function exportVideo() { return perform(id => service.exportActions(id, { result_version: state.value.result_version, scope: exportScope.value, group_id: exportScope.value === 'group' ? selected.value?.id : null, speed: exportSpeed.value })) }
watch(() => props.job.id, id => {
  generation++; clearTimeout(timer); stopFrames(); summaryController.setRecord(id); state.value = null; selected.value = null
  speed.value = .75; exportSpeed.value = .75; loop.value = false; cloudConsent.value = false; exportOpen.value = false; error.value = ''; submitting.value = false
  legacy.value = null
  currentTime.value = 0; seekingFeedback.value = false; internalSeek = false; preserveSummarySeek = false; clearTimeout(seekTimer)
  refresh(id, generation)
}, { immediate: true })
watch(() => state.value?.result_version, (next, previous) => {
  if (previous && next !== previous) {
    const updated = groups.value.find(g => g.id === selected.value?.id)
    if (updated) { selected.value = updated; video.value?.pause() }
    else exitSegment()
  }
})
onBeforeUnmount(() => { generation++; clearTimeout(timer); clearTimeout(seekTimer); summaryController.dispose(); stopFrames() })
defineExpose({ seekClip: select })
</script>

<style scoped>
@font-face { font-family: 'Replay Noto'; src: url('/fonts/ReplayNotoSC.woff2') format('woff2'); font-weight: 100 900; font-display: swap; }
.unified-replay { --replay-bg: #151719; --replay-ink: #f7f8f8; --replay-muted: #c1c7cb; --replay-accent: #d6e9b9; color: var(--replay-ink); background: var(--replay-bg); font-family: 'Replay Noto', 'Noto Sans SC', 'Source Han Sans SC', 'Microsoft YaHei', sans-serif; border-radius: 12px; overflow: hidden; }
.unified-stage { position: relative; background: #090a0b; width: 100%; margin: 0 auto; }
video { display: block; width: 100%; max-height: 72vh; object-fit: contain; transition: opacity .12s ease-out; }
.locating video { opacity: .82; }
.action-strip { position: relative; height: 40px; margin: 12px 16px 4px; background: #252a2d; }
.action-strip button { position: absolute; top: 0; min-width: 8px; border-radius: 3px; background: #3d4347; padding: 4px 0; border-right: 3px solid var(--replay-bg); }
.source-playhead { position: absolute; top: 0; bottom: 0; width: 2px; background: white; pointer-events: none; }
.action-strip button.selected { background: var(--replay-accent); color: #15200b; }
.replay-controls { display: flex; flex-wrap: wrap; align-items: center; gap: 8px 12px; padding: 12px 16px; }
button, select, a { font: inherit; color: inherit; }
button, select { min-height: 40px; border: 0; border-radius: 6px; background: #30363a; padding: 6px 12px; cursor: pointer; }
button:hover:not(:disabled), select:hover { background: #465057; }
button:disabled { opacity: .45; cursor: default; }
button:focus-visible, select:focus-visible, summary:focus-visible, a:focus-visible { outline: 2px solid var(--replay-accent); outline-offset: 3px; }
input { accent-color: var(--replay-accent); }
.range-label, .organize-prompt, .task-state, [role='alert'], .export-options { margin: 0; padding: 8px 16px 16px; line-height: 1.6; }
.range-label { color: var(--replay-muted); font-variant-numeric: tabular-nums; }
.export-options { display: flex; flex-wrap: wrap; align-items: center; gap: 12px; }
.export-options p { width: 100%; margin: 0; }
.export-options a { text-underline-offset: 4px; }
.replay-more { background: #f8faf9; color: #26312c; padding: 0 16px 16px; }
.replay-more > summary { padding: 16px 0; cursor: pointer; }
.local-check { line-height: 1.6; max-width: 65ch; }
.local-check button, .replay-more > button { background: #e0e8e2; display: block; margin: 12px 0; }
.action-correction { padding: 0 16px 12px; }
.action-correction > summary { min-height: 44px; display: list-item; align-content: center; cursor: pointer; color: var(--replay-muted); }
.data-focus-enter-active { transition: opacity .25s ease-out; }
.data-focus-leave-active { transition: transform .5s cubic-bezier(.16,1,.3,1), opacity .4s ease-out, border-radius .5s ease-out; pointer-events: none; }
.data-focus-enter-from { opacity: 0; }
.data-focus-leave-to { transform: translate(var(--orb-x), var(--orb-y)) scale(var(--orb-scale-x), var(--orb-scale-y)); opacity: 0; border-radius: 50%; }
.replay-data-orb { position: fixed; z-index: 100; right: max(22px, env(safe-area-inset-right)); bottom: calc(max(22px, env(safe-area-inset-bottom)) + var(--ui-shell-bottom, 0px)); width: 64px; height: 64px; display: flex; flex-direction: column; align-items: center; justify-content: center; background: #142b35; color: #effcff; border: 1px solid #7cdee5; border-radius: 50%; font: 600 12px/1.55 'Replay Noto', 'Noto Sans SC', sans-serif; padding: 0; cursor: pointer; }
.replay-data-orb:hover { background: #315863; }
.replay-data-orb:focus-visible { outline: 2px solid #7cdee5; outline-offset: 4px; }
.orb-arrive-enter-active { transition: transform .45s cubic-bezier(.16,1,.3,1), opacity .3s; transition-delay: .2s; }
.orb-arrive-enter-from { opacity: 0; transform: scale(.2); }
::selection { background: var(--replay-accent); color: #15200b; }
@media (max-width: 480px) { .replay-controls { gap: 8px; padding: 8px; } button, select { padding: 6px 9px; } }
@media (prefers-reduced-motion: reduce) { video, .data-focus-enter-active, .data-focus-leave-active, .orb-arrive-enter-active { transition: none; } .data-focus-leave-to, .orb-arrive-enter-from { transform: none; } }
</style>
