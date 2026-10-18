<template>
  <section class="unified-replay" aria-label="视频复盘">
    <div ref="replayView" class="replay-view">
    <div class="unified-stage" :class="{ locating: seekingFeedback }" :aria-busy="seekingFeedback">
      <ReplayVisualStage ref="visualStage" :src="mediaUrl" :frame="replayFrame" :holds="job.result?.holds || []" :contacts="visualization?.contacts || job.result?.attempt?.contacts || []" :summary="false" :original-source="sourceAvailable" :visualization="visualization"
        @timeupdate="tick" @seeking="onSeeking" @seeked="onSeeked" @ended="onEnded" @loadedmetadata="loaded"
        @play="onPlay" @pause="stopFrames" @fullscreen="fullscreen" @error="error = '视频无法播放，请重新载入记录。'">
        <template #tools>
          <button v-if="metrics.length" type="button" class="statistics-orb" aria-label="基础数据统计" :aria-expanded="statisticsOpen" aria-controls="replay-statistics" @click="statisticsOpen=!statisticsOpen"><DataAnalysis aria-hidden="true" /></button>
          <section v-if="statisticsOpen && metrics.length" id="replay-statistics" class="replay-basic-statistics" aria-label="基础数据统计" @keydown.esc.stop="statisticsOpen=false">
            <div class="statistics-heading"><h2>基础数据统计</h2><button type="button" aria-label="关闭基础数据" @click="statisticsOpen=false"><Close aria-hidden="true" /></button></div>
            <dl><div v-for="metric in metrics" :key="metric.key"><dt>{{ metric.label }}</dt><dd>{{ metricValue(metric) }} <span>{{ metric.unit }}</span></dd></div></dl>
          </section>
        </template>
      </ReplayVisualStage>
    </div>
    <nav v-if="groups.length" class="action-strip" aria-label="动作时间轴">
      <div class="timeline-heading"><strong>动作时间轴</strong><nav v-if="groups.length>timelineSize" class="timeline-pages" aria-label="动作分页"><button type="button" :disabled="timelinePage===0" @click="timelinePage--">上一页</button><output>{{timelinePage+1}} / {{Math.ceil(groups.length/timelineSize)}}</output><button type="button" :disabled="(timelinePage+1)*timelineSize>=groups.length" @click="timelinePage++">下一页</button></nav></div>
      <div class="source-progress" aria-hidden="true"><i class="source-playhead" :style="{ left: `${Math.min(100, currentTime / duration * 100)}%` }" /></div>
      <div class="action-list">
      <button v-for="(group, index) in timelineGroups" :key="group.id" type="button"
        :class="{ selected: selected?.id === group.id }" :aria-pressed="selected?.id === group.id"
        :aria-label="`动作 ${timelinePage * timelineSize + index + 1}，${clock(group.start_seconds)} 至 ${clock(group.end_seconds)}`"
        @click="select(group)"><span class="action-number">{{ timelinePage * timelineSize + index + 1 }}</span><time>{{ clock(group.start_seconds) }}–{{ clock(group.end_seconds) }}</time></button>
      </div>
    </nav>
    <div class="replay-controls">
      <div v-if="selected" class="segment-controls">
        <button type="button" :disabled="playbackIndex <= 0" @click="step(-1)">上一段</button>
        <button type="button" @click="select(selected, false)">重看</button>
        <button type="button" :disabled="playbackIndex < 0 || playbackIndex >= playbackGroups.length - 1" @click="step(1)">下一段</button>
        <button type="button" @click="exitSegment">整段观看</button>
      </div>
      <label class="speed-control">速度 <select v-model.number="speed" aria-label="播放速度" @change="setSpeed"><option :value=".5">0.5×</option><option :value=".75">0.75×</option><option :value="1">1×</option></select></label>
      <label v-if="selected"><input v-model="loop" type="checkbox" />循环</label>
      <button v-if="metrics.some(m => m.key === 'longest_still' && Number.isFinite(m.start_seconds))" type="button" @click="locateMetric(metrics.find(m => m.key === 'longest_still'))">回看最长停留</button>
      <button type="button" :disabled="!canExport" :aria-expanded="exportOpen" @click="openExport"><Download aria-hidden="true" />导出</button>
      <button v-if="selectedIndex >= 0 && state?.result_version && state?.vocabulary" type="button" @click="correctionOpen=true">修正动作</button>
    </div>
    </div>
    <p v-if="sourceAvailable" class="range-label">白点：估算重心 · 轨迹：重心移动路线</p>
    <ReplayActionNotes v-if="state?.result?.ai_analysis" :groups="groups" :analysis="state.result.ai_analysis" :time="currentTime" @select="select" />
    <p v-if="state?.result?.commentary_disclaimer" class="range-label">{{ state.result.commentary_disclaimer }}</p>
    <section v-if="sourceAvailable && !state?.result?.ai_analysis" class="local-check" aria-label="AI 复盘分析">
      <template v-if="state?.legacy_saved_vision_return">
        <p>已有返回已保留，旧分析无法用于当前动作时间。重新分析会发送新请求并产生费用。</p>
        <template v-if="state?.cloud_configured"><label><input v-model="cloudConsent" type="checkbox" />同意重新发送本次复盘资料，并确认新增费用</label>
        <button type="button" :disabled="!cloudConsent || busy || submitting" @click="generate(true,false,true)">重新分析</button></template>
      </template>
      <template v-else-if="state?.local_commentary_retry_available || state?.saved_commentary_available">
        <p>分析返回已保存，恢复不会再次调用 AI。</p>
        <button type="button" :disabled="busy || submitting" @click="resumeAnalysis">恢复分析</button>
      </template>
      <template v-else-if="state?.cloud_configured">
        <p>{{state.analysis_input_mode === 'video' ? 'AI 将结合完整视频与计算数据进行复盘。' : 'AI 将结合全程抽样画面与计算数据进行复盘。'}}费用以服务账单为准。</p>
        <label><input v-model="cloudConsent" type="checkbox" />同意发送本次复盘资料，并确认费用</label>
        <button type="button" :disabled="!cloudConsent || busy || submitting" @click="generate(true)">开始 AI 复盘</button>
      </template>
      <p v-else>本地复盘可直接观看和导出。启用 AI 分析请先在<a href="#/settings">设置</a>中配置 AI 服务。</p>
    </section>
    <p v-if="state?.revision_count" class="range-label">动作解析、基础统计与右侧用点已按修正更新。</p>
    <WorkspaceSheet v-if="correctionOpen && selectedIndex >= 0 && state?.result_version && state?.vocabulary" title="修正动作" @close="correctionOpen=false">

      <ReplayActionDetail :group="localGroups[selectedIndex]" :holds="state.result.holds || []" :vocabulary="state.vocabulary"
        :disabled="busy || exportBusy || submitting" :revision-count="state.revision_count" @save="saveAction" @undo="undoAction" @locate="locateEvidence" />
    </WorkspaceSheet>
    <WorkspaceSheet v-if="exportOpen" title="导出复盘" @close="exportOpen=false">
      <fieldset class="export-content">
        <legend>导出内容</legend>
        <label><input v-model="exportContent" type="radio" value="video" name="replay-export-content" />复盘视频</label>
        <label><input v-model="exportContent" type="radio" value="package" name="replay-export-content" :disabled="!state?.result_version && !canPrepareExport" />视频＋全部资料</label>
      </fieldset>
      <template v-if="state?.result_version">
        <label>范围 <select v-model="exportScope" aria-label="导出范围"><option value="full">完整复盘</option><option value="group" :disabled="!selected || (selectedIndex < 0 && !selected.segment_id)">当前动作</option></select></label>
        <label>速度 <select v-model.number="exportSpeed" aria-label="导出速度"><option :value=".75">0.75×</option><option :value=".5">0.5×</option><option :value="1">1×</option></select></label>
        <p>{{ exportScope === 'full' ? `0:00–${clock(duration)}` : `${clock(selected?.start_seconds)}–${clock(selected?.end_seconds)} · 仅当前动作` }} · {{ exportSpeed }}× · 视频保留基础画面，动作文字和基础数据仅在页面展示。</p>
        <button type="button" :disabled="exportBusy || submitting || (exportScope === 'group' && selectedIndex < 0 && !selected?.segment_id)" @click="exportVideo">{{ exportBusy ? '正在导出…' : '导出文件' }}</button>
        <button v-if="exportBusy" type="button" @click="cancelExport">停止导出</button>
        <a v-if="state?.export_media && exportContent === 'video'" :href="downloadUrl" download>下载复盘视频 · {{ state.export_media.scope === 'full' ? '完整复盘' : '动作片段' }} · {{ state.export_media.speed }}×</a>
        <a v-else-if="state?.export_media" :href="packageUrl" download="climb-replay-package.zip">下载视频＋全部资料</a>
        <p v-if="exportContent === 'package'">资料包包含复盘视频、可用原片、全部本地计算数据（时间、身体角度、估算重心等）、提示词与约束及证据画面。解压后可交给自己的 AI；原片时间与慢放、片段时间的换算见包内说明。</p>
      </template>
      <template v-else>
        <p v-if="busy || submitting" role="status">正在本地准备导出，完成后可选择范围和速度。不会重新识别骨架或新增姿态费用。</p>
        <template v-else-if="canPrepareExport">
          <p>导出前需要本地准备视频，不会重新识别骨架或新增姿态费用。</p>
          <button type="button" @click="generate(false)">重试本地准备导出</button>
        </template>
        <p v-else>原片已不可用，可下载已保存的复盘视频。</p>
        <a v-if="legacyUrl" :href="savedReplayDownloadUrl" download>下载已保存的复盘视频</a>
      </template>
    </WorkspaceSheet>
    <button v-if="sourceAvailable && state?.task?.status === 'failed' && !state?.vision_request_count && !state?.result_version" type="button" :disabled="submitting" @click="generate(false)">重试复盘</button>
    <p v-if="!sourceAvailable" class="range-label">原片已不可用，当前播放保留的旧视频。</p>
    <div v-if="busy" class="task-state" role="status">正在生成复盘… <button type="button" @click="cancel">停止</button></div>
    <p v-if="error || taskError" role="alert">{{ error || taskError }}</p>
  </section>
</template>

<script setup>
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { Download, DataAnalysis, Close } from '@element-plus/icons-vue'
import service from '../services/climbReplayService'
import { segmentDecision } from '../services/actionPlayback.js'
import { metricValue } from '../services/replayPresentation.js'
import ReplayVisualStage from './ReplayVisualStage.vue'
import { replayFrameGeometry } from '../services/replayFrameGeometry.js'
import { analysisFrame, currentVisualization } from '../services/replayAnalysisView.js'
import ReplayActionDetail from './ReplayActionDetail.vue'
import ReplayActionNotes from './ReplayActionNotes.vue'
import WorkspaceSheet from './ui/WorkspaceSheet.vue'
const correctionOpen=ref(false), timelinePage=ref(0)
const replayView=ref(null), statisticsOpen=ref(false)
function fullscreen() { if(document.fullscreenElement) document.exitFullscreen?.(); else replayView.value?.requestFullscreen?.() }
const timelineSize=5
const timelineGroups=computed(()=>groups.value.slice(timelinePage.value*timelineSize,(timelinePage.value+1)*timelineSize))
const props = defineProps({ job: { type: Object, required: true }, legacyUrl: { type: String, default: '' }, fallbackActions: { type: Array, default: () => [] }, analysisAuthorized: {type:Boolean,default:false} })
const visualStage = ref(null), video = computed(() => visualStage.value?.video)
const state = ref(null), selected = ref(null), speed = ref(.75), loop = ref(false)
const error = ref(''), submitting = ref(false), cloudConsent = ref(false)
const exportOpen = ref(false), exportScope = ref('full'), exportSpeed = ref(.75)
const exportContent = ref('video')
const currentTime = ref(0), seekingFeedback = ref(false)
const replayFrame = computed(() => sourceAvailable.value ? analysisFrame(props.job.result?.video || visualization.value?.video)
  : props.legacyUrl.includes('/comparison') || props.job.result?.overlay?.layout === 'split_analysis_right_v11' ? null : replayFrameGeometry(props.job.result))
const visualization = computed(() => currentVisualization(state.value?.result?.replay_visualization,props.job.result,state.value?.result?.center_of_mass_trajectory))
let timer, seekTimer, frameCallback, generation = 0, internalSeek = false, autoStarted = false
let pendingDownload = false, previousExportId = null
const sourceAvailable = computed(() => props.job.media?.source_video?.status === 'available')
const canPrepareExport = computed(() => sourceAvailable.value && props.job.status === 'succeeded')
const canExport = computed(() => Boolean(state.value?.result_version || canPrepareExport.value || props.legacyUrl))
const localGroups = computed(() => {
  const prepared = state.value?.result?.groups || []
  if (state.value?.result_version || state.value?.result?.segmentation_basis === 'significant_axis_displacement' || !props.fallbackActions.length) return prepared
  // Restore the saved action steps when a record predates organized actions.
  return props.fallbackActions.map((event, index, events) => {
    const start = event.seek_time_seconds
    const next = events.slice(index + 1).find(item => item.seek_time_seconds > start)?.seek_time_seconds
    return { id: event.key, start_seconds: start, end_seconds: Math.min(duration.value, Math.max(start + .1, next ?? duration.value)),
      description: event.supplementary_name || '动作片段', events: [] }
  }).filter(group => group.start_seconds >= 0 && group.end_seconds > group.start_seconds)
})
const metrics = computed(() => state.value?.result?.metrics || [])
const groups = computed(() => {
  const analyzed = state.value?.result?.ai_analysis?.actions || []
  return analyzed.length ? analyzed.map(row=>({...row,segment_id:row.id})) : localGroups.value
})
const duration = computed(() => state.value?.result?.source_duration_seconds || props.job.result?.video?.duration_seconds || 0)
const selectedIndex = computed(() => localGroups.value.findIndex(g => g.id === (selected.value?.group_id || selected.value?.id)))
const playbackGroups = computed(() => groups.value)
const playbackIndex = computed(() => playbackGroups.value.findIndex(g=>g.id===selected.value?.id))
const busy = computed(() => ['queued', 'running'].includes(state.value?.task?.status))
const exportBusy = computed(() => ['queued', 'running'].includes(state.value?.export?.status))
const taskError = computed(() => state.value?.task?.error || state.value?.export?.error)
const displayCost = computed(() => state.value?.vision_cost || state.value?.cost)
// Rebuild both panes from the retained original and saved analysis evidence.
const mediaUrl = computed(() => sourceAvailable.value ? service.mediaUrl(props.job.id, 'source-video')
  : state.value?.media_ready ? service.actionMediaUrl(props.job.id, state.value.result_version) : props.legacyUrl)
const downloadUrl = computed(() => service.actionMediaUrl(props.job.id, state.value?.export_media?.id, true, true))
const packageUrl = computed(() => service.actionPackageUrl(props.job.id, state.value?.result_version, Boolean(state.value?.export_media)))
const savedReplayDownloadUrl = computed(() => {
  if (!props.legacyUrl) return ''
  const url = new URL(props.legacyUrl, window.location.href)
  url.searchParams.set('download', 'true')
  return url.href
})
const clock = t => `${Math.floor((t || 0) / 60)}:${((t || 0) % 60).toFixed(1).padStart(4, '0')}`
function setSpeed() { if (video.value) video.value.playbackRate = speed.value }
function loaded() { setSpeed() }
function exitSegment() { selected.value = null; loop.value = false; speed.value = .75; setSpeed() }
async function play() { try { await video.value?.play() } catch { /* Native play control remains available. */ } }
function seek(time) {
  if (!video.value) return
  internalSeek = true; video.value.currentTime = time
}
function select(group) {
  if (!video.value) return
  selected.value = group
  setSpeed(); seek(group.start_seconds); play()
}
function step(offset) { const group = playbackGroups.value[playbackIndex.value + offset]; if (group) select(group) }
function tick() {
  if (video.value) currentTime.value = video.value.currentTime
  if (!video.value || video.value.seeking) return
  // Old retained videos may contain a summary tail. Stop at the original climbing end.
  if (!selected.value && duration.value > 0 && video.value.duration > duration.value + .05 && currentTime.value >= duration.value - .015) {
    video.value.pause(); seek(Math.max(0, duration.value - .02)); return
  }
  const decision = segmentDecision(selected.value, video.value.currentTime, { loop: loop.value })
  if (decision === 'repeat') { seek(selected.value.start_seconds); play() }
  else if (decision === 'pause') { video.value.pause() }
}
function onSeeking() {
  clearTimeout(seekTimer); seekingFeedback.value = true
  const ownSeek = internalSeek
  if (!ownSeek && segmentDecision(selected.value, video.value.currentTime, { seeking: true }) === 'exit') exitSegment()
}
function onSeeked() { currentTime.value = video.value?.currentTime || 0; internalSeek = false; seekTimer = setTimeout(() => { seekingFeedback.value = false }, 120) }
function onEnded() {
  if (selected.value) { if (loop.value) { seek(selected.value.start_seconds); play() } return }
}
function locateMetric(m) { select({ id: 'metric-stop', start_seconds: Math.max(0, m.start_seconds - .3), end_seconds: Math.min(duration.value, m.end_seconds + .4) }) }
function stopFrames() { if (frameCallback != null) video.value?.cancelVideoFrameCallback?.(frameCallback); frameCallback = null }
function startFrames() {
  stopFrames()
  if (!video.value?.requestVideoFrameCallback) return
  const next = () => { tick(); if (video.value && !video.value.paused) frameCallback = video.value.requestVideoFrameCallback(next) }
  frameCallback = video.value.requestVideoFrameCallback(next)
}
function onPlay() { startFrames() }
async function refresh(id, token) {
  try {
    const data = await service.actions(id)
    if (token !== generation) return
    state.value = data
    clearTimeout(timer)
    if (busy.value || exportBusy.value) timer = setTimeout(() => refresh(id, token), 1000)
    else if (!autoStarted && data.task?.status !== 'failed' && sourceAvailable.value && !data.result?.ai_analysis) {
      autoStarted = true
      if (props.analysisAuthorized && data.cloud_configured && !data.vision_request_count && !data.legacy_saved_vision_return) await generate(true)
      else if (!data.result_version) await generate(false)
    }
  } catch (e) { if (token === generation) error.value = e.response?.data?.detail || '无法读取复盘状态，请重新载入记录。' }
}
async function perform(fn) {
  const token = generation, id = props.job.id
  error.value = ''; submitting.value = true
  try { await fn(id); if (token === generation) await refresh(id, token) }
  catch (e) { if (token === generation) error.value = e.response?.data?.detail || '操作未完成，请重试。' }
  finally { if (token === generation) submitting.value = false }
}
function generate(cloud, reuse = false, replaceLegacy = false) { return perform(id => service.generateActions(id, { cloud_consent: cloud, consent_version: cloud ? state.value?.consent_version : null, budget_confirmed: cloud, ...(reuse ? { reuse_saved_commentary: true } : {}), ...(replaceLegacy ? {replace_legacy_return:true} : {}) })) }
function retryCommentary() { return perform(id => service.generateActions(id, { retry_saved_response: true })) }
function resumeAnalysis() { return state.value?.saved_commentary_available ? generate(false,true) : retryCommentary() }
function openExport() {
  exportOpen.value = !exportOpen.value
  if (exportOpen.value && !state.value?.result_version && canPrepareExport.value && !busy.value && !submitting.value) generate(false)
}
function cancel() { return perform(id => service.cancelActions(id)) }
function cancelExport() { pendingDownload=false; return perform(id => service.cancelActionExport(id)) }
function saveAction(payload) { return perform(id => service.reviewAction(id, { ...payload, result_version: state.value.result_version })) }
function undoAction() { return perform(id => service.undoActionReview(id, { result_version: state.value.result_version })) }
function locateEvidence(time) { if (video.value) { video.value.pause(); seek(time) } }
async function exportVideo() {
  previousExportId=state.value?.export_media?.id; pendingDownload=true
  await perform(id => service.exportActions(id, { result_version: state.value.result_version, scope: exportScope.value, group_id: exportScope.value === 'group' ? selected.value?.segment_id ? selected.value.group_id || null : selected.value?.id : null, ...(exportScope.value === 'group' && selected.value?.segment_id ? {segment_id:selected.value.segment_id} : {}), speed: exportSpeed.value }))
  if(error.value)pendingDownload=false
}
watch(()=>state.value?.export_media?.id,id=>{
  if(!pendingDownload || !id || id===previousExportId)return
  pendingDownload=false
  const link=document.createElement('a');link.href=exportContent.value==='package'?packageUrl.value:downloadUrl.value
  link.download=exportContent.value==='package'?'climb-replay-package.zip':'climb-replay.mp4'
  document.body.appendChild(link);link.click();link.remove()
})
watch(() => props.job.id, id => {
  autoStarted = false
  pendingDownload = false
  timelinePage.value=0;correctionOpen.value=false;generation++; clearTimeout(timer); stopFrames(); state.value = null; selected.value = null
  speed.value = .75; exportSpeed.value = .75; loop.value = false; cloudConsent.value = false; exportOpen.value = false; error.value = ''; submitting.value = false
  exportContent.value = 'video'; exportScope.value = 'full'
  currentTime.value = 0; seekingFeedback.value = false; internalSeek = false; clearTimeout(seekTimer)
  refresh(id, generation)
}, { immediate: true })
watch(playbackIndex,index=>{if(index>=0)timelinePage.value=Math.floor(index/timelineSize)})
watch(() => state.value?.task?.status, status => { if (status === 'failed') cloudConsent.value = false })
watch(() => state.value?.result_version, (next, previous) => {
  if (previous && next !== previous) {
    const updated = groups.value.find(g => g.id === selected.value?.id)
    if (updated) { selected.value = updated; video.value?.pause() }
    else exitSegment()
  }
})
watch(() => props.job, (next, previous) => {
  if (next.id === previous.id && (next.status !== previous.status
    || JSON.stringify(next.result) !== JSON.stringify(previous.result)
    || JSON.stringify(next.reviewed_segments) !== JSON.stringify(previous.reviewed_segments))) refresh(next.id, generation)
})
function pauseForHoldReview() {
  video.value?.pause()
  return Number(video.value?.currentTime || currentTime.value || 0)
}
onBeforeUnmount(() => { generation++; clearTimeout(timer); clearTimeout(seekTimer); stopFrames() })
defineExpose({ seekClip: select, pauseForHoldReview })
</script>

<style scoped>
@font-face { font-family: 'Replay Noto'; src: url('/fonts/ReplayNotoSC.woff2') format('woff2'); font-weight: 100 900; font-display: swap; }
.unified-replay { --replay-bg: var(--ui-surface, #fff); --replay-ink: var(--ui-ink, #1c1e21); --replay-muted: var(--ui-ink-muted, #696c72); --replay-accent: var(--ui-brand, #f4c430); color: var(--replay-ink); background: var(--replay-bg); font-family: 'Replay Noto', 'Noto Sans SC', 'Source Han Sans SC', 'Microsoft YaHei', sans-serif; overflow: hidden; }
.unified-stage { position: relative; background: #090a0b; width: 100%; margin: 0 auto; }
.replay-basic-statistics { position:absolute;z-index:5;right:8px;top:64px;width:min(420px,calc(100% - 16px));max-height:calc(100% - 76px);overflow:auto;box-sizing:border-box;padding:16px 24px;background:var(--replay-bg);color:var(--replay-ink);border-radius:8px;box-shadow:0 8px 24px #0004 }
.statistics-orb{width:44px;height:44px;min-height:44px;padding:0;border-radius:50%;background:#edcb52;color:#28230e;border:0}
.statistics-heading{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:12px}.statistics-heading h2{margin:0}.statistics-heading button{padding:0;width:44px;flex:none}
.replay-view:fullscreen{display:flex;flex-direction:column;justify-content:center;overflow:auto;background:var(--replay-bg);width:100%;height:100dvh}
.replay-view:fullscreen .unified-stage{flex:none}
.replay-basic-statistics h2 { margin:0 0 12px;font-size:14px;font-weight:600 }
.replay-basic-statistics dl { display:flex;flex-wrap:wrap;gap:16px 32px;margin:0 }
.replay-basic-statistics dt { color:var(--replay-muted);font-size:12px;margin-bottom:4px }
.replay-basic-statistics dd { margin:0;font-size:18px;font-variant-numeric:tabular-nums }
.replay-basic-statistics dd span { font-size:12px;color:var(--replay-muted) }
@media(max-width:600px){.replay-basic-statistics{padding:12px 16px}.replay-basic-statistics dl{gap:12px 24px}}
.locating :deep(video) { opacity: .82; }
.action-strip { padding: 12px 24px 0; }
.timeline-heading { display: flex; align-items: baseline; justify-content: space-between; gap: 12px; margin-bottom: 12px; }
.timeline-heading strong { font-size: 14px; font-weight: 600; }
.timeline-heading span { font-size: 12px; color: var(--replay-muted); }
.source-progress { position: relative; height: 3px; margin: 0 0 12px; background: var(--ui-surface-subtle, #f1efe9); }
.source-playhead { position: absolute; top: -3px; width: 3px; height: 9px; transform: translateX(-50%); border-radius: 2px; background: var(--ui-focus, #6b5000); pointer-events: none; }
.action-list { display: flex; gap: 8px; overflow-x: auto; padding: 3px 3px 10px; margin: 0 -3px; scroll-snap-type: x proximity; scrollbar-width: thin; scrollbar-color: var(--ui-line-strong, #c9c5bc) transparent; }
.action-list button { flex: 0 0 132px; min-height: 44px; display: grid; grid-template-columns: 24px minmax(0, 1fr); gap: 5px 8px; padding: 8px; text-align: left; scroll-snap-align: start; border: 1px solid var(--ui-line, #dedbd3); background: var(--replay-bg); }
.action-number { display: grid; place-items: center; width: 24px; height: 24px; border-radius: 6px; background: var(--ui-surface-subtle, #f1efe9); font-size: 12px; font-weight: 600; font-variant-numeric: tabular-nums; }
.action-label { align-self: center; overflow: hidden; white-space: nowrap; text-overflow: ellipsis; font-size: 13px; font-weight: 500; }
.action-list time { grid-column: 2; grid-row:1; color: var(--replay-muted); font-size: 11px; font-variant-numeric: tabular-nums; white-space: nowrap; }
.action-list button.selected { border-color: var(--replay-accent); background: var(--ui-brand-soft, #fff3b2); color: var(--ui-brand-ink, #2d2500); }
.action-list button.selected .action-number { background: var(--replay-accent); }
.action-list button.selected time { color: var(--ui-brand-ink, #2d2500); }
.replay-controls { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; padding: 10px 24px 20px; }
.segment-controls { display: flex; flex-wrap: wrap; gap: 6px; width: 100%; margin-bottom: 4px; }
.speed-control { display: inline-flex; align-items: center; gap: 8px; margin-right: auto; font-size: 13px; color: var(--replay-muted); }
.replay-controls > label:has(input) { display: inline-flex; align-items: center; gap: 6px; font-size: 13px; }
button, select, a { font: inherit; color: inherit; }
button, select { min-height: 44px; border: 1px solid var(--ui-line, #dedbd3); border-radius: 8px; background: var(--replay-bg); padding: 8px 14px; cursor: pointer; font-size: 13px; }
button { display: inline-flex; align-items: center; justify-content: center; gap: 7px; }
button svg { width: 16px; height: 16px; }
button:hover:not(:disabled), select:hover { background: var(--ui-surface-subtle, #f1efe9); border-color: var(--ui-line-strong, #c9c5bc); }
button:disabled { opacity: .5; cursor: not-allowed; }
button:focus-visible, select:focus-visible, summary:focus-visible, a:focus-visible { outline: 2px solid var(--ui-focus, #6b5000); outline-offset: 3px; }
input { accent-color: var(--replay-accent); }
.range-label, .organize-prompt, .task-state, [role='alert'], .export-options { margin: 0; padding: 12px 24px 20px; line-height: 1.6; font-size: 13px; }
.organize-prompt { display: flex; align-items: center; justify-content: space-between; gap: 16px; }
.organize-prompt p { margin: 0; color: var(--replay-muted); }
.organize-prompt button { flex-shrink: 0; }
[role='alert'] { color: var(--ui-danger, #bd4343); }
.range-label { color: var(--replay-muted); font-variant-numeric: tabular-nums; }
.export-options { display: flex; flex-wrap: wrap; align-items: center; gap: 12px; }
.export-options p { width: 100%; margin: 0; }
.export-options a { text-underline-offset: 4px; }
.export-content { display: grid; gap: 8px; min-width: 0; margin: 0; padding: 12px; border: 1px solid var(--ui-line, #dedbd3); border-radius: 8px; }
.export-content label { display: flex; align-items: center; gap: 8px; min-height: 44px; cursor: pointer; }
.replay-more { background: var(--ui-surface-raised, #fbfaf7); color: var(--replay-ink); padding: 0 24px; border-top: 1px solid var(--ui-line, #dedbd3); font-size: 13px; }
.replay-more[open] { padding-bottom: 20px; }
.replay-more > summary { min-height: 56px; align-content: center; cursor: pointer; font-weight: 500; }
.replay-more > summary span { margin-left: 12px; font-weight: 400; color: var(--replay-muted); font-size: 12px; }
.local-check { line-height: 1.6; max-width: 65ch; }
.local-check button, .replay-more > button { display: block; margin: 12px 0; }
.action-correction { padding: 0 16px 12px; }
.action-correction > summary { min-height: 44px; display: list-item; align-content: center; cursor: pointer; color: var(--replay-muted); }
::selection { background: var(--replay-accent); color: #15200b; }
@media (max-width: 600px) { .action-strip { padding: 16px 16px 0; } .replay-controls { padding: 8px 16px 16px; } .action-list button { flex-basis: 120px; } .range-label, .organize-prompt, .task-state, [role='alert'], .export-options { padding: 12px 16px 16px; } .replay-more { padding: 0 16px; } .organize-prompt { align-items: flex-start; } .timeline-heading span { font-size: 11px; } }

</style>
