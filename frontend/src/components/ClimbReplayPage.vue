<template>
  <section class="replay-page" aria-labelledby="replay-title">
    <header class="replay-heading">
      <div>
        <h1 id="replay-title">AI 复盘</h1>
        <p>上传视频，查看动作与关键帧。</p>
      </div>
      <span class="prototype-badge">技术验证</span>
    </header>

    <div class="replay-workspace" :class="{ 'review-mode': result }">
      <div class="video-column">
        <template v-if="!playbackUrl">
        <div
          v-if="!isBusy"
          class="video-drop"
          :class="{ dragging: isDragging }"
          role="button"
          tabindex="0"
          @click="openPicker"
          @keydown.enter="openPicker"
          @keydown.space.prevent="openPicker"
          @dragenter.prevent="isDragging = true"
          @dragover.prevent="isDragging = true"
          @dragleave.prevent="isDragging = false"
          @drop.prevent="onDrop"
        >
          <VideoCamera class="drop-icon" />
          <strong>选择攀爬视频</strong>
          <span>MP4、MOV 等常见视频 · 系统自动转码和压缩 · 单文件不超过 500 MB</span>
          <button type="button" class="secondary-button">浏览文件</button>
        </div>

        <div v-if="!isBusy && testVideoCases.length" class="test-video-cases">
          <div class="test-video-heading">
            <span class="test-video-mark" aria-hidden="true"><VideoCamera /></span>
            <div><strong>本地测试案例</strong><p>仅用于本机验收，不会随生产发布。</p></div>
          </div>
          <button
            v-for="item in testVideoCases"
            :key="item.id"
            type="button"
            class="test-video-case"
            :disabled="Boolean(loadingTestCaseId)"
            @click="useTestVideo(item)"
          >
            <span><strong>{{ item.label }}</strong><small>{{ item.description }} · {{ formatBytes(item.size_bytes) }}</small></span>
            <Loading v-if="loadingTestCaseId === item.id" />
            <b v-else>载入</b>
          </button>
        </div>
        </template>

        <div v-else class="playback-review" :class="{ 'has-action-focus': actionEvents.length }">
          <div class="video-stage">
            <div class="video-canvas">
              <video
                ref="videoElement"
                :src="playbackUrl"
                controls
                playsinline
                preload="metadata"
                @timeupdate="updatePlaybackEvidence"
                @loadedmetadata="handlePlaybackLoaded"
                @seeked="updatePlaybackEvidence"
                @error="handlePlaybackError"
              />
              <div v-if="playerMode === 'interactive' && result" class="hold-overlay" aria-hidden="true">
                <span
                  v-for="hold in showHolds ? (result.holds || []) : []"
                  :key="hold.id"
                  class="hold-box"
                  :style="holdStyle(hold)"
                ><b>{{ hold.id }}</b></span>
                <svg v-if="showPose && currentPose" class="pose-overlay" viewBox="0 0 100 100" preserveAspectRatio="none">
                  <line
                    v-for="segment in skeletonSegments"
                    :key="segment.key"
                    :x1="segment.x1"
                    :y1="segment.y1"
                    :x2="segment.x2"
                    :y2="segment.y2"
                    vector-effect="non-scaling-stroke"
                  />
                  <circle
                    v-for="point in posePoints"
                    :key="point.key"
                    :cx="point.x"
                    :cy="point.y"
                    r="0.75"
                    vector-effect="non-scaling-stroke"
                  />
                </svg>
                <div v-if="showEvents && activeContactEvents.length" class="contact-badges">
                  <span v-for="event in activeContactEvents" :key="event.key">{{ limbNames[event.limb] }} → 岩点 {{ event.hold_id }}</span>
                </div>
                <span v-if="showPose && currentPose" class="pose-evidence" :class="{ nearby: !currentPoseExact }">{{ poseEvidenceLabel }}</span>
              </div>
            </div>
            <button v-if="!isBusy" type="button" class="replace-video" @click="openPicker">更换视频</button>
          </div>

          <aside v-if="activeAction" class="action-focus" aria-label="当前动作">
            <div class="action-focus-head">
              <strong>当前动作</strong>
              <span><b>{{ String(activeAction.step).padStart(2, '0') }}</b> / {{ String(actionEvents.length).padStart(2, '0') }}</span>
            </div>
            <div class="action-focus-name">
              <span>{{ String(activeAction.step).padStart(2, '0') }}</span>
              <div>
                <strong>{{ limbNames[activeAction.limb] || '手脚' }}</strong>
                <p>{{ activeAction.supplementary_name }}</p>
                <small>{{ formatClock(activeAction.seek_time_seconds) }}</small>
              </div>
            </div>
            <div class="action-focus-actions">
              <button type="button" :disabled="activeActionIndex <= 0" @click="stepAction(-1)"><ArrowLeft /><span>上一个</span></button>
              <button type="button" class="primary" @click="replayActiveAction"><RefreshRight /><span>重看</span></button>
              <button type="button" :disabled="activeActionIndex >= actionEvents.length - 1" @click="stepAction(1)"><ArrowRight /><span>下一个</span></button>
            </div>
          </aside>
        </div>
        <div v-if="playbackUrl && result" class="player-tools">
          <div class="player-options">
            <div v-if="activeJob?.id" class="playback-switch" role="group" aria-label="播放版本">
              <button
                type="button"
                :class="{ active: playbackKind === 'overlay' }"
                :disabled="!replayVideoAvailable"
                :aria-pressed="playbackKind === 'overlay'"
                @click="switchPlayback('overlay')"
              >复盘视频</button>
              <button
                type="button"
                :class="{ active: playbackKind === 'source' }"
                :disabled="!sourcePlayable"
                :aria-pressed="playbackKind === 'source'"
                @click="switchPlayback('source')"
              >原视频</button>
            </div>
            <div v-if="playerMode === 'interactive'" class="layer-controls" aria-label="叠加层开关">
              <label><input v-model="showHolds" type="checkbox" />岩点</label>
              <label><input v-model="showPose" type="checkbox" />采样骨架</label>
              <label><input v-model="showEvents" type="checkbox" />接触事件</label>
            </div>
            <p v-else-if="playerMode === 'rendered'">当前播放：复盘视频</p>
          </div>
          <a v-if="replayVideoAvailable" class="export-action" :href="replayDownloadUrl">导出复盘视频</a>
        </div>
        <nav v-if="playbackUrl && actionEvents.length" class="event-timeline" aria-label="动作顺序">
          <div class="event-timeline-heading">
            <strong>动作顺序</strong>
            <span>点一下定位</span>
          </div>
          <ol>
            <li v-for="event in actionEvents" :key="event.key">
              <button
                type="button"
                :class="{ current: event.key === activeActionKey, reached: playbackTime >= event.seek_time_seconds }"
                :aria-current="event.key === activeActionKey ? 'step' : undefined"
                :aria-label="actionAriaLabel(event)"
                @click="seekToEvent(event)"
              >
                <span>{{ String(event.step).padStart(2, '0') }}</span>
                <strong>{{ limbNames[event.limb] || '手脚' }}</strong>
                <small>{{ event.supplementary_name }}</small>
              </button>
            </li>
          </ol>
        </nav>
        <input ref="fileInput" class="visually-hidden" type="file" accept="video/mp4,video/quicktime,video/x-m4v,video/webm,video/3gpp,video/3gpp2,video/x-matroska,.mp4,.mov,.m4v,.webm,.3gp,.3g2,.mkv" @change="onFileChange" />

        <div v-if="activeJob" class="analysis-state" :class="activeJob.status" aria-live="polite">
          <div class="state-copy">
            <span class="state-mark"><Loading v-if="isBusy" /><CircleCheck v-else-if="activeJob.status === 'succeeded'" /><Warning v-else /></span>
            <div>
              <strong>{{ statusTitle }}</strong>
              <p>{{ statusDetail }}</p>
            </div>
            <b v-if="isBusy">{{ activeJob.progress || 0 }}%</b>
          </div>
          <div v-if="isBusy" class="progress-track"><i :style="{ width: `${activeJob.progress || 0}%` }" /></div>
          <div v-if="analysisEvidence" class="run-summary" aria-label="本次处理计量摘要">
            <span>{{ formatNumber(analysisEvidence.sampling?.effective_fps) }} FPS 抽帧</span>
            <span>姿态 {{ analysisUsage.successful_pose_frames || 0 }}/{{ analysisUsage.planned_requests || 0 }} 帧</span>
            <span>估算 {{ formatCost(analysisCost.estimated_amount) }}</span>
            <span>{{ formatDuration(analysisTimings.total) }}</span>
          </div>
          <div v-if="['failed', 'cancelled'].includes(activeJob.status) && !isJobDeleting" class="state-actions">
            <button v-if="sourceAvailable" type="button" class="secondary-button" :disabled="!sampleConsent || !consentPolicy" @click="retryJob">重新分析</button>
            <p v-else>原视频已删除，这次复盘不能重新分析。</p>
          </div>
          <div class="media-retention">
            <div class="media-row">
              <div><strong>原视频</strong><p>{{ sourceRetentionLabel }}</p></div>
              <button v-if="sourceAvailable && !isBusy" type="button" class="text-action" :disabled="isDeleting || isJobDeleting" @click="deleteSourceVideo">仅删除原视频</button>
            </div>
            <div v-if="overlayMedia" class="media-row">
              <div><strong>叠加视频</strong><p>{{ overlayRetentionLabel }}</p></div>
              <div v-if="overlayAvailable" class="media-actions">
                <a class="text-action" :href="storedOverlayDownloadUrl">导出</a>
                <button type="button" class="text-action" :disabled="isDeleting || isJobDeleting" @click="deleteOverlayVideo">删除叠加视频</button>
              </div>
            </div>
            <div class="media-record-actions">
              <button type="button" class="text-action destructive" :disabled="isDeleting || isJobDeleting" @click="deleteEntireReplay">{{ isJobDeleting ? '正在删除整次记录' : '删除整次记录' }}</button>
            </div>
          </div>
        </div>

        <details v-if="analysisEvidence" class="analysis-evidence">
          <summary>处理记录与费用估算</summary>
          <dl>
            <div><dt>处理链路</dt><dd>本地岩点 · {{ analysisEvidence.provider?.service || '人体姿态服务' }}（{{ analysisEvidence.provider?.region || '地域待确认' }}）</dd></div>
            <div><dt>抽帧计划</dt><dd>{{ formatNumber(analysisEvidence.sampling?.effective_fps) }} FPS · 计划 {{ analysisUsage.planned_requests || 0 }} 帧</dd></div>
            <div><dt>接口请求</dt><dd>实际 {{ analysisUsage.actual_requests || 0 }} 次 · 成功 {{ analysisUsage.successful_requests || 0 }} · 失败 {{ analysisUsage.failed_requests || 0 }}</dd></div>
            <div><dt>姿态结果</dt><dd>有效 {{ analysisUsage.successful_pose_frames || 0 }} 帧 · 无姿态 {{ analysisUsage.responses_without_pose || 0 }} · 解码失败 {{ analysisUsage.decode_failed_frames || 0 }} · 未处理 {{ analysisUsage.unprocessed_frames || 0 }}</dd></div>
            <div><dt>费用估算</dt><dd>{{ formatCost(analysisCost.estimated_amount) }}（{{ formatCost(analysisCost.unit_price) }}/成功请求）</dd></div>
            <div><dt>总耗时</dt><dd>{{ formatDuration(analysisTimings.total) }} · 姿态 {{ formatDuration(analysisTimings.pose) }} · 叠加视频 {{ formatDuration(analysisTimings.overlay) }}</dd></div>
            <div><dt>版本</dt><dd>{{ analysisEvidence.pipeline_version }} · 岩点 {{ analysisEvidence.models?.holds?.version || '尚未完成' }} · API {{ analysisEvidence.provider?.api_version || '待确认' }}</dd></div>
          </dl>
          <p>{{ analysisCost.basis }}</p>
        </details>

        <section v-if="result" class="result-report" aria-labelledby="result-title">
          <div class="result-summary">
            <div>
              <h2 id="result-title">本次复盘</h2>
              <p>{{ result.attempt?.topped_out ? '识别到双手稳定控制顶点' : '暂未确认完攀' }}</p>
            </div>
            <strong>{{ elapsedLabel }}</strong>
          </div>

          <div class="sequence-block">
            <h3>岩点使用顺序</h3>
            <div v-if="result.attempt?.sequence?.length" class="hold-sequence">
              <template v-for="(hold, index) in result.attempt.sequence" :key="`${hold}-${index}`">
                <span>{{ hold }}</span><ArrowRight v-if="index < result.attempt.sequence.length - 1" />
              </template>
            </div>
            <p v-else class="empty-result">没有识别到稳定的手脚接触。</p>
          </div>

          <div class="limb-table">
            <div v-for="item in limbRows" :key="item.key">
              <span>{{ item.label }}</span>
              <strong>{{ item.seconds }}</strong>
              <small>{{ item.holds }}</small>
            </div>
          </div>

          <details v-if="result.warnings?.length" class="review-notes">
            <summary>查看识别说明</summary>
            <ul><li v-for="warning in result.warnings" :key="warning">{{ warning }}</li></ul>
          </details>
        </section>
      </div>

      <aside v-if="!result" class="setup-panel" aria-label="分析设置">
        <div>
          <h2>准备分析</h2>
          <p>画面尽量包含整面墙与攀爬者全身，手机固定不移动。</p>
        </div>

        <fieldset>
          <legend>线路颜色</legend>
          <div class="color-options">
            <label v-for="color in colors" :key="color.value" :class="{ selected: routeColor === color.value }">
              <input v-model="routeColor" type="radio" name="route-color" :value="color.value" />
              <i :style="{ background: color.hex }" />
              <span>{{ color.value }}</span>
            </label>
          </div>
        </fieldset>

        <fieldset class="retention-options">
          <legend>原视频保留方式</legend>
          <label :class="{ selected: retentionMode === 'delete_after_processing' }">
            <input v-model="retentionMode" type="radio" name="retention-mode" value="delete_after_processing" :disabled="isBusy || isDeleting" />
            <span><strong>分析后自动删除</strong><small>成功后 24 小时内删除；失败或取消后保留 72 小时，方便重试。</small></span>
          </label>
          <label :class="{ selected: retentionMode === 'keep_private_original' }">
            <input v-model="retentionMode" type="radio" name="retention-mode" value="keep_private_original" :disabled="isBusy || isDeleting" />
            <span><strong>私密保留原视频</strong><small>仅当前账号可见，直到你手动删除。</small></span>
          </label>
        </fieldset>

        <label class="privacy-check">
          <input v-model="sampleConsent" type="checkbox" :disabled="!consentPolicy || isBusy || isDeleting" />
          <span>我同意本次处理：上传的视频在本系统整理为分析副本并按上方选择清理，上传的原始文件在转换成功后从服务器删除；人体姿态分析会把降帧后的单张画面发送至{{ consentPolicy?.provider || '指定姿态服务' }}，岩点在服务器本地识别。重试时需要重新同意。</span>
        </label>
        <p v-if="consentPolicy" class="consent-meta">{{ consentPolicy.service }} · {{ consentPolicy.region }} · 告知版本 {{ consentPolicy.version }}</p>
        <button v-if="activeConsentGranted" type="button" class="consent-action" @click="withdrawConsent">撤回本次授权</button>

        <section v-if="selectedFile" class="video-preflight" aria-label="视频处理说明">
          <div class="video-preflight__head"><strong>上传后由系统处理视频</strong><span>{{ videoMeta ? formatVideoMeta(videoMeta) : formatBytes(selectedFile.size) }}</span></div>
          <p>完整文件会上传到本系统，随后在后台自动修正方向、裁剪、降帧并转成不含原音频的 H.264 MP4；分析副本不超过 1920×1080（支持竖屏）、200 MB。手机里的原文件不会修改，只有抽样画面会发送给上述姿态服务。</p>
          <div v-if="videoMeta?.duration > MAX_VIDEO_SECONDS" class="video-trim">
            <strong>默认分析前 90 秒，也可以在这里调整片段</strong>
            <p>选择片段只改变本系统的分析范围，上传的仍是完整文件。</p>
            <div class="video-trim__fields">
              <label>开始 <input v-model.number="trimStartSeconds" type="number" min="0" :max="Math.max(0, videoMeta.duration - 1)" step="0.1" /></label>
              <label>结束 <input v-model.number="trimEndSeconds" type="number" :min="trimStartSeconds + 0.1" :max="videoMeta.duration" step="0.1" /></label>
            </div>
            <p class="video-trim__status" :class="{ invalid: !trimIsValid }">当前片段 {{ formatSeconds(trimDuration) }}<span v-if="!trimIsValid">，请选择不超过 90 秒的范围</span></p>
          </div>
          <p v-if="!videoMeta">手机浏览器无法预览此编码。仍可上传，服务器会读取视频；超过 90 秒时默认分析前 90 秒。如服务器也无法解码，任务会显示具体原因。</p>
        </section>

        <button type="button" class="primary-action" :disabled="!canSubmit" @click="submit">
          <Loading v-if="isBusy || isSubmitting" />
          <span>{{ isSubmitting ? (uploadProgress < 100 ? `正在上传 ${uploadProgress}%` : '正在创建后台任务') : (isBusy ? '正在处理' : '开始 AI 复盘') }}</span>
        </button>
        <button v-if="isBusy" type="button" class="cancel-action" @click="cancelJob">取消任务</button>
        <p v-if="formError" class="form-error" role="alert">{{ formError }}</p>
        <p v-if="formNotice" class="form-notice" role="status">{{ formNotice }}</p>

        <div class="shooting-guide">
          <h3>拍摄建议</h3>
          <ul>
            <li><span>1</span>竖屏、横屏均可，机位保持固定</li>
            <li><span>2</span>从离地前开始，顶点稳定后结束</li>
            <li><span>3</span>选择单一颜色线路，减少人物遮挡</li>
          </ul>
        </div>
      </aside>
    </div>

    <section v-if="recentJobs.length" class="recent-section" aria-labelledby="recent-title">
      <div class="recent-heading"><h2 id="recent-title">最近分析</h2><span>仅当前账号可见</span></div>
      <button v-for="job in recentJobs" :key="job.id" type="button" class="recent-row" @click="selectJob(job)">
        <span class="recent-dot" :class="job.status" />
        <span><strong>{{ job.original_name }}</strong><small>{{ job.route_color }}线路 · {{ dateLabel(job.created_at) }}</small></span>
        <b>{{ jobStatusLabel(job) }}</b>
      </button>
    </section>
  </section>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import { ArrowLeft, ArrowRight, CircleCheck, Loading, RefreshRight, VideoCamera, Warning } from '@element-plus/icons-vue'
import climbReplayService from '../services/climbReplayService'

const colors = [
  { value: '绿色', hex: '#2f8c62' }, { value: '黄色', hex: '#e1b91d' },
  { value: '红色', hex: '#c94747' }, { value: '蓝色', hex: '#3478bc' },
  { value: '橙色', hex: '#dd792c' }, { value: '紫色', hex: '#8357a7' },
  { value: '粉色', hex: '#d86d91' }, { value: '黑色', hex: '#2b2c2f' },
]
const limbNames = { left_hand: '左手', right_hand: '右手', left_foot: '左脚', right_foot: '右脚' }
const fileInput = ref(null)
const videoElement = ref(null)
const selectedFile = ref(null)
const previewUrl = ref('')
const videoMeta = ref(null)
const trimStartSeconds = ref(0)
const trimEndSeconds = ref(90)
const MAX_VIDEO_SECONDS = 90
const MAX_INPUT_BYTES = 500 * 1024 * 1024
const routeColor = ref('绿色')
const retentionMode = ref('delete_after_processing')
const sampleConsent = ref(false)
const consentPolicy = ref(null)
const testVideoCases = ref([])
const loadingTestCaseId = ref('')
const uploadProgress = ref(0)
const isSubmitting = ref(false)
const activeJob = ref(null)
const recentJobs = ref([])
const formError = ref('')
const formNotice = ref('')
const isDragging = ref(false)
const isDeleting = ref(false)
const deletionReceipt = ref(null)
const showHolds = ref(true)
const showPose = ref(true)
const showEvents = ref(true)
const playbackTime = ref(0)
const preferredPlaybackKind = ref('overlay')
const pendingPlaybackState = ref(null)
let pollTimer = 0
let deletionTimer = 0

const poseEdges = [
  [5, 6], [5, 7], [7, 9], [6, 8], [8, 10],
  [5, 11], [6, 12], [11, 12], [11, 13], [13, 15], [12, 14], [14, 16],
]

const isBusy = computed(() => ['queued', 'running'].includes(activeJob.value?.status))
const isJobDeleting = computed(() => deletionReceipt.value
  ? deletionReceipt.value.state === 'queued'
  : activeJob.value?.deletion?.state === 'queued')
const result = computed(() => activeJob.value?.result || null)
const sourceMedia = computed(() => activeJob.value?.media?.source_video || null)
const sourceAvailable = computed(() => sourceMedia.value?.status === 'available')
const sourcePlayable = computed(() => sourceAvailable.value &&
  (!activeJob.value?.preparation || activeJob.value.preparation.status === 'completed'))
const overlayMedia = computed(() => activeJob.value?.media?.overlay_video || null)
const overlayAvailable = computed(() => overlayMedia.value?.status === 'available')
const comparisonCase = computed(() => testVideoCases.value.find((item) => (
  item.comparison_available
  && activeJob.value?.status === 'succeeded'
  && item.filename === activeJob.value?.original_name
  && item.comparison_route_color === activeJob.value?.route_color
  && Number(item.comparison_action_count) === actionEvents.value.length
)) || null)
const replayVideoAvailable = computed(() => Boolean(comparisonCase.value) || overlayAvailable.value)
const replayVideoUrl = computed(() => {
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
  if (comparisonCase.value) return climbReplayService.comparisonVideoUrl(comparisonCase.value.id, true)
  return storedOverlayDownloadUrl.value
})
const poseSamples = computed(() => (result.value?.pose_samples || []).filter((sample) => sample.observed))
const contactEvents = computed(() => (result.value?.attempt?.contacts || [])
  .filter((event) => Number.isFinite(Number(event.start_time_seconds)))
  .map((event, index) => ({ ...event, key: `${event.limb}-${event.hold_id}-${event.start_time_seconds}-${index}` })))
const actionEvents = computed(() => {
  const attempt = result.value?.attempt || {}
  const source = attempt.action_steps?.length ? attempt.action_steps : (attempt.contacts || [])
  const fps = Number(result.value?.video?.fps || 0)
  const limbOrder = { left_hand: 0, right_hand: 1, left_foot: 2, right_foot: 3 }
  const ordered = source
    .map((event, index) => {
      const sourceFrame = Number(event.start_source_frame)
      const eventTime = Number(event.start_time_seconds)
      const seekTime = Number.isFinite(sourceFrame) && sourceFrame >= 0 && fps > 0
        ? sourceFrame / fps
        : eventTime
      return {
        ...event,
        source_step: Number(event.step || index + 1),
        seek_time_seconds: seekTime,
      }
    })
    .filter((event) => Number.isFinite(event.seek_time_seconds))
    .sort((left, right) => (
      left.seek_time_seconds - right.seek_time_seconds
      || (limbOrder[left.limb] ?? 9) - (limbOrder[right.limb] ?? 9)
      || Number(left.hold_id || 0) - Number(right.hold_id || 0)
    ))
  const firstTime = ordered.length ? ordered[0].seek_time_seconds : 0
  const previousHoldByLimb = new Map()
  const namedEvents = []
  return ordered.map((event, index) => {
    const sourceHoldId = event.source_hold_id ?? previousHoldByLimb.get(event.limb)
    const activeSameHold = [...namedEvents].reverse().find((prior) => (
      prior.limb !== event.limb
      && Number(prior.hold_id) === Number(event.hold_id)
      && actionEndTime(prior) >= event.seek_time_seconds
    ))
    const supplementaryName = event.supplementary_name || inferSupplementaryActionName(
      event, sourceHoldId, activeSameHold, firstTime,
    )
    const namedEvent = {
      ...event,
      source_hold_id: sourceHoldId ?? null,
      supplementary_name: supplementaryName,
      step: index + 1,
      key: `动作-${index + 1}-${event.limb}-${event.seek_time_seconds}`,
    }
    namedEvents.push(namedEvent)
    previousHoldByLimb.set(event.limb, Number(event.hold_id))
    return namedEvent
  })
})
const activeActionKey = computed(() => {
  let active = null
  for (const event of actionEvents.value) {
    if (event.seek_time_seconds > playbackTime.value + .04) break
    active = event
  }
  return active?.key || ''
})
const activeActionIndex = computed(() => {
  const index = actionEvents.value.findIndex((event) => event.key === activeActionKey.value)
  return index >= 0 ? index : 0
})
const activeAction = computed(() => actionEvents.value[activeActionIndex.value] || null)
const currentPose = computed(() => {
  if (!poseSamples.value.length) return null
  let nearest = poseSamples.value[0]
  let delta = Math.abs(Number(nearest.time_seconds) - playbackTime.value)
  for (const sample of poseSamples.value.slice(1)) {
    const nextDelta = Math.abs(Number(sample.time_seconds) - playbackTime.value)
    if (nextDelta < delta) { nearest = sample; delta = nextDelta }
  }
  const sampleFps = Number(analysisEvidence.value?.sampling?.effective_fps || 4)
  if (delta > Math.max(.18, .75 / Math.max(sampleFps, 1))) return null
  return { ...nearest, delta }
})
const currentPoseExact = computed(() => {
  if (!currentPose.value) return false
  const sampleFps = Number(analysisEvidence.value?.sampling?.effective_fps || 4)
  return currentPose.value.delta <= Math.max(.04, .25 / Math.max(sampleFps, 1))
})
const poseEvidenceLabel = computed(() => {
  if (!currentPose.value) return ''
  const confidence = `${Math.round(Number(currentPose.value.confidence || 0) * 100)}%`
  return currentPoseExact.value
    ? `实测采样 · 置信度 ${confidence}`
    : `邻近实测采样 · 非插值 · ${currentPose.value.delta.toFixed(1)} 秒`
})
const skeletonSegments = computed(() => {
  const pose = currentPose.value
  if (!pose) return []
  const points = pose.kpts_xy || []
  const scores = pose.kpts_score || []
  return poseEdges.flatMap(([start, end]) => {
    if (!points[start] || !points[end] || Number(scores[start] || 0) < .15 || Number(scores[end] || 0) < .15) return []
    return [{ key: `${start}-${end}`, x1: points[start][0] * 100, y1: points[start][1] * 100,
      x2: points[end][0] * 100, y2: points[end][1] * 100 }]
  })
})
const posePoints = computed(() => {
  const pose = currentPose.value
  if (!pose) return []
  return (pose.kpts_xy || []).flatMap((point, index) => Number(pose.kpts_score?.[index] || 0) >= .15
    ? [{ key: index, x: point[0] * 100, y: point[1] * 100 }]
    : [])
})
const activeContactEvents = computed(() => contactEvents.value.filter((event) => {
  const end = Number.isFinite(Number(event.end_time_seconds)) ? Number(event.end_time_seconds) : Number(event.start_time_seconds)
  return playbackTime.value >= Number(event.start_time_seconds) && playbackTime.value <= end + .08
}))
const currentRun = computed(() => {
  const attempt = activeJob.value?.attempt || 1
  return [...(activeJob.value?.analysis_runs || [])].reverse().find((run) => run.attempt === attempt)
})
const analysisEvidence = computed(() => result.value?.analysis || currentRun.value?.analysis || null)
const analysisUsage = computed(() => analysisEvidence.value?.usage || {})
const analysisCost = computed(() => analysisEvidence.value?.cost || {})
const analysisTimings = computed(() => analysisEvidence.value?.timings_ms || {})
const currentConsentEvent = computed(() => {
  const attempt = activeJob.value?.attempt || 1
  return [...(activeJob.value?.consent_history || [])].reverse().find((event) => event.attempt === attempt)
})
const activeConsentGranted = computed(() => currentConsentEvent.value?.event === 'granted')
const trimDuration = computed(() => Math.max(0, Number(trimEndSeconds.value || 0) - Number(trimStartSeconds.value || 0)))
const trimIsValid = computed(() => !videoMeta.value || (trimStartSeconds.value >= 0 && trimEndSeconds.value > trimStartSeconds.value && trimDuration.value <= MAX_VIDEO_SECONDS + .05 && trimEndSeconds.value <= videoMeta.value.duration + .05))
const canSubmit = computed(() => selectedFile.value && routeColor.value && sampleConsent.value && consentPolicy.value && trimIsValid.value && !isBusy.value && !isSubmitting.value && !isDeleting.value)
const statusTitle = computed(() => isJobDeleting.value ? '正在删除整次记录' : ({
  queued: '任务正在排队', running: activeJob.value?.stage || '正在分析视频',
  succeeded: '分析完成', failed: '分析未完成', cancelled: '任务已取消',
}[activeJob.value?.status] || '准备中'))
const statusDetail = computed(() => {
  if (isJobDeleting.value) return '正在停止任务并删除原视频、复盘指标与派生文件。'
  if (activeJob.value?.status === 'failed') return activeJob.value.error || '请检查视频和人体姿态服务配置后重试。'
  if (activeJob.value?.status === 'cancelled') return sourceAvailable.value ? '原视频仍可用于重新分析。' : '原视频已删除，本次任务不能重新分析。'
  if (activeJob.value?.status === 'succeeded') return '结果为机器估算，请结合原视频复核。'
  if (activeJob.value?.status === 'queued') return uploadProgress.value < 100 ? `视频上传 ${uploadProgress.value}%` : '前方任务完成后会自动开始。'
  return '系统正在处理视频并识别动作；可以稍后在任务列表查看结果。'
})
const sourceRetentionLabel = computed(() => {
  const source = sourceMedia.value
  if (!source) return '未记录原视频保留状态'
  if (source.status === 'deleted') return `已于 ${dateLabel(source.deleted_at)} 删除，复盘指标仍保留`
  if (source.retention_mode === 'keep_private_original') return '私密保留中，仅当前账号可见'
  if (source.delete_at) return `计划于 ${dateLabel(source.delete_at)} 自动删除`
  return '任务结束后将按规则自动清理'
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

function openPicker() { fileInput.value?.click() }
let selectedFileToken = 0
async function inspectVideo(file) {
  const url = URL.createObjectURL(file)
  try {
    const metadata = await new Promise((resolve, reject) => {
      const probe = document.createElement('video')
      const timer = window.setTimeout(() => reject(new Error('浏览器无法预览此视频编码')), 8000)
      probe.preload = 'metadata'
      probe.onloadedmetadata = () => { window.clearTimeout(timer); resolve({ width: probe.videoWidth, height: probe.videoHeight, duration: probe.duration }) }
      probe.onerror = () => { window.clearTimeout(timer); reject(new Error('浏览器无法预览此视频编码')) }
      probe.src = url
    })
    if (!metadata.width || !metadata.height || !Number.isFinite(metadata.duration)) throw new Error('无法读取视频尺寸或时长，请重新选择文件。')
    return metadata
  } finally { URL.revokeObjectURL(url) }
}
async function useFile(file) {
  formError.value = ''
  formNotice.value = ''
  if (!file) return
  const token = ++selectedFileToken
  const supportedTypes = new Set(['video/mp4', 'video/quicktime', 'video/x-m4v', 'video/webm', 'video/3gpp', 'video/3gpp2', 'video/x-matroska'])
  const supportedExtensions = ['.mp4', '.mov', '.m4v', '.webm', '.3gp', '.3g2', '.mkv']
  if (!supportedTypes.has(file.type.toLowerCase()) && !supportedExtensions.some((extension) => file.name.toLowerCase().endsWith(extension))) {
    formError.value = '请选择 MP4、MOV、M4V、WebM、3GP 或 MKV 视频。'
    return
  }
  if (file.size > MAX_INPUT_BYTES) {
    formError.value = '视频不能超过 500 MB。'
    return
  }
  if (previewUrl.value) URL.revokeObjectURL(previewUrl.value)
  selectedFile.value = file
  previewUrl.value = URL.createObjectURL(file)
  videoMeta.value = null
  trimStartSeconds.value = 0
  trimEndSeconds.value = MAX_VIDEO_SECONDS
  activeJob.value = null
  deletionReceipt.value = null
  playbackTime.value = 0
  preferredPlaybackKind.value = 'overlay'
  pendingPlaybackState.value = null
  window.clearTimeout(deletionTimer)
  sampleConsent.value = false
  try {
    const metadata = await inspectVideo(file)
    if (token !== selectedFileToken) return
    videoMeta.value = metadata
    trimEndSeconds.value = Math.min(MAX_VIDEO_SECONDS, videoMeta.value.duration)
    formNotice.value = videoMeta.value.duration > MAX_VIDEO_SECONDS
      ? '视频已读取。系统默认分析前 90 秒；如需调整，可修改下面的起止时间。'
      : '视频已读取。上传后系统会自动整理视频。'
  } catch (_) {
    if (token !== selectedFileToken) return
    formNotice.value = '手机浏览器暂时无法预览此视频；仍可上传，服务器会继续尝试处理。'
  }
}
function onFileChange(event) { void useFile(event.target.files?.[0]); event.target.value = '' }
function onDrop(event) { isDragging.value = false; void useFile(event.dataTransfer.files?.[0]) }
async function loadTestVideoInfo() {
  try {
    const response = await climbReplayService.testVideos()
    testVideoCases.value = Array.isArray(response?.items) ? response.items : []
  } catch (_) { testVideoCases.value = [] }
}
async function useTestVideo(testCase) {
  if (loadingTestCaseId.value || !testCase?.id) return
  loadingTestCaseId.value = testCase.id
  formError.value = ''
  formNotice.value = ''
  try {
    const blob = await climbReplayService.testVideo(testCase.id)
    await useFile(new File([blob], testCase.filename || `${testCase.id}.mp4`, {
      type: 'video/mp4', lastModified: Date.now(),
    }))
    formNotice.value = `已载入${testCase.label}。请选择线路颜色并阅读授权说明后开始复盘。`
  } catch (error) {
    formError.value = error?.response?.status === 404
      ? '本机测试视频不可用，请重新启动本地服务后再试。'
      : errorText(error)
  } finally { loadingTestCaseId.value = '' }
}
function errorText(error) {
  if (error?.response?.status === 404) return '本地复盘服务尚未启用，请重新启动本地服务。'
  return error?.response?.data?.detail || error?.message || '操作失败，请稍后重试。'
}
async function submit() {
  if (!canSubmit.value) return
  formError.value = ''
  uploadProgress.value = 0
  isSubmitting.value = true
  try {
    activeJob.value = await climbReplayService.create({
      video: selectedFile.value,
      routeColor: routeColor.value,
      consentVersion: consentPolicy.value.version,
      consentGranted: true,
      retentionMode: retentionMode.value,
      trimStartSeconds: videoMeta.value?.duration > MAX_VIDEO_SECONDS ? Number(trimStartSeconds.value) : 0,
      trimEndSeconds: videoMeta.value?.duration > MAX_VIDEO_SECONDS ? Number(trimEndSeconds.value) : null,
    }, (value) => { uploadProgress.value = value })
    if (previewUrl.value) URL.revokeObjectURL(previewUrl.value)
    previewUrl.value = ''
    selectedFile.value = null
    videoMeta.value = null
    sampleConsent.value = false
    await loadJobs()
    schedulePoll()
  } catch (error) { formError.value = errorText(error) }
  finally { isSubmitting.value = false }
}
function schedulePoll() {
  window.clearTimeout(pollTimer)
  if (!isBusy.value || !activeJob.value?.id || isJobDeleting.value) return
  pollTimer = window.setTimeout(async () => {
    try {
      activeJob.value = await climbReplayService.get(activeJob.value.id)
      if (!isBusy.value) await loadJobs()
    } catch (error) { formError.value = errorText(error) }
    schedulePoll()
  }, 1200)
}
function clearDeletedReplay() {
  activeJob.value = null
  selectedFile.value = null
  videoMeta.value = null
  sampleConsent.value = false
  if (previewUrl.value) URL.revokeObjectURL(previewUrl.value)
  previewUrl.value = ''
  playbackTime.value = 0
  preferredPlaybackKind.value = 'overlay'
  pendingPlaybackState.value = null
}
function scheduleDeletionPoll(jobId) {
  window.clearTimeout(deletionTimer)
  if (!jobId || deletionReceipt.value?.state !== 'queued') return
  deletionTimer = window.setTimeout(async () => {
    try {
      deletionReceipt.value = await climbReplayService.deletion(jobId)
      if (deletionReceipt.value.state === 'completed') {
        clearDeletedReplay()
        formNotice.value = '整次复盘已删除，删除回执已生成。本机原始文件不受影响。'
        await loadJobs()
        return
      }
      if (deletionReceipt.value.state === 'failed') {
        formError.value = deletionReceipt.value.error || '删除未完成，请稍后重试。'
        return
      }
    } catch (error) {
      formError.value = errorText(error)
      return
    }
    scheduleDeletionPoll(jobId)
  }, 800)
}
async function cancelJob() {
  if (!activeJob.value?.id) return
  try { activeJob.value = await climbReplayService.cancel(activeJob.value.id); await loadJobs() }
  catch (error) { formError.value = errorText(error) }
}
async function retryJob() {
  if (!activeJob.value?.id) return
  if (!sampleConsent.value || !consentPolicy.value) {
    formError.value = '重新分析会再次发送抽样画面，请先重新勾选本次处理授权。'
    return
  }
  formError.value = ''
  formNotice.value = ''
  try {
    activeJob.value = await climbReplayService.retry(activeJob.value.id, consentPolicy.value.version)
    sampleConsent.value = false
    schedulePoll()
    await loadJobs()
  }
  catch (error) { formError.value = errorText(error) }
}
async function withdrawConsent() {
  if (!activeJob.value?.id) return
  formError.value = ''
  formNotice.value = ''
  try {
    activeJob.value = await climbReplayService.withdrawConsent(activeJob.value.id)
    const event = [...(activeJob.value.consent_history || [])].reverse().find((item) => item.event === 'withdrawn')
    formNotice.value = event?.outcome || '已记录授权撤回。'
    sampleConsent.value = false
    await loadJobs()
  } catch (error) { formError.value = errorText(error) }
}
async function deleteSourceVideo() {
  if (!activeJob.value?.id || isDeleting.value) return
  if (!window.confirm('将永久删除原视频，保留复盘指标。删除后该任务不能重新分析。确认删除？')) return
  isDeleting.value = true
  formError.value = ''
  formNotice.value = ''
  try {
    activeJob.value = await climbReplayService.deleteSource(activeJob.value.id)
    formNotice.value = '原视频已删除，复盘指标和处理记录仍保留。'
    await loadJobs()
  } catch (error) { formError.value = errorText(error) }
  finally { isDeleting.value = false }
}
async function deleteOverlayVideo() {
  if (!activeJob.value?.id || isDeleting.value || !overlayAvailable.value) return
  if (!window.confirm('将永久删除可导出的叠加视频，原视频、姿态数据和复盘指标仍会保留。确认删除？')) return
  isDeleting.value = true
  formError.value = ''
  formNotice.value = ''
  try {
    activeJob.value = await climbReplayService.deleteOverlay(activeJob.value.id)
    formNotice.value = '叠加视频已删除，原视频和复盘指标仍保留。'
    await loadJobs()
  } catch (error) { formError.value = errorText(error) }
  finally { isDeleting.value = false }
}
async function deleteEntireReplay() {
  if (!activeJob.value?.id || isDeleting.value || isJobDeleting.value) return
  if (!window.confirm('将永久删除原视频、姿态、事件、指标和派生文件。此操作不可恢复。确认删除整次记录？')) return
  const jobId = activeJob.value.id
  isDeleting.value = true
  formError.value = ''
  formNotice.value = ''
  window.clearTimeout(pollTimer)
  try {
    deletionReceipt.value = await climbReplayService.deleteJob(jobId)
    if (deletionReceipt.value.state === 'completed') {
      clearDeletedReplay()
      await loadJobs()
      formNotice.value = '整次复盘已删除，删除回执已生成。本机原始文件不受影响。'
    } else {
      scheduleDeletionPoll(jobId)
    }
  } catch (error) { formError.value = errorText(error) }
  finally { isDeleting.value = false }
}
function selectJob(job) {
  if (previewUrl.value) URL.revokeObjectURL(previewUrl.value)
  previewUrl.value = ''
  selectedFile.value = null
  videoMeta.value = null
  playbackTime.value = 0
  preferredPlaybackKind.value = 'overlay'
  pendingPlaybackState.value = null
  activeJob.value = job
  deletionReceipt.value = job.deletion || null
  sampleConsent.value = false
  formError.value = ''
  formNotice.value = ''
  if (isJobDeleting.value) scheduleDeletionPoll(job.id)
  else schedulePoll()
  window.scrollTo({ top: 0, behavior: 'smooth' })
}
async function loadConsentPolicy() {
  try { consentPolicy.value = await climbReplayService.consentPolicy() }
  catch (error) { formError.value = errorText(error) || '暂时无法加载数据处理告知。' }
}
async function loadJobs() {
  try { recentJobs.value = await climbReplayService.list() }
  catch (error) { if (error?.response?.status !== 404) formError.value = errorText(error) }
}
function holdStyle(hold) {
  const [x, y, width, height] = hold.bbox || [0, 0, 0, 0]
  return { left: `${x * 100}%`, top: `${y * 100}%`, width: `${width * 100}%`, height: `${height * 100}%` }
}
function updatePlaybackEvidence() {
  playbackTime.value = Number(videoElement.value?.currentTime || 0)
}
function capturePlaybackState() {
  const video = videoElement.value
  return {
    time: Number(video?.currentTime || playbackTime.value || 0),
    shouldPlay: Boolean(video && !video.paused && !video.ended),
  }
}
function switchPlayback(kind) {
  if (kind === playbackKind.value) return
  if (kind === 'overlay' && !replayVideoAvailable.value) return
  if (kind === 'source' && !sourcePlayable.value) return
  pendingPlaybackState.value = capturePlaybackState()
  preferredPlaybackKind.value = kind
  formNotice.value = ''
  nextTick(() => videoElement.value?.load())
}
function handlePlaybackLoaded() {
  const video = videoElement.value
  const state = pendingPlaybackState.value
  if (video && state) {
    const duration = Number(video.duration)
    const maxTime = Number.isFinite(duration) ? Math.max(0, duration - .05) : state.time
    video.currentTime = Math.max(0, Math.min(state.time, maxTime))
    pendingPlaybackState.value = null
    if (state.shouldPlay) video.play().catch(() => {})
  }
  updatePlaybackEvidence()
}
function handlePlaybackError() {
  if (playbackKind.value !== 'overlay' || !sourcePlayable.value) return
  pendingPlaybackState.value = capturePlaybackState()
  preferredPlaybackKind.value = 'source'
  formNotice.value = '复盘视频暂时无法加载，已自动切换到原视频。'
  nextTick(() => videoElement.value?.load())
}
function seekToEvent(event) {
  if (!videoElement.value) return
  videoElement.value.pause()
  videoElement.value.currentTime = Math.max(0, Number(event.seek_time_seconds || 0))
  updatePlaybackEvidence()
  videoElement.value.focus()
}
function stepAction(offset) {
  const target = actionEvents.value[activeActionIndex.value + offset]
  if (target) seekToEvent(target)
}
function replayActiveAction() {
  if (!activeAction.value || !videoElement.value) return
  seekToEvent(activeAction.value)
  videoElement.value.play().catch(() => {})
}
function actionAriaLabel(event) {
  return `跳转到第 ${event.step} 个动作，${limbNames[event.limb] || '手脚'}，${event.supplementary_name}，${formatClock(event.seek_time_seconds)}`
}
function actionEndTime(event) {
  const endTime = Number(event.end_time_seconds)
  if (Number.isFinite(endTime)) return endTime
  const endFrame = Number(event.end_source_frame)
  const fps = Number(result.value?.video?.fps || 0)
  return Number.isFinite(endFrame) && fps > 0 ? endFrame / fps : event.seek_time_seconds
}
function inferSupplementaryActionName(event, sourceHoldId, activeSameHold, firstTime) {
  const holdId = Number(event.hold_id)
  if (Math.abs(event.seek_time_seconds - firstTime) < .001) return `起步接触 ${holdId}`
  if (activeSameHold) {
    const limbKind = event.limb?.endsWith('hand') ? 'hand' : 'foot'
    const otherKind = activeSameHold.limb?.endsWith('hand') ? 'hand' : 'foot'
    if (limbKind === otherKind) return `${limbKind === 'hand' ? '双手' : '双脚'}匹配 ${holdId}`
    return `手脚同点 ${holdId}`
  }
  if (sourceHoldId == null) return `上点 ${holdId}`
  if (Number(sourceHoldId) === holdId) return `原点调整 ${holdId}`
  return `换点 ${sourceHoldId}→${holdId}`
}
function formatClock(value) {
  const seconds = Math.max(0, Number(value || 0))
  const minutes = Math.floor(seconds / 60)
  return `${minutes}:${String(Math.floor(seconds % 60)).padStart(2, '0')}.${Math.floor((seconds % 1) * 10)}`
}
function formatNumber(value) {
  return Number.isFinite(Number(value)) ? Number(value).toLocaleString('zh-CN', { maximumFractionDigits: 2 }) : '—'
}
function formatCost(value) {
  return Number.isFinite(Number(value)) ? `¥${Number(value).toFixed(4)}` : '待计算'
}
function formatDuration(milliseconds) {
  const value = Number(milliseconds)
  if (!Number.isFinite(value)) return '待计算'
  if (value < 1000) return `${Math.max(0, Math.round(value))} 毫秒`
  const seconds = value / 1000
  if (seconds < 60) return `${seconds.toFixed(seconds < 10 ? 1 : 0)} 秒`
  const minutes = Math.floor(seconds / 60)
  return `${minutes} 分 ${Math.round(seconds % 60)} 秒`
}
function formatBytes(value) {
  const bytes = Number(value)
  if (!Number.isFinite(bytes) || bytes <= 0) return '大小未知'
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}
function formatSeconds(value) {
  const seconds = Number(value)
  if (!Number.isFinite(seconds)) return '待计算'
  return `${seconds.toFixed(seconds < 10 ? 1 : 0)} 秒`
}
function formatVideoMeta(meta) {
  return `${meta.width}×${meta.height} · ${formatSeconds(meta.duration)} · ${formatBytes(selectedFile.value?.size)}`
}
function jobStatusLabel(job) {
  if (job.deletion?.state === 'queued') return '删除中'
  return ({ queued: '排队中', running: '分析中', succeeded: '已完成', failed: '失败', cancelled: '已取消' })[job.status] || job.status
}
function dateLabel(value) {
  if (!value) return ''
  return new Intl.DateTimeFormat('zh-CN', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' }).format(new Date(value))
}

onMounted(() => { loadConsentPolicy(); loadTestVideoInfo(); loadJobs() })
onBeforeUnmount(() => {
  window.clearTimeout(pollTimer)
  window.clearTimeout(deletionTimer)
  if (previewUrl.value) URL.revokeObjectURL(previewUrl.value)
})
</script>

<style scoped>
.replay-page{max-width:1400px;margin:0 auto;padding:34px 32px 80px;color:var(--ui-ink)}
.replay-page ::selection{background:var(--ui-brand-soft);color:var(--ui-brand-ink)}
.replay-page :is(button,input,a):focus-visible{outline:3px solid var(--ui-focus-halo);outline-offset:2px}
.replay-heading{display:flex;align-items:flex-end;justify-content:space-between;gap:24px;margin-bottom:24px}
.replay-heading h1{margin:0;font-size:clamp(30px,3vw,38px);font-weight:650;letter-spacing:-.03em;line-height:1.08}
.replay-heading p{max-width:65ch;margin:8px 0 0;color:var(--ui-ink-muted);font-size:14px}
.prototype-badge{flex:none;padding:5px 9px;border:1px solid var(--ui-line);border-radius:999px;background:rgba(255,255,255,.56);color:var(--ui-ink-muted);font-size:11px;font-weight:600}
.replay-workspace{display:grid;grid-template-columns:minmax(0,1fr) 330px;gap:22px;align-items:start}
.replay-workspace.review-mode{grid-template-columns:minmax(0,1fr)}
.video-column,.setup-panel,.recent-section{border:1px solid var(--ui-line);border-radius:16px;background:var(--ui-surface)}
.video-column{min-width:0;overflow:hidden;box-shadow:0 18px 48px rgba(33,31,26,.07)}
.video-drop{min-height:540px;padding:40px;display:grid;place-items:center;align-content:center;gap:12px;background:#242629;color:#fff;text-align:center;cursor:pointer;transition:background .18s ease-out}
.video-drop.dragging,.video-drop:hover{background:#2d3033}.drop-icon{width:42px;height:42px;color:var(--ui-brand)}
.video-drop strong{font-size:21px}.video-drop>span{color:#bfc2c4;font-size:13px}
.secondary-button,.replace-video,.cancel-action{min-height:38px;padding:0 15px;border:1px solid var(--ui-line-strong);border-radius:var(--ui-radius-small);background:var(--ui-surface);color:var(--ui-ink);font:inherit;font-size:13px;font-weight:600;cursor:pointer}.secondary-button:disabled{cursor:not-allowed;opacity:.45}
.video-drop .secondary-button{margin-top:8px;border-color:#696c70;background:transparent;color:#fff}
.test-video-cases{padding:16px 20px 18px;border-top:1px solid var(--ui-line);background:var(--ui-surface-subtle);display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px}.test-video-heading{grid-column:1/-1;min-width:0;margin-bottom:3px;display:grid;grid-template-columns:36px minmax(0,1fr);align-items:center;gap:12px}.test-video-mark{width:34px;height:34px;border-radius:10px;background:var(--ui-brand-soft);color:var(--ui-brand-ink);display:grid;place-items:center}.test-video-mark svg{width:18px}.test-video-heading strong{font-size:13px}.test-video-heading p{margin:3px 0 0;color:var(--ui-ink-muted);font-size:12px}.test-video-case{min-width:0;padding:11px 12px;border:1px solid var(--ui-line);border-radius:var(--ui-radius-small);background:var(--ui-surface);color:var(--ui-ink);display:flex;align-items:center;justify-content:space-between;gap:10px;text-align:left;font:inherit;cursor:pointer}.test-video-case:hover:not(:disabled){border-color:var(--ui-line-strong);background:var(--ui-surface-subtle)}.test-video-case:disabled{cursor:not-allowed;opacity:.55}.test-video-case>span{min-width:0;display:grid;gap:3px}.test-video-case strong{font-size:12px}.test-video-case small{color:var(--ui-ink-muted);font-size:11px;line-height:1.4;overflow-wrap:anywhere}.test-video-case b{flex:none;color:var(--ui-ink-muted);font-size:11px}.test-video-case svg{flex:none;width:15px;animation:spin 1s linear infinite}
.playback-review{display:grid;min-width:0;background:#0e100f}
.playback-review.has-action-focus{grid-template-columns:minmax(0,1fr) 280px}
.video-stage{position:relative;min-width:0;min-height:440px;max-height:680px;background:#0e100f;display:flex;align-items:center;justify-content:center;overflow:hidden}
.video-canvas{position:relative;max-width:100%;max-height:650px;display:inline-flex}
.video-stage video{display:block;width:auto;height:auto;max-width:100%;max-height:650px;object-fit:contain}
.hold-overlay{position:absolute;inset:0;margin:auto;width:100%;height:100%;pointer-events:none}
.hold-box{position:absolute;border:2px solid var(--ui-brand);border-radius:7px;box-shadow:0 3px 12px rgba(0,0,0,.28)}
.hold-box b{position:absolute;top:-10px;left:-8px;min-width:21px;height:21px;padding:0 4px;border-radius:7px;background:var(--ui-brand);color:var(--ui-brand-ink);display:grid;place-items:center;font-size:11px}
.pose-overlay{position:absolute;inset:0;width:100%;height:100%;overflow:visible}.pose-overlay line{stroke:#6ce0d2;stroke-width:3;stroke-linecap:round}.pose-overlay circle{fill:#d6fff9;stroke:#155d55;stroke-width:1.5}.pose-evidence{position:absolute;left:12px;top:12px;padding:6px 9px;border-radius:8px;background:rgba(17,92,83,.9);color:#fff;font-size:11px;font-weight:650;box-shadow:0 3px 12px rgba(0,0,0,.24)}.pose-evidence.nearby{background:rgba(47,50,52,.9);border:1px dashed rgba(255,255,255,.7)}.contact-badges{position:absolute;left:12px;bottom:12px;display:flex;flex-wrap:wrap;gap:6px}.contact-badges span{padding:5px 8px;border-radius:7px;background:rgba(21,76,132,.92);color:#fff;font-size:11px;font-weight:650;box-shadow:0 3px 12px rgba(0,0,0,.24)}
.replace-video{position:absolute;right:16px;top:16px;min-height:34px;padding:0 13px;border-color:rgba(255,255,255,.18);border-radius:999px;background:rgba(14,16,15,.76);color:#fff;backdrop-filter:blur(8px)}
.action-focus{min-width:0;padding:24px 22px 22px;background:#171917;color:#f7f6f1;display:flex;flex-direction:column;border-left:1px solid rgba(255,255,255,.08)}
.action-focus-head{display:flex;align-items:center;justify-content:space-between;gap:12px;color:#8f948f;font-size:11px}.action-focus-head strong{color:#c7cac5;font-size:11px;font-weight:500}.action-focus-head span{font-variant-numeric:tabular-nums}.action-focus-head b{color:#f4c430;font-size:13px}
.action-focus-name{margin-top:30px;display:grid;grid-template-columns:48px minmax(0,1fr);align-items:start;gap:15px}.action-focus-name>span{width:48px;height:48px;border:1px solid rgba(244,196,48,.52);border-radius:50%;color:#f4c430;display:grid;place-items:center;font-size:13px;font-weight:700;font-variant-numeric:tabular-nums}.action-focus-name>div{min-width:0;display:grid;gap:2px}.action-focus-name strong{font-size:22px;font-weight:600;letter-spacing:-.02em;line-height:1.2}.action-focus-name p{margin:2px 0 0;color:#d9dbd7;font-size:14px;line-height:1.4}.action-focus-name small{margin-top:8px;color:#858a85;font-size:11px;font-variant-numeric:tabular-nums}
.action-focus-actions{margin-top:auto;display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:7px}.action-focus-actions button{min-height:42px;padding:0 8px;border:1px solid transparent;border-radius:999px;background:rgba(255,255,255,.07);color:#d7dad5;display:flex;align-items:center;justify-content:center;gap:6px;font:inherit;font-size:11px;font-weight:600;cursor:pointer;transition:background .18s ease-out,color .18s ease-out,transform .18s ease-out}.action-focus-actions button svg{width:14px;height:14px}.action-focus-actions button.primary{background:var(--ui-brand);color:var(--ui-brand-ink)}.action-focus-actions button:hover:not(:disabled){background:rgba(255,255,255,.13);color:#fff;transform:translateY(-1px)}.action-focus-actions button.primary:hover{background:var(--ui-brand-hover);color:var(--ui-brand-ink)}.action-focus-actions button:disabled{cursor:not-allowed;opacity:.28}
.player-tools{min-height:50px;padding:9px 18px;border-top:1px solid rgba(255,255,255,.07);background:#171917;color:#f7f6f1;display:flex;align-items:center;justify-content:space-between;gap:16px}.player-options{min-width:0;display:flex;align-items:center;flex-wrap:wrap;gap:9px 16px}.player-options>p{margin:0;color:#9a9f99;font-size:12px}.playback-switch{padding:3px;border:0;border-radius:999px;background:rgba(255,255,255,.08);display:flex;gap:2px}.playback-switch button{min-height:29px;padding:0 12px;border:0;border-radius:999px;background:transparent;color:#9fa39e;font:inherit;font-size:11px;font-weight:600;cursor:pointer}.playback-switch button.active{background:#f2f1ec;color:#181a18}.playback-switch button:disabled{cursor:not-allowed;opacity:.35}.layer-controls{display:flex;align-items:center;flex-wrap:wrap;gap:8px 16px}.layer-controls label{display:flex;align-items:center;gap:6px;color:#c3c7c1;font-size:11px;font-weight:500;cursor:pointer}.layer-controls input{width:14px;height:14px;margin:0;accent-color:var(--ui-brand)}.export-action{flex:none;min-height:32px;padding:0 12px;border:1px solid rgba(255,255,255,.13);border-radius:999px;color:#f2f3ef;display:inline-flex;align-items:center;font-size:11px;font-weight:600;text-decoration:none}.export-action:hover{background:rgba(255,255,255,.08)}
.event-timeline{padding:17px 20px 18px;border-top:1px solid var(--ui-line);background:var(--ui-surface)}
.event-timeline-heading{display:flex;align-items:baseline;justify-content:space-between;gap:10px;margin-bottom:12px}.event-timeline-heading strong{font-size:12px;font-weight:600}.event-timeline-heading span{color:var(--ui-ink-faint);font-size:10px}
.event-timeline ol{margin:0;padding:0 0 7px;list-style:none;display:flex;gap:0;overflow-x:auto;scroll-snap-type:x proximity;scrollbar-color:var(--ui-line-strong) transparent;scrollbar-width:thin}
.event-timeline li{position:relative;flex:none;scroll-snap-align:center}.event-timeline li:not(:last-child)::after{content:"";position:absolute;z-index:0;left:52px;top:14px;width:28px;height:1px;background:var(--ui-line)}
.event-timeline button{position:relative;z-index:1;width:80px;min-height:66px;padding:0 5px;border:0;background:transparent;color:var(--ui-ink-muted);display:flex;flex-direction:column;align-items:center;gap:4px;text-align:center;font:inherit;cursor:pointer}
.event-timeline button>span{width:28px;height:28px;border:1px solid var(--ui-line);border-radius:50%;background:var(--ui-surface);display:grid;place-items:center;font-size:10px;font-weight:700;font-variant-numeric:tabular-nums;transition:background .18s ease-out,border-color .18s ease-out,color .18s ease-out,transform .18s ease-out}.event-timeline button>strong{font-size:10px;font-weight:600;white-space:nowrap}.event-timeline button>small{max-width:72px;color:var(--ui-ink-faint);font-size:9px;line-height:1.2;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.event-timeline button.reached>span{border-color:#4d514c;background:#4d514c;color:#fff}.event-timeline button.reached>small,.event-timeline button.current>small{color:var(--ui-ink-muted)}
.event-timeline button.current>span{border-color:var(--ui-brand);background:var(--ui-brand);color:var(--ui-brand-ink);transform:scale(1.08)}
.event-timeline button:hover>span{border-color:var(--ui-ink);transform:translateY(-1px)}
.analysis-state{padding:18px 20px;border-top:1px solid var(--ui-line);background:var(--ui-surface-subtle)}
.state-copy{display:grid;grid-template-columns:34px minmax(0,1fr) auto;align-items:center;gap:11px}.state-copy p{margin:3px 0 0;color:var(--ui-ink-muted);font-size:12px}.state-copy>b{font-variant-numeric:tabular-nums}.state-mark{width:32px;height:32px;border-radius:10px;background:var(--ui-surface);display:grid;place-items:center}.state-mark svg{width:18px}.running .state-mark svg,.queued .state-mark svg{animation:spin 1s linear infinite}.succeeded .state-mark{color:var(--ui-success)}.failed .state-mark{color:var(--ui-danger)}
.progress-track{height:5px;margin-top:14px;border-radius:5px;background:var(--ui-line);overflow:hidden}.progress-track i{display:block;height:100%;border-radius:inherit;background:var(--ui-brand);transition:width .35s ease-out}.state-actions{margin-top:12px}
.state-actions p{margin:0;color:var(--ui-ink-muted);font-size:12px}.media-retention{margin-top:14px;padding-top:4px;border-top:1px solid var(--ui-line);display:grid}.media-row{min-width:0;padding:10px 0;border-bottom:1px solid var(--ui-line);display:flex;align-items:flex-start;justify-content:space-between;gap:18px}.media-row>div:first-child{min-width:0}.media-retention strong{font-size:12px}.media-retention p{margin:4px 0 0;color:var(--ui-ink-muted);font-size:12px;line-height:1.5}.media-actions{display:flex;flex:none;align-items:center;gap:14px}.media-record-actions{padding-top:10px;display:flex;justify-content:flex-end}.text-action{padding:3px 0;border:0;background:transparent;color:var(--ui-ink-muted);font:inherit;font-size:12px;text-decoration:underline;text-underline-offset:3px;cursor:pointer}.text-action:hover:not(:disabled){color:var(--ui-ink)}a.text-action{display:inline-flex}.text-action.destructive{color:var(--ui-danger)}.text-action:disabled{cursor:not-allowed;opacity:.45}
.run-summary{margin-top:13px;padding-top:12px;border-top:1px solid var(--ui-line);display:flex;flex-wrap:wrap;gap:7px 18px;color:var(--ui-ink-muted);font-size:12px;font-variant-numeric:tabular-nums}.run-summary span{white-space:nowrap}
.analysis-evidence{padding:18px 20px;border-top:1px solid var(--ui-line);background:var(--ui-surface)}.analysis-evidence summary{color:var(--ui-ink);font-size:13px;font-weight:600;cursor:pointer}.analysis-evidence dl{margin:16px 0 0;display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:0 24px}.analysis-evidence dl>div{min-width:0;padding:10px 0;border-top:1px solid var(--ui-line);display:grid;grid-template-columns:76px minmax(0,1fr);gap:10px;font-size:12px;line-height:1.55}.analysis-evidence dt{color:var(--ui-ink-muted)}.analysis-evidence dd{margin:0;color:var(--ui-ink);overflow-wrap:anywhere;font-variant-numeric:tabular-nums}.analysis-evidence>p{max-width:72ch;margin:12px 0 0;color:var(--ui-ink-muted);font-size:11px;line-height:1.6}
.setup-panel{position:sticky;top:86px;padding:24px}.setup-panel h2,.result-report h2,.recent-heading h2{margin:0;font-size:20px}.setup-panel>div>p{margin:7px 0 0;color:var(--ui-ink-muted);font-size:13px;line-height:1.6}.setup-panel fieldset{margin:26px 0 0;padding:0;border:0}.setup-panel legend{margin-bottom:10px;font-size:13px;font-weight:600}
.color-options{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:7px}.color-options label{min-height:42px;padding:0 10px;border:1px solid var(--ui-line);border-radius:var(--ui-radius-small);display:flex;align-items:center;gap:8px;font-size:13px;cursor:pointer}.color-options label.selected{border-color:var(--ui-ink);background:var(--ui-surface-subtle)}.color-options input{position:absolute;opacity:0;pointer-events:none}.color-options i{width:14px;height:14px;border:1px solid rgba(0,0,0,.2);border-radius:50%}
.retention-options{display:grid;gap:7px}.retention-options label{padding:11px;border:1px solid var(--ui-line);border-radius:var(--ui-radius-small);display:grid;grid-template-columns:16px 1fr;gap:9px;align-items:start;cursor:pointer}.retention-options label.selected{border-color:var(--ui-ink);background:var(--ui-surface-subtle)}.retention-options input{width:15px;height:15px;margin:2px 0 0;accent-color:var(--ui-ink)}.retention-options span{display:grid;gap:3px}.retention-options strong{font-size:12px}.retention-options small{color:var(--ui-ink-muted);font-size:11px;line-height:1.5}
.privacy-check{margin-top:22px;display:grid;grid-template-columns:17px 1fr;gap:9px;color:var(--ui-ink-muted);font-size:12px;line-height:1.5;cursor:pointer}.privacy-check input{width:16px;height:16px;margin:1px 0;accent-color:var(--ui-ink)}
.consent-meta{margin:8px 0 0 26px;color:var(--ui-ink-faint);font-size:11px;line-height:1.5;overflow-wrap:anywhere}.consent-action{margin:8px 0 0 26px;padding:0;border:0;background:transparent;color:var(--ui-ink-muted);font:inherit;font-size:12px;text-decoration:underline;text-underline-offset:3px;cursor:pointer}.consent-action:hover{color:var(--ui-ink)}
.video-preflight{margin-top:16px;padding:14px 16px;border:1px solid var(--ui-line);border-radius:var(--ui-radius-control);background:var(--ui-surface-subtle);color:var(--ui-ink-muted);font-size:12px;line-height:1.55}.video-preflight__head{display:flex;align-items:baseline;justify-content:space-between;gap:12px;color:var(--ui-ink)}.video-preflight__head span{font-size:11px;color:var(--ui-ink-faint);font-variant-numeric:tabular-nums}.video-preflight p{margin:7px 0 0}.video-trim{margin-top:12px;padding-top:12px;border-top:1px solid var(--ui-line);color:var(--ui-ink)}.video-trim>p{color:var(--ui-ink-muted)}.video-trim__fields{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-top:10px}.video-trim__fields label{display:grid;gap:5px;color:var(--ui-ink-muted);font-size:11px}.video-trim__fields input{width:100%;min-height:34px;padding:0 9px;border:1px solid var(--ui-line-strong);border-radius:8px;background:var(--ui-surface);color:var(--ui-ink);font:inherit}.video-trim__status{font-variant-numeric:tabular-nums}.video-trim__status.invalid{color:var(--ui-danger)}
.primary-action{width:100%;min-height:48px;margin-top:16px;border:0;border-radius:var(--ui-radius-control);background:var(--ui-brand);color:var(--ui-brand-ink);display:flex;align-items:center;justify-content:center;gap:8px;font:inherit;font-weight:700;cursor:pointer}.primary-action:hover:not(:disabled){background:var(--ui-brand-hover)}.primary-action:disabled{cursor:not-allowed;opacity:.45}.primary-action svg{width:17px;animation:spin 1s linear infinite}.cancel-action{width:100%;margin-top:8px}.form-error,.form-notice{margin:12px 0 0;font-size:12px;line-height:1.5}.form-error{color:var(--ui-danger)}.form-notice{color:var(--ui-success)}
.shooting-guide{margin-top:28px;padding-top:22px;border-top:1px solid var(--ui-line)}.shooting-guide h3,.sequence-block h3{margin:0;font-size:13px}.shooting-guide ul{margin:13px 0 0;padding:0;list-style:none;display:grid;gap:12px}.shooting-guide li{display:grid;grid-template-columns:22px 1fr;gap:8px;color:var(--ui-ink-muted);font-size:12px;line-height:1.5}.shooting-guide li span{width:21px;height:21px;border-radius:7px;background:var(--ui-surface-subtle);color:var(--ui-ink);display:grid;place-items:center;font-weight:600}
.result-report{padding:24px;border-top:1px solid var(--ui-line)}.result-summary{display:flex;align-items:flex-start;justify-content:space-between;gap:16px}.result-summary p{margin:5px 0 0;color:var(--ui-ink-muted);font-size:13px}.result-summary>strong{font-size:26px;font-variant-numeric:tabular-nums}.sequence-block{margin-top:25px}.hold-sequence{margin-top:11px;display:flex;align-items:center;gap:7px;flex-wrap:wrap}.hold-sequence span{width:32px;height:32px;border-radius:9px;background:var(--ui-brand);color:var(--ui-brand-ink);display:grid;place-items:center;font-weight:700}.hold-sequence svg{width:14px;color:var(--ui-ink-faint)}.empty-result{color:var(--ui-ink-muted);font-size:13px}
.limb-table{margin-top:22px;border-top:1px solid var(--ui-line)}.limb-table>div{min-height:50px;border-bottom:1px solid var(--ui-line);display:grid;grid-template-columns:70px 80px 1fr;align-items:center;gap:10px;font-size:13px}.limb-table strong{font-variant-numeric:tabular-nums}.limb-table small{color:var(--ui-ink-muted);text-align:right}.review-notes{margin-top:18px;color:var(--ui-ink-muted);font-size:12px}.review-notes summary{color:var(--ui-ink);cursor:pointer;font-weight:600}.review-notes ul{margin:9px 0 0;padding-left:18px;line-height:1.7}
.recent-section{margin-top:22px;padding:22px}.recent-heading{display:flex;align-items:center;justify-content:space-between;margin-bottom:10px}.recent-heading span{color:var(--ui-ink-muted);font-size:12px}.recent-row{width:100%;min-height:58px;padding:9px 4px;border:0;border-top:1px solid var(--ui-line);background:transparent;color:var(--ui-ink);display:grid;grid-template-columns:10px minmax(0,1fr) auto;align-items:center;gap:12px;text-align:left;cursor:pointer}.recent-row>span:nth-child(2){min-width:0;display:grid;gap:3px}.recent-row strong,.recent-row small{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.recent-row small{color:var(--ui-ink-muted)}.recent-row>b{font-size:12px}.recent-dot{width:8px;height:8px;border-radius:50%;background:var(--ui-warning)}.recent-dot.succeeded{background:var(--ui-success)}.recent-dot.failed{background:var(--ui-danger)}.recent-dot.cancelled{background:var(--ui-ink-faint)}
.visually-hidden{position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap;border:0}
@keyframes spin{to{transform:rotate(360deg)}}
@media(max-width:900px){.replay-page{padding:16px 16px 88px}.replay-heading{display:none}.replay-workspace{grid-template-columns:1fr}.setup-panel{position:static}.video-drop{min-height:340px}.video-stage{height:min(56vw,390px);min-height:0;max-height:390px}.video-canvas{height:100%;max-height:100%}.video-stage video{max-height:100%}.color-options{grid-template-columns:repeat(2,minmax(0,1fr))}}
@media(max-width:720px){.playback-review.has-action-focus{grid-template-columns:1fr}.action-focus{min-height:156px;padding:17px 16px 16px;border-top:1px solid rgba(255,255,255,.08);border-left:0}.action-focus-name{margin-top:14px;grid-template-columns:40px minmax(0,1fr);gap:12px}.action-focus-name>span{width:40px;height:40px}.action-focus-name strong{font-size:18px}.action-focus-name p{font-size:13px}.action-focus-name small{margin-top:4px}.action-focus-actions{margin-top:16px}.player-tools{align-items:flex-start;flex-wrap:wrap}}
@media(max-width:650px){.test-video-cases{grid-template-columns:1fr}}
@media(max-width:520px){.video-column{border-radius:14px}.video-stage{height:58vw;max-height:260px}.action-focus{min-height:154px}.action-focus-head{position:absolute;right:16px;margin-top:2px}.action-focus-head>strong{display:none}.action-focus-name strong{font-size:18px}.action-focus-actions button{min-height:40px}.test-video-cases{padding:14px 16px}.color-options{grid-template-columns:repeat(4,1fr)}.limb-table>div{grid-template-columns:58px 64px 1fr}.recent-section{padding:18px}.result-report{padding:20px}.result-summary>strong{font-size:21px}.run-summary{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:7px 12px}.analysis-evidence{padding:18px}.analysis-evidence dl{grid-template-columns:1fr}.analysis-evidence dl>div{grid-template-columns:70px minmax(0,1fr)}.layer-controls{gap:8px 12px}.event-timeline{padding:15px 14px 16px}.event-timeline button{width:68px}.event-timeline li:not(:last-child)::after{left:46px;width:22px}.media-row{display:grid;gap:7px}.media-actions{justify-content:flex-start;flex-wrap:wrap}.media-record-actions{justify-content:flex-start}}
@media(prefers-reduced-motion:reduce){.progress-track i,.video-drop{transition:none}.running .state-mark svg,.queued .state-mark svg,.primary-action svg,.test-video-case svg{animation:none}}
</style>
