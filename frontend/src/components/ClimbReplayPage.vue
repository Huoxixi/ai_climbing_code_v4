<template>
  <section class="replay-page" aria-labelledby="replay-title">
    <header class="replay-heading">
      <div>
        <h1 id="replay-title">看清这次攀爬</h1>
        <p>上传一段固定机位视频，识别线路岩点、手脚接触顺序和完攀时间。</p>
      </div>
      <span class="prototype-badge">技术验证</span>
    </header>

    <div class="replay-workspace">
      <div class="video-column">
        <div
          v-if="!previewUrl"
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
          <span>MP4 · 最长 1 分 30 秒 · 不超过 200 MB</span>
          <button type="button" class="secondary-button">浏览文件</button>
        </div>

        <div v-else class="video-stage">
          <div class="video-canvas">
            <video ref="videoElement" :src="previewUrl" controls playsinline preload="metadata" />
            <div v-if="result?.holds?.length" class="hold-overlay" aria-hidden="true">
              <span
                v-for="hold in result.holds"
                :key="hold.id"
                class="hold-box"
                :style="holdStyle(hold)"
              ><b>{{ hold.id }}</b></span>
            </div>
          </div>
          <button v-if="!isBusy" type="button" class="replace-video" @click="openPicker">更换视频</button>
        </div>
        <input ref="fileInput" class="visually-hidden" type="file" accept="video/mp4,.mp4" @change="onFileChange" />

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
          <div v-if="['failed', 'cancelled'].includes(activeJob.status)" class="state-actions">
            <button type="button" class="secondary-button" @click="retryJob">重新分析</button>
          </div>
        </div>

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

      <aside class="setup-panel" aria-label="分析设置">
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

        <label class="privacy-check">
          <input v-model="cloudConsent" type="checkbox" />
          <span>我了解：点击分析后，视频会发送至 VLM Run 云端模型处理。</span>
        </label>

        <button type="button" class="primary-action" :disabled="!canSubmit" @click="submit">
          <Loading v-if="isBusy" />
          <span>{{ isBusy ? '正在分析' : '开始 AI 复盘' }}</span>
        </button>
        <button v-if="isBusy" type="button" class="cancel-action" @click="cancelJob">取消任务</button>
        <p v-if="formError" class="form-error" role="alert">{{ formError }}</p>

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
        <b>{{ jobStatusLabel(job.status) }}</b>
      </button>
    </section>
  </section>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { ArrowRight, CircleCheck, Loading, VideoCamera, Warning } from '@element-plus/icons-vue'
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
const routeColor = ref('绿色')
const cloudConsent = ref(false)
const uploadProgress = ref(0)
const activeJob = ref(null)
const recentJobs = ref([])
const formError = ref('')
const isDragging = ref(false)
let pollTimer = 0

const isBusy = computed(() => ['queued', 'running'].includes(activeJob.value?.status))
const result = computed(() => activeJob.value?.result || null)
const canSubmit = computed(() => selectedFile.value && routeColor.value && cloudConsent.value && !isBusy.value)
const statusTitle = computed(() => ({
  queued: '任务正在排队', running: activeJob.value?.stage || '正在分析视频',
  succeeded: '分析完成', failed: '分析未完成', cancelled: '任务已取消',
}[activeJob.value?.status] || '准备中'))
const statusDetail = computed(() => {
  if (activeJob.value?.status === 'failed') return activeJob.value.error || '请检查视频和云端配置后重试。'
  if (activeJob.value?.status === 'cancelled') return '视频保留在本机，可随时重新分析。'
  if (activeJob.value?.status === 'succeeded') return '结果为机器估算，请结合原视频复核。'
  if (activeJob.value?.status === 'queued') return uploadProgress.value < 100 ? `视频上传 ${uploadProgress.value}%` : '前方任务完成后会自动开始。'
  return '正在识别岩点与攀爬者动作，请保持页面开启。'
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
function useFile(file) {
  formError.value = ''
  if (!file) return
  if (file.type !== 'video/mp4' && !file.name.toLowerCase().endsWith('.mp4')) {
    formError.value = '当前仅支持 MP4 视频。'
    return
  }
  if (file.size > 200 * 1024 * 1024) {
    formError.value = '视频不能超过 200 MB。'
    return
  }
  if (previewUrl.value) URL.revokeObjectURL(previewUrl.value)
  selectedFile.value = file
  previewUrl.value = URL.createObjectURL(file)
  activeJob.value = null
  cloudConsent.value = false
}
function onFileChange(event) { useFile(event.target.files?.[0]); event.target.value = '' }
function onDrop(event) { isDragging.value = false; useFile(event.dataTransfer.files?.[0]) }
function errorText(error) {
  if (error?.response?.status === 404) return '本地复盘服务尚未启用，请重新启动本地服务。'
  return error?.response?.data?.detail || error?.message || '操作失败，请稍后重试。'
}
async function submit() {
  if (!canSubmit.value) return
  formError.value = ''
  uploadProgress.value = 0
  try {
    activeJob.value = await climbReplayService.create({ video: selectedFile.value, routeColor: routeColor.value }, (value) => { uploadProgress.value = value })
    await loadJobs()
    schedulePoll()
  } catch (error) { formError.value = errorText(error) }
}
function schedulePoll() {
  window.clearTimeout(pollTimer)
  if (!isBusy.value || !activeJob.value?.id) return
  pollTimer = window.setTimeout(async () => {
    try {
      activeJob.value = await climbReplayService.get(activeJob.value.id)
      if (!isBusy.value) await loadJobs()
    } catch (error) { formError.value = errorText(error) }
    schedulePoll()
  }, 1200)
}
async function cancelJob() {
  if (!activeJob.value?.id) return
  try { activeJob.value = await climbReplayService.cancel(activeJob.value.id); await loadJobs() }
  catch (error) { formError.value = errorText(error) }
}
async function retryJob() {
  if (!activeJob.value?.id) return
  formError.value = ''
  try { activeJob.value = await climbReplayService.retry(activeJob.value.id); schedulePoll(); await loadJobs() }
  catch (error) { formError.value = errorText(error) }
}
function selectJob(job) { activeJob.value = job; formError.value = ''; schedulePoll(); window.scrollTo({ top: 0, behavior: 'smooth' }) }
async function loadJobs() {
  try { recentJobs.value = await climbReplayService.list() }
  catch (error) { if (error?.response?.status !== 404) formError.value = errorText(error) }
}
function holdStyle(hold) {
  const [x, y, width, height] = hold.bbox || [0, 0, 0, 0]
  return { left: `${x * 100}%`, top: `${y * 100}%`, width: `${width * 100}%`, height: `${height * 100}%` }
}
function jobStatusLabel(status) { return ({ queued: '排队中', running: '分析中', succeeded: '已完成', failed: '失败', cancelled: '已取消' })[status] || status }
function dateLabel(value) {
  if (!value) return ''
  return new Intl.DateTimeFormat('zh-CN', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' }).format(new Date(value))
}

onMounted(loadJobs)
onBeforeUnmount(() => { window.clearTimeout(pollTimer); if (previewUrl.value) URL.revokeObjectURL(previewUrl.value) })
</script>

<style scoped>
.replay-page{max-width:1320px;margin:0 auto;padding:38px 32px 72px;color:var(--ui-ink)}
.replay-page ::selection{background:var(--ui-brand-soft);color:var(--ui-brand-ink)}
.replay-page :is(button,input):focus-visible{outline:3px solid var(--ui-focus-halo);outline-offset:2px}
.replay-heading{display:flex;align-items:flex-end;justify-content:space-between;gap:24px;margin-bottom:26px}
.replay-heading h1{margin:0;font-size:clamp(28px,3vw,42px);font-weight:600;letter-spacing:-.025em;line-height:1.1}
.replay-heading p{max-width:65ch;margin:9px 0 0;color:var(--ui-ink-muted);font-size:15px}
.prototype-badge{flex:none;padding:6px 10px;border:1px solid var(--ui-line-strong);border-radius:999px;color:var(--ui-ink-muted);font-size:12px;font-weight:600}
.replay-workspace{display:grid;grid-template-columns:minmax(0,1fr) 330px;gap:22px;align-items:start}
.video-column,.setup-panel,.recent-section{border:1px solid var(--ui-line);border-radius:var(--ui-radius-card);background:var(--ui-surface)}
.video-column{min-width:0;overflow:hidden}
.video-drop{min-height:540px;padding:40px;display:grid;place-items:center;align-content:center;gap:12px;background:#242629;color:#fff;text-align:center;cursor:pointer;transition:background .18s ease-out}
.video-drop.dragging,.video-drop:hover{background:#2d3033}.drop-icon{width:42px;height:42px;color:var(--ui-brand)}
.video-drop strong{font-size:21px}.video-drop>span{color:#bfc2c4;font-size:13px}
.secondary-button,.replace-video,.cancel-action{min-height:38px;padding:0 15px;border:1px solid var(--ui-line-strong);border-radius:var(--ui-radius-small);background:var(--ui-surface);color:var(--ui-ink);font:inherit;font-size:13px;font-weight:600;cursor:pointer}
.video-drop .secondary-button{margin-top:8px;border-color:#696c70;background:transparent;color:#fff}
.video-stage{position:relative;min-height:420px;max-height:650px;background:#17191b;display:flex;align-items:center;justify-content:center;overflow:hidden}
.video-canvas{position:relative;max-width:100%;max-height:650px;display:inline-flex}
.video-stage video{display:block;width:auto;height:auto;max-width:100%;max-height:650px;object-fit:contain}
.hold-overlay{position:absolute;inset:0;margin:auto;width:100%;height:100%;pointer-events:none}
.hold-box{position:absolute;border:2px solid var(--ui-brand);border-radius:7px;box-shadow:0 3px 12px rgba(0,0,0,.28)}
.hold-box b{position:absolute;top:-10px;left:-8px;min-width:21px;height:21px;padding:0 4px;border-radius:7px;background:var(--ui-brand);color:var(--ui-brand-ink);display:grid;place-items:center;font-size:11px}
.replace-video{position:absolute;right:14px;top:14px;border-color:rgba(255,255,255,.45);background:rgba(20,21,22,.82);color:#fff}
.analysis-state{padding:18px 20px;border-top:1px solid var(--ui-line);background:var(--ui-surface-subtle)}
.state-copy{display:grid;grid-template-columns:34px minmax(0,1fr) auto;align-items:center;gap:11px}.state-copy p{margin:3px 0 0;color:var(--ui-ink-muted);font-size:12px}.state-copy>b{font-variant-numeric:tabular-nums}.state-mark{width:32px;height:32px;border-radius:10px;background:var(--ui-surface);display:grid;place-items:center}.state-mark svg{width:18px}.running .state-mark svg,.queued .state-mark svg{animation:spin 1s linear infinite}.succeeded .state-mark{color:var(--ui-success)}.failed .state-mark{color:var(--ui-danger)}
.progress-track{height:5px;margin-top:14px;border-radius:5px;background:var(--ui-line);overflow:hidden}.progress-track i{display:block;height:100%;border-radius:inherit;background:var(--ui-brand);transition:width .35s ease-out}.state-actions{margin-top:12px}
.setup-panel{position:sticky;top:86px;padding:24px}.setup-panel h2,.result-report h2,.recent-heading h2{margin:0;font-size:20px}.setup-panel>div>p{margin:7px 0 0;color:var(--ui-ink-muted);font-size:13px;line-height:1.6}.setup-panel fieldset{margin:26px 0 0;padding:0;border:0}.setup-panel legend{margin-bottom:10px;font-size:13px;font-weight:600}
.color-options{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:7px}.color-options label{min-height:42px;padding:0 10px;border:1px solid var(--ui-line);border-radius:var(--ui-radius-small);display:flex;align-items:center;gap:8px;font-size:13px;cursor:pointer}.color-options label.selected{border-color:var(--ui-ink);background:var(--ui-surface-subtle)}.color-options input{position:absolute;opacity:0;pointer-events:none}.color-options i{width:14px;height:14px;border:1px solid rgba(0,0,0,.2);border-radius:50%}
.privacy-check{margin-top:22px;display:grid;grid-template-columns:17px 1fr;gap:9px;color:var(--ui-ink-muted);font-size:12px;line-height:1.5;cursor:pointer}.privacy-check input{width:16px;height:16px;margin:1px 0;accent-color:var(--ui-ink)}
.primary-action{width:100%;min-height:48px;margin-top:16px;border:0;border-radius:var(--ui-radius-control);background:var(--ui-brand);color:var(--ui-brand-ink);display:flex;align-items:center;justify-content:center;gap:8px;font:inherit;font-weight:700;cursor:pointer}.primary-action:hover:not(:disabled){background:var(--ui-brand-hover)}.primary-action:disabled{cursor:not-allowed;opacity:.45}.primary-action svg{width:17px;animation:spin 1s linear infinite}.cancel-action{width:100%;margin-top:8px}.form-error{margin:12px 0 0;color:var(--ui-danger);font-size:12px;line-height:1.5}
.shooting-guide{margin-top:28px;padding-top:22px;border-top:1px solid var(--ui-line)}.shooting-guide h3,.sequence-block h3{margin:0;font-size:13px}.shooting-guide ul{margin:13px 0 0;padding:0;list-style:none;display:grid;gap:12px}.shooting-guide li{display:grid;grid-template-columns:22px 1fr;gap:8px;color:var(--ui-ink-muted);font-size:12px;line-height:1.5}.shooting-guide li span{width:21px;height:21px;border-radius:7px;background:var(--ui-surface-subtle);color:var(--ui-ink);display:grid;place-items:center;font-weight:600}
.result-report{padding:24px;border-top:1px solid var(--ui-line)}.result-summary{display:flex;align-items:flex-start;justify-content:space-between;gap:16px}.result-summary p{margin:5px 0 0;color:var(--ui-ink-muted);font-size:13px}.result-summary>strong{font-size:26px;font-variant-numeric:tabular-nums}.sequence-block{margin-top:25px}.hold-sequence{margin-top:11px;display:flex;align-items:center;gap:7px;flex-wrap:wrap}.hold-sequence span{width:32px;height:32px;border-radius:9px;background:var(--ui-brand);color:var(--ui-brand-ink);display:grid;place-items:center;font-weight:700}.hold-sequence svg{width:14px;color:var(--ui-ink-faint)}.empty-result{color:var(--ui-ink-muted);font-size:13px}
.limb-table{margin-top:22px;border-top:1px solid var(--ui-line)}.limb-table>div{min-height:50px;border-bottom:1px solid var(--ui-line);display:grid;grid-template-columns:70px 80px 1fr;align-items:center;gap:10px;font-size:13px}.limb-table strong{font-variant-numeric:tabular-nums}.limb-table small{color:var(--ui-ink-muted);text-align:right}.review-notes{margin-top:18px;color:var(--ui-ink-muted);font-size:12px}.review-notes summary{color:var(--ui-ink);cursor:pointer;font-weight:600}.review-notes ul{margin:9px 0 0;padding-left:18px;line-height:1.7}
.recent-section{margin-top:22px;padding:22px}.recent-heading{display:flex;align-items:center;justify-content:space-between;margin-bottom:10px}.recent-heading span{color:var(--ui-ink-muted);font-size:12px}.recent-row{width:100%;min-height:58px;padding:9px 4px;border:0;border-top:1px solid var(--ui-line);background:transparent;color:var(--ui-ink);display:grid;grid-template-columns:10px minmax(0,1fr) auto;align-items:center;gap:12px;text-align:left;cursor:pointer}.recent-row>span:nth-child(2){min-width:0;display:grid;gap:3px}.recent-row strong,.recent-row small{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.recent-row small{color:var(--ui-ink-muted)}.recent-row>b{font-size:12px}.recent-dot{width:8px;height:8px;border-radius:50%;background:var(--ui-warning)}.recent-dot.succeeded{background:var(--ui-success)}.recent-dot.failed{background:var(--ui-danger)}.recent-dot.cancelled{background:var(--ui-ink-faint)}
.visually-hidden{position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap;border:0}
@keyframes spin{to{transform:rotate(360deg)}}
@media(max-width:900px){.replay-page{padding:24px 16px 88px}.replay-workspace{grid-template-columns:1fr}.setup-panel{position:static}.video-drop{min-height:340px}.video-stage{min-height:300px}.color-options{grid-template-columns:repeat(2,minmax(0,1fr))}}
@media(max-width:520px){.replay-heading{align-items:flex-start}.prototype-badge{margin-top:4px}.video-stage{min-height:250px}.color-options{grid-template-columns:repeat(4,1fr)}.limb-table>div{grid-template-columns:58px 64px 1fr}.recent-section{padding:18px}.result-report{padding:20px}.result-summary>strong{font-size:21px}}
@media(prefers-reduced-motion:reduce){.progress-track i,.video-drop{transition:none}.running .state-mark svg,.queued .state-mark svg,.primary-action svg{animation:none}}
</style>
