<template>
  <section class="template-panel" aria-labelledby="template-title" :aria-busy="loading || cancelling">
    <h3 id="template-title">让 Agent 按模板制作复盘视频</h3>
    <p class="template-intro">以原视频为主体，连续看清动作，再读数据与重点。Agent 根据本次分析安排慢放、标注和转场，生成一份独立成片。</p>
    <ol class="template-outline" aria-label="视频模板结构">
      <li><strong>连续动作慢放解析</strong><span>按动作组串起攀爬过程，保留换点前后的动作关系。</span></li>
      <li><strong>基础数据</strong><span>整理可确认的用时、停留与四肢触点；缺少依据的数据会说明或省略。</span></li>
      <li><strong>{{ observationOnly ? '重点画面回看' : '重点动作与练习建议' }}</strong><span>{{ observationOnly ? '当前仅能提供画面观察，不生成动作纠正或练习建议。' : '有充分依据时给出一项调整与验证方式；依据不足时仅回看观察。' }}</span></li>
    </ol>

    <p v-if="!sourceAvailable" class="template-note">原视频不可用，暂时不能制作模板成片。请重新上传原视频；已有基础复盘仍可在上方观看。</p>
    <p v-else-if="policy && (!policy.enabled || !policy.configured)" class="template-note">模板使用的分析服务尚未开放或配置。请联系管理员完成配置后重试。</p>
    <p v-else-if="loading" class="template-note" role="status">正在读取模板成片状态…</p>
    <p v-if="error" class="template-error" role="alert">{{ error }}</p>
    <button v-if="readFailed" type="button" class="template-secondary" @click="reload">重新读取成片状态</button>
    <p v-if="state.stale" class="template-note" role="status">{{ state.stale_reason || '复盘依据或模板版本已更新。' }} 旧成片已停止展示，请按当前资料重新生成。</p>

    <div v-if="busy" class="template-progress" aria-live="polite">
      <p><strong>{{ progressLabel }}</strong><span class="template-percent">{{ progress }}%</span></p>
      <progress :value="progress" max="100" aria-label="模板成片生成进度" />
      <p class="template-note">{{ state.message || '完成后会显示在这里，离开页面后仍会继续。' }}</p>
      <button type="button" class="template-secondary" :disabled="cancelling" @click="cancel">{{ cancelling ? '正在停止…' : '停止制作成片' }}</button>
    </div>
    <p v-if="state.status === 'failed'" class="template-error" role="alert">{{ state.error || '本次成片未生成，请重试。' }} 基础复盘仍保留。</p>
    <p v-if="state.status === 'cancelled'" class="template-note">已停止制作成片，基础复盘仍保留。分析费用请在本次报告中查看。</p>

    <div v-if="mediaReady" class="template-result">
      <p v-if="state.status !== 'succeeded'" class="template-note">下方保留的是此前成功生成的成片。</p>
      <video :key="mediaUrl" :src="mediaUrl" controls playsinline preload="metadata" aria-label="Agent 模板复盘成片" @error="mediaFailed = true" />
      <p v-if="mediaFailed" class="template-error" role="alert">成片暂时无法播放，请重新读取状态，也可尝试下载后观看。</p>
      <div class="template-result-actions"><a :href="downloadUrl" download>下载模板成片</a><span v-if="mediaPlan?.duration_seconds">约 {{ Math.round(mediaPlan.duration_seconds) }} 秒</span><button v-if="mediaFailed" type="button" class="template-secondary" @click="reload">重新读取成片状态</button></div>
      <details v-if="mediaPlan?.chapters?.length" class="template-chapters"><summary>查看本次成片章节</summary><ol><li v-for="(chapter, index) in mediaPlan.chapters" :key="index">{{ chapter.title }}<span v-if="Number.isFinite(chapter.duration_seconds)"> · 约 {{ Math.round(chapter.duration_seconds) }} 秒</span></li></ol><template v-if="omittedMetrics.length"><p class="template-note">本次未展示的数据</p><ul class="template-note"><li v-for="(item, index) in omittedMetrics" :key="index">{{ item }}</li></ul></template></details>
    </div>
    <div v-if="!busy" class="template-entry">
      <button type="button" class="template-primary" :disabled="!canRequest || requestDisabled" @click="$emit('request')">{{ state.id ? '按模板重新生成' : '按模板生成复盘视频' }}</button>
      <p class="template-note">下一步确认分析资料与费用。相同有效分析优先复用，成片不会替换基础复盘。</p>
    </div>
  </section>
</template>

<script setup>
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import climbReplayService from '../services/climbReplayService'
import { coachingErrorMessage } from '../services/coachingErrors'

const props = defineProps({ job: { type: Object, required: true }, policy: { type: Object, default: null }, requestDisabled: { type: Boolean, default: false } })
const emit = defineEmits(['request', 'busy'])
const state = ref({ status: 'none' })
const loading = ref(false), cancelling = ref(false), readFailed = ref(false), error = ref(''), mediaFailed = ref(false)
let epoch = 0, readVersion = 0, timer, controller, disposed = false
const sourceAvailable = computed(() => props.job.media?.source_video?.status === 'available')
const observationOnly = computed(() => props.policy?.advice_available !== true)
const busy = computed(() => ['queued', 'waiting_report', 'running'].includes(state.value.status))
const canRequest = computed(() => sourceAvailable.value && props.policy?.enabled && props.policy?.configured && !loading.value && !readFailed.value)
const progress = computed(() => Math.round(Math.max(0, Math.min(100, Number(state.value.progress) || 0))))
const progressLabel = computed(() => ({ queued: '成片正在排队', waiting_report: '正在等待本次画面分析', running: '正在制作模板成片' })[state.value.status])
const mediaReady = computed(() => sourceAvailable.value && state.value.media_ready === true && !state.value.stale && !readFailed.value)
const mediaPlan = computed(() => state.value.media_plan || (state.value.status === 'succeeded' ? state.value.plan : null))
// A failed retry may retain an earlier movie. Cache identity belongs to that
// movie, not to the most recent rendering attempt.
const mediaVersion = computed(() => state.value.media_version || `${state.value.id || ''}-${state.value.finished_at || ''}`)
const mediaUrl = computed(() => climbReplayService.templateVideoMediaUrl(props.job.id, false, mediaVersion.value))
const downloadUrl = computed(() => climbReplayService.templateVideoMediaUrl(props.job.id, true, mediaVersion.value))
const omittedMetrics = computed(() => (mediaPlan.value?.omitted_metrics || []).map(item => {
  if (typeof item === 'string') return item
  const label = ({ elapsed_seconds: '攀爬用时', total_time: '攀爬用时', longest_hold: '最长已确认停留', limb_counts: '四肢不同触点数' })[item?.metric] || item?.metric || '部分数据'
  return item?.reason ? `${label}：${item.reason}` : label
}))
watch(busy, value => emit('busy', value), { immediate: true })

function messageFor(failure, fallback) {
  if (failure?.response?.status === 404) return '模板成片服务或本次记录暂不可用。请更新或重启本地服务，并刷新复盘后重新读取。'
  return coachingErrorMessage(failure, fallback)
}
function stop() { clearTimeout(timer); controller?.abort(); readVersion += 1 }
function acceptGeneration(value) {
  // Called only after the parent has checked its job/evidence request token.
  if (disposed) return
  readVersion += 1
  clearTimeout(timer)
  state.value = value || { status: 'none' }
  readFailed.value = false; error.value = ''; mediaFailed.value = false
  if (busy.value) timer = setTimeout(refresh, 2500)
}
async function refresh() {
  clearTimeout(timer)
  const token = epoch, read = ++readVersion
  try {
    const value = await climbReplayService.templateVideo(props.job.id, controller?.signal)
    if (disposed || token !== epoch || read !== readVersion) return
    acceptGeneration(value)
  } catch (failure) {
    if (disposed || token !== epoch || read !== readVersion) return
    readFailed.value = true
    error.value = messageFor(failure, '暂时无法读取成片进度，请重新读取状态。')
  } finally { if (!disposed && token === epoch) loading.value = false }
}
async function reload() {
  stop(); epoch += 1; controller = new AbortController()
  state.value = { status: 'none' }; error.value = ''; readFailed.value = false; mediaFailed.value = false; cancelling.value = false
  loading.value = Boolean(sourceAvailable.value && props.policy)
  if (loading.value) await refresh()
}
async function cancel() {
  if (cancelling.value || !busy.value) return
  cancelling.value = true; clearTimeout(timer); readVersion += 1
  const token = epoch
  try {
    const value = await climbReplayService.cancelTemplateVideo(props.job.id, controller?.signal)
    if (!disposed && token === epoch) acceptGeneration(value)
  } catch (failure) {
    if (disposed || token !== epoch) return
    error.value = messageFor(failure, '暂时无法停止制作，请重新读取状态后重试。')
    if (busy.value) timer = setTimeout(refresh, 2500)
  } finally { if (!disposed && token === epoch) cancelling.value = false }
}
watch([() => props.job, () => Boolean(props.policy)], reload, { immediate: true })
onBeforeUnmount(() => { disposed = true; epoch += 1; stop() })
defineExpose({ acceptGeneration, reload })
</script>

<style scoped>
.template-panel{margin-top:28px;padding:24px 0;border-top:1px solid var(--ui-line);border-bottom:1px solid var(--ui-line);color:var(--ui-ink)}
.template-panel h3{font-size:20px;line-height:1.4;margin:0 0 10px}.template-panel p{max-width:72ch;margin:10px 0}.template-intro,.template-note,.template-outline span{color:var(--ui-ink-muted)}
.template-outline{padding-left:24px;margin:20px 0 24px}.template-outline li{padding-left:4px;margin:12px 0}.template-outline strong,.template-outline span{display:block}.template-outline strong{font-size:14px}.template-outline span{margin-top:2px}
.template-entry{margin-top:20px}.template-entry .template-note{font-size:12px;margin-bottom:0}.template-panel button,.template-panel a{box-sizing:border-box;min-width:44px;min-height:44px;font:inherit;font-weight:600;cursor:pointer}.template-panel :is(button,a,summary,video):focus-visible{outline:2px solid var(--ui-focus);outline-offset:3px}
.template-primary,.template-secondary{padding:9px 16px;border-radius:var(--ui-radius-small)}.template-primary{border:1px solid transparent;background:var(--ui-brand);color:var(--ui-brand-ink)}.template-primary:hover:not(:disabled){background:var(--ui-brand-hover)}.template-secondary{border:1px solid var(--ui-line-strong);background:var(--ui-surface);color:var(--ui-ink)}.template-secondary:hover:not(:disabled){background:var(--ui-surface-subtle)}.template-panel button:disabled{opacity:.5;cursor:not-allowed}.template-error{color:var(--ui-danger)}
.template-progress{margin:24px 0}.template-progress>p:first-child{display:flex;gap:16px;justify-content:space-between;max-width:560px}.template-percent{font-variant-numeric:tabular-nums}.template-progress progress{display:block;width:100%;max-width:560px;height:8px;accent-color:var(--ui-brand-ink)}.template-progress .template-note{margin-bottom:14px}
.template-result{margin:24px 0}.template-result video{display:block;width:100%;max-height:70vh;background:#1c1e21;object-fit:contain}.template-result-actions{display:flex;align-items:center;gap:16px;flex-wrap:wrap;margin-top:8px}.template-result-actions a{display:inline-flex;align-items:center;color:var(--ui-brand-ink);text-underline-offset:4px}.template-result-actions span{color:var(--ui-ink-muted);font-variant-numeric:tabular-nums}.template-chapters{margin-top:12px}.template-chapters summary{min-height:44px;cursor:pointer;align-content:center}.template-chapters summary:hover{text-decoration:underline;text-underline-offset:4px}.template-chapters ol{padding-left:24px}.template-chapters li{margin:8px 0}
@media(max-width:650px){.template-panel{margin-top:24px;padding:22px 0}.template-panel h3{font-size:20px}.template-outline strong{font-size:16px}.template-outline span,.template-entry .template-note{font-size:14px}.template-result video{max-height:65vh}}
</style>
