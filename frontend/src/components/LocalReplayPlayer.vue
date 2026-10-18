<template>
  <section class="unified-replay" aria-label="视频复盘">
    <div ref="replayView" class="replay-view">
    <div class="unified-stage" :class="{ locating: seekingFeedback }" :aria-busy="seekingFeedback">
      <ReplayVisualStage ref="visualStage" :src="mediaUrl" :frame="replayFrame" :holds="job.result?.holds || []" :contacts="visualization?.contacts || job.result?.attempt?.contacts || []" :summary="false" :original-source="sourceAvailable" :visualization="visualization"
        :selection="sourceAvailable ? pictureSelection : null" :background-url="backgroundUrl" :background-info="state?.background"
        @background-ready="backgroundLoaded=true" @background-error="backgroundLoaded=false; error='无人背景无法载入，请重新载入记录。'"
        @timeupdate="tick" @seeking="onSeeking" @seeked="onSeeked" @ended="onEnded" @loadedmetadata="loaded"
        @play="onPlay" @pause="stopFrames" @fullscreen="fullscreen" @error="error = '视频无法播放，请重新载入记录。'">
        <template #tools>
          <button v-if="metrics.length" type="button" class="statistics-orb" aria-label="基础数据统计" :aria-expanded="statisticsOpen" aria-controls="replay-statistics" @click="statisticsOpen=!statisticsOpen"><DataAnalysis aria-hidden="true" /></button>
          <section v-if="statisticsOpen && metrics.length" id="replay-statistics" class="replay-basic-statistics" aria-label="基础数据统计" @keydown.esc.stop="statisticsOpen=false">
            <div class="statistics-heading"><h2>基础数据统计</h2><button type="button" aria-label="关闭基础数据" @click="statisticsOpen=false"><Close aria-hidden="true" /></button></div>
            <dl><div v-for="metric in metrics" :key="metric.key"><dt>{{ metric.label }}</dt><dd>{{ metricValue(metric) }} <span>{{ metric.unit }}</span><button v-if="metric.key === 'longest_still' && Number.isFinite(metric.start_seconds)" type="button" aria-label="跳转到最长姿态停留" @click="locateMetric(metric)">跳转</button></dd></div></dl>
          </section>
        </template>
      </ReplayVisualStage>
    </div>
    <ReplayPictureChoices v-if="canChangePictures" v-model="pictureSelection" :background-ready="backgroundReady" :background-message="backgroundMessage" />
    <div class="replay-controls">
      <div v-if="selected" class="segment-controls">
        <button type="button" :disabled="playbackIndex <= 0" @click="step(-1)">上一段</button>
        <button type="button" @click="select(selected, false)">重看</button>
        <button type="button" :disabled="playbackIndex < 0 || playbackIndex >= playbackGroups.length - 1" @click="step(1)">下一段</button>
        <button type="button" @click="exitSegment">整段观看</button>
      </div>
      <label class="speed-control">速度 <select v-model.number="speed" aria-label="播放速度" @change="setSpeed"><option :value=".5">0.5×</option><option :value=".75">0.75×</option><option :value="1">1×</option></select></label>
      <label v-if="selected"><input v-model="loop" type="checkbox" />循环</label>
      <button type="button" :disabled="!canExport" :aria-expanded="exportOpen" @click="openExport"><Download aria-hidden="true" />导出</button>

    </div>
    </div>
    <div v-if="sourceAvailable && skeletonOnly && pictureSelection.show_diagram" class="trajectory-start-control">
      <p v-if="!Number.isFinite(trajectoryWindow?.start_seconds)">尚未确定攀爬起点。请将视频定位到开始攀爬的位置，点击“从这里开始”。</p>
      <p v-else>重心路线从 {{ clock(trajectoryWindow.start_seconds) }} 开始{{ trajectoryWindow.status === 'user_confirmed' ? '（已手动定位）' : '（自动定位，可调整）' }}。</p>
      <button type="button" :disabled="submitting || busy || exportBusy || !video || currentTime >= duration" @click="markTrajectoryStart">从这里开始 · {{ clock(currentTime) }}</button>
      <button v-if="trajectoryWindow?.status === 'user_confirmed'" type="button" :disabled="submitting || busy || exportBusy" @click="resetTrajectoryStart">恢复自动判断</button>
    </div>
    <p v-if="sourceAvailable && pictureSelection.show_diagram" class="range-label">白点：估算重心 · 轨迹：重心移动路线</p>
    <WorkspaceSheet v-if="exportOpen" title="导出复盘" @close="exportOpen=false">
      <template v-if="state?.result_version">
        <ReplayPictureChoices v-model="exportSelection" include-data :background-ready="backgroundReady" :background-message="backgroundMessage" :disabled="exportBusy || submitting" />
        <label v-if="hasExportPictures">范围 <select v-model="exportScope" aria-label="导出范围" :disabled="exportBusy || submitting"><option value="full">完整复盘</option><option value="group" :disabled="!selected || (selectedIndex < 0 && !selected.segment_id)">当前动作</option></select></label>
        <label v-if="hasExportPictures">速度 <select v-model.number="exportSpeed" aria-label="导出速度" :disabled="exportBusy || submitting"><option :value=".75">0.75×</option><option :value=".5">0.5×</option><option :value="1">1×</option></select></label>
        <p v-if="hasExportPictures">{{ exportScope === 'full' ? `0:00–${clock(duration)}` : `${clock(selected?.start_seconds)}–${clock(selected?.end_seconds)} · 仅当前动作` }} · {{ exportSpeed }}× · 导出所选画面，无声音、评语字幕或统计浮层。</p>
        <button type="button" :disabled="exportBusy || submitting || !validExportSelection || (hasExportPictures && exportScope === 'group' && selectedIndex < 0 && !selected?.segment_id)" @click="exportVideo">{{ exportBusy ? '正在导出…' : '导出文件' }}</button>
        <button v-if="exportBusy" type="button" @click="cancelExport">停止导出</button>
        <a v-if="matchingExport" :href="completedDownloadUrl" :download="state.export_media.include_data ? 'climb-replay-package.zip' : 'climb-replay.mp4'">{{ state.export_media.include_data ? '下载资料包' : '下载复盘视频' }}</a>
        <p v-if="exportSelection.include_data">资料仅含运动数据（时间、身体角度、估算重心等）、提示词与时间说明，不含原片、截图或声音。仅选资料时无需生成视频。</p>
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
import WorkspaceSheet from './ui/WorkspaceSheet.vue'
import ReplayPictureChoices from './ReplayPictureChoices.vue'
const replayView=ref(null), statisticsOpen=ref(false)
function fullscreen() { if(document.fullscreenElement) document.exitFullscreen?.(); else replayView.value?.requestFullscreen?.() }
const props = defineProps({ job: { type: Object, required: true }, legacyUrl: { type: String, default: '' }, fallbackActions: { type: Array, default: () => [] }, analysisAuthorized: {type:Boolean,default:false} })
const visualStage = ref(null), video = computed(() => visualStage.value?.video)
const state = ref(null), selected = ref(null), speed = ref(.75), loop = ref(false)
const error = ref(''), submitting = ref(false), cloudConsent = ref(false)
const exportOpen = ref(false), exportScope = ref('full'), exportSpeed = ref(.75)
const defaultPictures=()=>({show_skeleton:false,show_human:true,show_diagram:true})
const pictureSelection=ref(defaultPictures()),exportSelection=ref({...defaultPictures(),include_data:false})
const backgroundLoaded=ref(false)
const canChangePictures=computed(()=>sourceAvailable.value && Boolean(state.value?.result_version) && props.job.status==='succeeded')
const backgroundReady=computed(()=>state.value?.background?.status==='ready' && backgroundLoaded.value)
const backgroundMessage=computed(()=>state.value?.background?.status==='ready' ? (backgroundLoaded.value?'':'正在载入无人背景…') : state.value?.background?.message || '无人背景尚不可用。')
const backgroundUrl=computed(()=>state.value?.background?.status==='ready' ? service.replayBackgroundUrl(props.job.id,state.value.background.binding) : '')
const hasExportPictures=computed(()=>exportSelection.value.show_skeleton || exportSelection.value.show_human || exportSelection.value.show_diagram)
const validExportSelection=computed(()=>(hasExportPictures.value || exportSelection.value.include_data) && !(exportSelection.value.show_skeleton && !exportSelection.value.show_human && !backgroundReady.value))
const currentTime = ref(0), seekingFeedback = ref(false)
const replayFrame = computed(() => sourceAvailable.value ? analysisFrame(props.job.result?.video || visualization.value?.video,pictureSelection.value)
  : props.legacyUrl.includes('/comparison') || props.job.result?.overlay?.layout === 'split_analysis_right_v11' ? null : replayFrameGeometry(props.job.result))
const visualization = computed(() => currentVisualization(state.value?.result?.replay_visualization,props.job.result,state.value?.result?.center_of_mass_trajectory))
const skeletonOnly = computed(() => Boolean(props.job.skeleton_only || props.job.result?.skeleton_only || state.value?.result?.skeleton_only))
const trajectoryWindow = computed(() => visualization.value?.center_of_mass_trajectory?.climbing_window)
let timer, seekTimer, frameCallback, generation = 0, internalSeek = false, autoStarted = false
let pendingDownload = false, backgroundRequested = false
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
const groups = computed(() => localGroups.value)
const duration = computed(() => state.value?.result?.source_duration_seconds || props.job.result?.video?.duration_seconds || 0)
const selectedIndex = computed(() => localGroups.value.findIndex(g => g.id === (selected.value?.group_id || selected.value?.id)))
const playbackGroups = computed(() => groups.value)
const playbackIndex = computed(() => playbackGroups.value.findIndex(g=>g.id===selected.value?.id))
const busy = computed(() => ['queued', 'running'].includes(state.value?.task?.status))
const exportBusy = computed(() => ['queued', 'running'].includes(state.value?.export?.status))
const taskError = computed(() => state.value?.export?.error || (!state.value?.vision_request_count && !state.value?.result_version ? state.value?.task?.error : ''))
const displayCost = computed(() => state.value?.vision_cost || state.value?.cost)
// Rebuild both panes from the retained original and saved analysis evidence.
const mediaUrl = computed(() => sourceAvailable.value ? service.mediaUrl(props.job.id, 'source-video')
  : state.value?.media_ready ? service.actionMediaUrl(props.job.id, state.value.result_version) : props.legacyUrl)
const downloadUrl = computed(() => service.actionMediaUrl(props.job.id, state.value?.export_media?.id, true, true))
const mediaHasPictures=media=>media && (media.show_skeleton || media.show_human || media.show_diagram)
const completedDownloadUrl = computed(() => state.value?.export_media?.include_data
  ? service.actionPackageUrl(props.job.id,state.value.result_version,true,!mediaHasPictures(state.value.export_media),state.value.export_media.id) : downloadUrl.value)
const matchingExport=computed(()=>{
  const media=state.value?.export_media
  return media && ['show_skeleton','show_human','show_diagram','include_data'].every(k=>media[k]===exportSelection.value[k])
    && (!hasExportPictures.value || (media.speed===exportSpeed.value && media.scope===exportScope.value
    && (exportScope.value!=='group' || media.group_id===(selected.value?.group_id || selected.value?.id))))
})
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
function locateMetric(m) {
  selected.value = null
  loop.value = false
  statisticsOpen.value = false
  seek(Math.max(0, Math.min(duration.value, m.start_seconds)))
  play()
}
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
    if (busy.value || exportBusy.value || data.background?.status==='running') timer = setTimeout(() => refresh(id, token), 1000)
    else if (!autoStarted && data.task?.status !== 'failed' && sourceAvailable.value) {
      autoStarted = true
      if (!data.result_version) await generate(false)
    }
    if(data.result_version && data.background?.status==='not_started' && !backgroundRequested && sourceAvailable.value){
      backgroundRequested=true
      service.prepareReplayBackground(id).then(()=>{if(token===generation)refresh(id,token)}).catch(()=>{
        if(token===generation && state.value)state.value.background={status:'unavailable',message:'无人背景检查未完成，请重新载入记录后重试。'}
      })
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
function generate() { return perform(id => service.generateActions(id, { cloud_consent: false })) }
function markTrajectoryStart() {
  video.value?.pause()
  const time = video.value?.currentTime ?? currentTime.value
  return perform(id => service.setTrajectoryStart(id, time))
}
function resetTrajectoryStart() { return perform(id => service.setTrajectoryStart(id, null)) }
function openExport() {
  exportOpen.value = !exportOpen.value
  if(exportOpen.value)exportSelection.value={...pictureSelection.value,include_data:false}
  if (exportOpen.value && !state.value?.result_version && canPrepareExport.value && !busy.value && !submitting.value) generate(false)
}
function cancel() { return perform(id => service.cancelActions(id)) }
function cancelExport() { pendingDownload=false; return perform(id => service.cancelActionExport(id)) }
async function exportVideo() {
  if(!validExportSelection.value)return
  pendingDownload=true
  const scope=hasExportPictures.value?exportScope.value:'full'
  await perform(id => service.exportActions(id, { result_version: state.value.result_version, ...exportSelection.value, scope, group_id: scope === 'group' ? selected.value?.segment_id ? selected.value.group_id || null : selected.value?.id : null, ...(scope === 'group' && selected.value?.segment_id ? {segment_id:selected.value.segment_id} : {}), speed: hasExportPictures.value?exportSpeed.value:1 }))
  if(error.value)pendingDownload=false
  else finishDownload()
}
function finishDownload(){
  if(!pendingDownload || !matchingExport.value || state.value?.export?.status!=='succeeded')return
  pendingDownload=false
  const link=document.createElement('a');link.href=completedDownloadUrl.value
  link.download=state.value.export_media.include_data?'climb-replay-package.zip':'climb-replay.mp4'
  document.body.appendChild(link);link.click();link.remove()
}
watch(()=>[state.value?.export_media?.id,state.value?.export?.status],()=>{
  if(state.value?.export?.status==='failed')pendingDownload=false
  else finishDownload()
})
watch(() => props.job.id, id => {
  autoStarted = false
  pendingDownload = false
  backgroundRequested=false; backgroundLoaded.value=false
  pictureSelection.value=defaultPictures();exportSelection.value={...defaultPictures(),include_data:false}
  generation++; clearTimeout(timer); stopFrames(); state.value = null; selected.value = null
  speed.value = .75; exportSpeed.value = .75; loop.value = false; cloudConsent.value = false; exportOpen.value = false; error.value = ''; submitting.value = false
  exportScope.value = 'full'
  currentTime.value = 0; seekingFeedback.value = false; internalSeek = false; clearTimeout(seekTimer)
  refresh(id, generation)
}, { immediate: true })
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
onBeforeUnmount(() => { generation++; clearTimeout(timer); clearTimeout(seekTimer); stopFrames() })
defineExpose({ seekClip: select })
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
.replay-basic-statistics dd button { margin-left:10px;min-height:32px;padding:4px 10px;font-size:12px;vertical-align:middle }
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
.trajectory-start-control { padding: 0 24px 12px; font-size: 13px; line-height: 1.6; }
.trajectory-start-control p { margin: 0 0 8px; }
.trajectory-start-control button { margin-right: 8px; }
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
