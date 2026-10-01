<template>
  <section class="coaching-panel" aria-labelledby="coaching-title" :aria-busy="loading || submitting">
    <div class="coaching-heading">
      <div><h2 id="coaching-title">个性化复盘</h2><p>先核对一处画面现象；依据和条件充分时，再给一项下次可验证的尝试。</p></div>
      <span class="coaching-prototype">试验功能</span>
    </div>

    <p v-if="loading" class="coaching-note" role="status">正在读取报告…</p>
    <p v-if="error" class="coaching-error" role="alert">{{ error }}</p>
    <button v-if="loadFailed" class="coaching-secondary" type="button" @click="load">重新读取</button>
    <p v-if="!mediaAvailable" class="coaching-note">本次可对应时间的复盘视频与分析副本均不可用，无法生成新的画面分析。已有报告的片段依据需要重新核实。</p>
    <p v-else-if="policy && (!policy.enabled || !policy.configured)" class="coaching-note">服务尚未配置或开放，请联系管理员完成视觉服务配置后重试。</p>
    <p v-if="envelope.stale" class="coaching-stale" role="status">依据已更新。{{ envelope.stale_reason || '岩点、动作复核或视频发生了变化。' }} 上一份报告不再作为当前建议，请重新生成。</p>
    <p v-else-if="legacyReport" class="coaching-stale" role="status">这份旧报告尚未通过当前的画面复核和建议条件检查，原文仍保留，但不再展示为行动建议。请重新生成核对；这可能产生新的分析费用。</p>
    <div v-if="busy" class="coaching-progress" role="status">
      <p>{{ envelope.status === 'queued' ? '报告正在排队' : '正在核对画面和知识依据' }}。完成后会显示在这里，离开页面后仍会继续。</p>
      <button class="coaching-secondary" type="button" :disabled="submitting" @click="cancel">停止生成</button>
      <button v-if="pollFailed" class="coaching-secondary" type="button" @click="refresh">重新查询进度</button>
    </div>
    <p v-if="envelope.status === 'failed'" class="coaching-error" role="alert">{{ envelope.error || '本次报告未生成，请稍后重试。' }}</p>
    <p v-if="envelope.status === 'cancelled'" class="coaching-note">已停止后续调用。已发送的内容和已产生的费用不能撤回；重新尝试可能追加费用。</p>
    <details v-if="envelope.id && !currentReport" class="coaching-cost">
      <summary>已知个性化分析费用估算：{{ costLabel(analysisCost) }}</summary>
      <p>{{ analysisCost?.basis || '本次用量记录不完整，不能按零元计算。' }}</p>
      <p v-if="analysisCost?.reason">{{ analysisCost.reason }}</p>
      <p v-if="costIncomplete">费用可能不完整，未收到完整用量的请求仍可能计费。</p>
      <p>原有姿态处理：{{ costLabel(originalPoseCost) }}；已知两项合计：{{ costLabel(totalCost) }}。</p>
      <p>免费额度与优惠未计入，实际扣费以供应商账单为准。</p>
      <ul v-if="envelope.previous_attempt_costs?.length"><li v-for="(attempt, index) in envelope.previous_attempt_costs" :key="attempt.id">此前尝试 {{ index + 1 }}（另计）：{{ costLabel(attempt.cost) }}</li></ul>
    </details>

    <div v-if="!busy && !loading" class="coaching-entry">
      <button v-if="!showForm" class="coaching-primary" type="button" :disabled="!canGenerate || preflightPending || templateBusy" @click="openForm('report')">{{ preflightPending ? '正在检查本次资料…' : envelope.id ? '重新生成个性化复盘' : '生成个性化复盘' }}</button>
      <p v-if="!currentReport && !showForm && canGenerate" class="coaching-note">个人信息可全部跳过。每次零至一项技术建议，也可能只得到画面观察或资料不足的说明。</p>
    </div>

    <ReplayTemplatePanel ref="templatePanel" :job="job" :policy="policy" :request-disabled="loading || submitting || preflightPending || showForm || loadFailed" @request="openForm('template')" @busy="templateBusy = $event" />

    <form v-if="showForm && (!busy || generationMode === 'template')" ref="consentForm" class="coaching-form" @submit.prevent="generate">
      <p v-if="generationMode === 'template'" class="coaching-template-context"><strong>按模板生成复盘视频</strong><br />确认以下资料与授权后，Agent 会复用有效分析或完成本次分析，再制作独立成片。</p>
      <fieldset :disabled="submitting || !canGenerate">
        <legend>这次最想改善什么？<span>选填</span></legend>
        <label class="coaching-field">本次目标<textarea v-model="context.goal" rows="2" maxlength="500" placeholder="例如：想知道第三次换手前可以怎样调整" /></label>
        <div class="coaching-fields coaching-focus-fields">
          <label class="coaching-field">关注片段开始（秒）<input v-model.number="context.focus_start_seconds" type="number" min="0" :max="duration || undefined" step="0.1" placeholder="可留空" /></label>
          <label class="coaching-field">关注片段结束（秒）<input v-model.number="context.focus_end_seconds" type="number" min="0" :max="duration || undefined" step="0.1" placeholder="可留空" /></label>
        </div>
        <details class="coaching-input-details">
          <summary>补充个人背景与本次状态（全部选填）</summary>
          <p class="coaching-note">信息只随本次报告保存。没有填写的内容保持未知；体重仅保留本次快照，不发送给视觉模型。自述不适或活动限制会约束建议，不能据此诊断或判断动作原因。</p>
          <div class="coaching-fields">
            <label class="coaching-field">身高（厘米）<input v-model.number="personal.height_cm" type="number" min="0.1" max="300" step="0.1" placeholder="可留空" /></label>
            <label class="coaching-field">臂展（厘米）<input v-model.number="personal.arm_span_cm" type="number" min="0.1" max="350" step="0.1" placeholder="可留空" /></label>
            <label class="coaching-field">体重（千克）<input v-model.number="personal.weight_kg" type="number" min="0.1" max="500" step="0.1" placeholder="可留空" /></label>
            <label class="coaching-field">攀龄（年）<input v-model.number="personal.climbing_years" type="number" min="0" max="100" step="0.1" placeholder="可留空" /></label>
            <label class="coaching-field">常爬难度<input v-model.trim="personal.usual_grade" type="text" maxlength="60" placeholder="例如 V2–V3" /></label>
            <label class="coaching-field">疲劳情况<input v-model.trim="context.fatigue" type="text" maxlength="300" placeholder="仅填写你愿意提供的情况" /></label>
            <label class="coaching-field coaching-field-wide">不适或疼痛<input v-model.trim="context.discomfort" type="text" maxlength="300" placeholder="可留空，留空不代表没有不适" /></label>
            <label class="coaching-field coaching-field-wide">活动限制<input v-model.trim="context.movement_limitations" type="text" maxlength="300" placeholder="例如某个动作目前不方便完成" /></label>
          </div>
        </details>
        <div class="coaching-consent" v-if="policy">
          <strong>本次将使用云端视觉分析</strong>
          <p>{{ policy.purpose || '核对攀爬画面并生成有依据的个性化复盘。' }}</p>
          <p>将发送给 {{ policy.provider }}：{{ (policy.data_types || []).join('、') || '可对应时间的抽样画面和必要定位信息' }}。{{ policy.full_video_sent ? '服务会使用完整视频。' : '不会发送完整视频。' }}</p>
          <p>观察画面时不使用个人背景或目标推断事实；目标、片段范围与确有用途的背景只在后续筛选中使用。体重不发送给模型。</p>
          <p>个人背景随报告保存；删除本次复盘时一并删除。画面与建议仍可能有误，请结合实际情况判断。</p>
          <p v-if="observationOnly">{{ policy.observation_only_notice || '目前没有获准的适用知识。本次仅能整理画面观察，不能生成技术建议。' }}</p>
          <p v-else>本次最多生成一项技术建议。即使已存在获准知识，画面或条件不足时仍只提供观察。</p>
          <p>生成前计划费用范围：{{ plannedCostLabel }}（仅个性化分析）。内部调用预算上限 {{ budgetLabel }}，达到预算或请求次数限制后停止后续调用。</p>
          <p>这是内部预算控制，不是固定报价或供应商精确硬停费承诺；已发出的请求可能继续计费。未计入原有姿态处理、免费额度和优惠。失败、取消或重试也可能产生费用。</p>
          <p v-if="envelope.id">已存在本次分析记录；相同有效结果会优先复用，需要新调用时可能追加费用。</p>
          <label><input v-model="indoorBoulderingConfirmed" type="checkbox" />本次是室内抱石录像</label>
          <label v-if="observationOnly"><input v-model="observationOnlyAccepted" type="checkbox" />我选择仅生成画面观察，知道本次不会给出技术建议</label>
          <label><input v-model="budgetAccepted" type="checkbox" />我已了解费用范围、内部预算限制，以及失败或重试可能产生费用</label>
          <label><input v-model="consentGranted" type="checkbox" />我同意将上述画面和必要信息用于本次云端分析</label>
        </div>
        <div class="coaching-actions"><button class="coaching-primary" type="submit" :disabled="!readyToSubmit">{{ submitting ? '正在提交…' : generationMode === 'template' ? (observationOnly ? '同意并制作观察成片' : '同意并制作模板成片') : observationOnly ? '同意并生成画面观察' : '同意并生成报告' }}</button><button class="coaching-secondary" type="button" :disabled="submitting" @click="showForm = false">收起</button></div>
      </fieldset>
    </form>

    <div v-if="currentReport" class="coaching-report">
      <section class="coaching-priority" aria-label="本次首要重点">
        <h3>{{ focus?.kind === 'adjustment' ? '可以尝试一项调整' : currentReport.result_status === 'review' ? '先核对片段' : '资料不足' }}</h3>
        <template v-if="focus">
          <p class="coaching-priority-text">{{ focus.text }}</p>
          <p v-if="focus.kind === 'adjustment'">已核实的现象：{{ readableObservation(focus.item.observation) }}</p>
          <p v-if="focus.reason">{{ focus.reason }}</p>
          <p v-if="focus.verification"><strong>{{ focus.kind === 'adjustment' ? '下次观察：' : '回看时核对：' }}</strong>{{ focus.verification }}</p>
          <button class="coaching-clip" type="button" :disabled="!mediaAvailable" @click="seek(focus.item)">回看 {{ timeLabel(focus.item.start_seconds) }}–{{ timeLabel(focus.item.end_seconds) }}</button>
          <p v-if="focus.kind === 'review'" class="coaching-note">这是需要核对的画面现象，还不能认定为动作问题。</p>
        </template>
        <template v-else>
          <p v-if="currentReport.result_status === 'review'">目前还不能确定哪一段更优先。下方观察可分别回看核对，不能据此认定为动作问题。</p>
          <p v-else>目前无法确认一项适用的技术建议，也不能判断哪一处更需要改善。</p>
        </template>
        <ul v-if="focus?.kind !== 'adjustment'" class="coaching-reasons"><li v-for="reason in reasons" :key="reason">{{ reason }}</li></ul>
      </section>
      <details class="coaching-cost">
        <summary>本次费用估算：个性化分析 {{ costLabel(analysisCost) }} · 姿态处理 {{ costLabel(originalPoseCost) }}</summary>
        <p>两项合计估算：{{ costLabel(totalCost) }}。生成前预算与这里的用量估算不同。</p>
        <p>{{ analysisCost?.basis || '用量未记录完整，无法估算实际费用。' }}</p>
        <p v-if="analysisCost?.reason">{{ analysisCost.reason }}</p>
        <p v-if="costIncomplete">费用可能不完整，未收到完整用量的请求仍可能计费。</p>
        <p>免费额度与优惠未计入，实际扣费以供应商账单为准。</p>
        <ul v-if="envelope.previous_attempt_costs?.length"><li v-for="(attempt, index) in envelope.previous_attempt_costs" :key="attempt.id">此前尝试 {{ index + 1 }}（另计）：{{ costLabel(attempt.cost) }}</li></ul>
        <p v-if="currentReport.provenance?.usage">输入 {{ currentReport.provenance.usage.prompt_tokens ?? '未知' }} token，输出 {{ currentReport.provenance.usage.completion_tokens ?? '未知' }} token。</p>
        <a v-if="safeUrls([currentReport.provenance?.cost?.source_url]).length" :href="currentReport.provenance.cost.source_url" target="_blank" rel="noopener noreferrer">查看百炼计价说明</a>
      </details>
      <section class="coaching-overview"><h3>本次概览</h3><p>{{ currentReport.overview }}</p></section>
      <component :is="group.collapsed ? 'details' : 'section'" v-for="group in reportGroups" :key="group.kind" class="coaching-group" :aria-label="group.title">
        <component :is="group.collapsed ? 'summary' : 'h3'">{{ group.title }}</component>
        <p v-if="!group.items.length" class="coaching-note">{{ group.empty }}</p>
        <article v-for="item in group.items" :key="item.id" class="coaching-item">
          <div class="coaching-item-heading"><h4>{{ item.title }}</h4><button class="coaching-clip" type="button" :disabled="!mediaAvailable || !validTime(item.start_seconds)" @click="seek(item)">回看 {{ timeLabel(item.start_seconds) }}<template v-if="validTime(item.end_seconds)">–{{ timeLabel(item.end_seconds) }}</template></button></div>
          <p class="coaching-evidence-label">{{ evidenceLabel(item) }}</p>
          <p><strong>画面观察</strong>{{ readableObservation(item.observation) }}</p>
          <p v-if="group.kind === 'improvements' && item.conditions?.length"><strong>适用条件</strong>{{ item.conditions.join('；') }}</p>
          <details class="coaching-evidence">
            <summary>查看依据与适用信息</summary>
            <p v-if="group.kind === 'improvements' && item.possible_explanation"><strong>知识说明与限制：</strong>{{ item.possible_explanation }}</p>
            <div class="coaching-evidence-times"><span>画面依据：</span><button v-for="frame in item.evidence || []" :key="frame.frame_id" class="coaching-clip" type="button" :disabled="!mediaAvailable || !validTime(frame.time_seconds)" @click="seek({ start_seconds: frame.time_seconds })">{{ timeLabel(frame.time_seconds) }}</button><span v-if="!item.evidence?.length">未提供可定位画面</span></div>
            <p v-if="item.personal_factors?.length">使用的个人信息：{{ item.personal_factors.map(personalFactor).join('；') }}</p>
            <p v-if="item.user_report">用户自述：{{ item.user_report }}</p>
            <ul v-if="item.knowledge_refs?.length" class="coaching-sources"><li v-for="source in item.knowledge_refs" :key="source.unit_id"><span>{{ source.title }}<small v-if="source.version"> · {{ source.version }}</small></span><a v-for="(url, index) in safeUrls(source.source_urls)" :key="url" :href="url" target="_blank" rel="noopener noreferrer">查看来源{{ index + 1 }}</a></li></ul>
            <p v-else class="coaching-note">此项没有已审核知识引用，仅供核对观察。</p>
          </details>
          <label class="coaching-field coaching-feedback-reason">具体原因（选填）<select v-model="feedbackReasons[item.id]"><option value="">暂不选择</option><option v-for="reason in feedbackReasonChoices" :key="reason.value" :value="reason.value">{{ reason.label }}</option></select></label>
          <div class="coaching-feedback" :aria-label="`反馈：${item.title}`"><span>这条复盘</span><button v-for="choice in feedbackChoices" :key="choice.kind" type="button" :aria-pressed="hasFeedback(item.id, choice.kind)" :disabled="Boolean(feedbackPending) || submitting || busy" @click="submitFeedback(item.id, choice.kind)">{{ choice.label }}</button></div>
        </article>
      </component>
      <details class="coaching-limitations"><summary>依据与限制</summary><p>本次核对 {{ currentReport.coverage?.frames_reviewed || 0 }} 张抽样画面。抽样之间的快速动作可能无法看清；叠加骨架、接触标签和编号只作定位，不能证明动作事实。</p><ul><li v-for="limit in currentReport.limitations || []" :key="limit">{{ limit }}</li></ul><p>本版不提供个性化伤害风险判断。没有风险提醒不表示已确认安全。</p><ul v-if="currentReport.personal_information_used?.length"><li v-for="used in currentReport.personal_information_used" :key="used.field">{{ personalFactor(used.field) }}：{{ used.purpose }}（{{ used.source === 'user_selected_range' ? '你选择的片段' : '本次自述' }}）</li></ul><p v-else>本次报告未记录使用个人背景；不能把缺填视为没有不适。</p><p v-if="policy?.knowledge_notice">{{ policy.knowledge_notice }}</p><p v-if="currentReport.provenance?.model">本次视觉服务：{{ currentReport.provenance.provider }} · {{ currentReport.provenance.model }}</p></details>
      <p v-if="feedbackNotice" class="coaching-note" role="status">{{ feedbackNotice }}</p>
    </div>
    <details v-if="envelope.id" class="coaching-permission"><summary>本次报告的云端授权</summary><p class="coaching-note">撤回后停止后续画面发送，当前报告将标为不可用。已经完成的云端处理无法撤销；需要新报告时可重新明确授权。</p><button class="coaching-secondary" type="button" :disabled="submitting" @click="withdrawConsent">撤回本次报告授权</button></details>
  </section>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, reactive, ref, watch } from 'vue'
import ReplayTemplatePanel from './ReplayTemplatePanel.vue'
import climbReplayService from '../services/climbReplayService'
import { coachingErrorMessage } from '../services/coachingErrors'
import { reportFocus, reportIsCurrent, noAdviceReasons, costLabel, poseCost, combinedCost, evidenceLabel, readableObservation } from '../services/coachingPresentation'

const props = defineProps({ job: { type: Object, required: true }, mediaAvailable: { type: Boolean, default: false } })
const emit = defineEmits(['seek'])
const policy = ref(null)
const envelope = ref({ status: 'none', feedback: [] })
const loading = ref(true)
const submitting = ref(false)
const showForm = ref(false)
const generationMode = ref('report')
const templatePanel = ref(null)
const templateBusy = ref(false)
const consentForm = ref(null)
const consentGranted = ref(false)
const indoorBoulderingConfirmed = ref(false)
const budgetAccepted = ref(false)
const observationOnlyAccepted = ref(false)
const preflightPending = ref(false)
const preflightReady = ref(false)
const error = ref('')
const loadFailed = ref(false)
const pollFailed = ref(false)
const feedbackPending = ref('')
const feedbackNotice = ref('')
const feedbackReasons = reactive({})
const emptyPersonal = () => ({ height_cm: '', arm_span_cm: '', weight_kg: '', climbing_years: '', usual_grade: '' })
const emptyContext = () => ({ goal: '', focus_start_seconds: '', focus_end_seconds: '', fatigue: '', discomfort: '', movement_limitations: '' })
const personal = reactive(emptyPersonal())
const context = reactive(emptyContext())
const feedbackChoices = [{ kind: 'helpful', label: '有帮助' }, { kind: 'inaccurate', label: '看错了' }, { kind: 'not_applicable', label: '不适用' }]
const feedbackReasonChoices = [{ value: 'body_part', label: '部位看错' }, { value: 'time', label: '时间错误' }, { value: 'knowledge', label: '知识不相关' }, { value: 'conditions', label: '条件不成立' }, { value: 'wording', label: '表达不清' }, { value: 'priority', label: '重点不对' }]
let generation = 0
let timer
let controller
let disposed = false
let readVersion = 0
const busy = computed(() => ['queued', 'running'].includes(envelope.value.status))
const canGenerate = computed(() => props.mediaAvailable && policy.value?.enabled && policy.value?.configured && !loadFailed.value)
const duration = computed(() => Number(props.job.video?.duration_seconds || props.job.result?.video?.duration_seconds || 0))
const currentReport = computed(() => reportIsCurrent(envelope.value, props.mediaAvailable) ? envelope.value.report : null)
const legacyReport = computed(() => envelope.value.report && (envelope.value.legacy || !['try', 'review', 'insufficient'].includes(envelope.value.report.result_status)))
const observationOnly = computed(() => policy.value?.advice_available !== true)
const readyToSubmit = computed(() => canGenerate.value && preflightReady.value && !submitting.value && !templateBusy.value && (generationMode.value !== 'template' || props.job.media?.source_video?.status === 'available') && indoorBoulderingConfirmed.value && consentGranted.value && budgetAccepted.value && (!observationOnly.value || observationOnlyAccepted.value))
const plannedCostLabel = computed(() => costLabel({ status: 'range', amount_min: policy.value?.budget?.estimate_min, amount_max: policy.value?.budget?.estimate_max }))
const budgetLabel = computed(() => costLabel({ status: 'estimated', amount_min: policy.value?.budget?.amount, amount_max: policy.value?.budget?.amount }))
const analysisCost = computed(() => envelope.value.cost || envelope.value.report?.provenance?.cost)
const originalPoseCost = computed(() => poseCost(props.job))
const totalCost = computed(() => combinedCost(analysisCost.value, originalPoseCost.value))
const costIncomplete = computed(() => analysisCost.value?.usage_complete === false || analysisCost.value?.status === 'partial' || envelope.value.usage_incomplete === true)
const focus = computed(() => reportFocus(currentReport.value))
const reasons = computed(() => noAdviceReasons(currentReport.value))
const reportGroups = computed(() => {
  const improvements = focus.value?.kind === 'adjustment' ? [focus.value.item] : []
  const improvementIds = new Set(improvements.map(item => item.observation_id || item.id))
  const observations = (currentReport.value?.observations || []).filter(item => !improvementIds.has(item.id))
  const hasFocus = focus.value?.kind === 'review'
  const visibleObservations = hasFocus ? observations.filter(item => item.id === focus.value.item.id) : []
  const visibleIds = new Set(visibleObservations.map(item => item.id))
  return [
    ...(improvements.length ? [{ kind: 'improvements', title: '改进重点', items: improvements }] : []),
    ...(visibleObservations.length ? [{ kind: 'observations', title: '对应画面观察', items: visibleObservations }] : []),
    { kind: 'other_observations', title: focus.value ? '其他画面观察' : '画面观察（尚未确认重点）', items: observations.filter(item => !visibleIds.has(item.id)), collapsed: true },
  ].filter(group => group.items.length)
})

function validTime(value) { return value !== null && value !== undefined && value !== '' && Number.isFinite(Number(value)) && Number(value) >= 0 }
function timeLabel(value) {
  if (!validTime(value)) return '时间未知'
  const seconds = Number(value)
  return `${Math.floor(seconds / 60)}:${(seconds % 60).toFixed(1).padStart(4, '0')}`
}
function safeUrls(urls) {
  return (Array.isArray(urls) ? urls : []).filter(value => {
    try { return typeof value === 'string' && new URL(value).protocol === 'https:' } catch { return false }
  })
}
function personalFactor(key) {
  const labels = { height_cm: '身高', arm_span_cm: '臂展', weight_kg: '体重', climbing_years: '攀龄', usual_grade: '常爬难度', goal: '本次目标', focus_start_seconds: '片段开始', focus_end_seconds: '片段结束', fatigue: '疲劳情况', discomfort: '不适或疼痛', movement_limitations: '活动限制' }
  const units = { height_cm: '厘米', arm_span_cm: '厘米', weight_kg: '千克', climbing_years: '年' }
  const value = envelope.value.personal?.[key] ?? envelope.value.context?.[key]
  return `${labels[key] || key}${value !== undefined && value !== null ? ` ${value}${units[key] || ''}` : ''}`
}
function seek(item) { if (props.mediaAvailable && validTime(item.start_seconds)) emit('seek', { start_seconds: Number(item.start_seconds), end_seconds: validTime(item.end_seconds) ? Number(item.end_seconds) : null }) }
function cleanFields(fields) { return Object.fromEntries(Object.entries(fields).filter(([, value]) => value !== '' && value !== null && value !== undefined)) }
const messageFor = coachingErrorMessage
function stopRequests() { clearTimeout(timer); controller?.abort() }
function accept(value, token) {
  if (disposed || token !== generation) return false
  envelope.value = value || { status: 'none', feedback: [] }
  pollFailed.value = false
  clearTimeout(timer)
  if (busy.value) timer = setTimeout(() => refresh(), 2500)
  return true
}
async function load() {
  stopRequests()
  controller = new AbortController()
  const token = ++generation
  const jobId = props.job.id
  loading.value = true
  loadFailed.value = false
  error.value = ''
  let resource = 'policy'
  try {
    // Check feature availability first so an older backend's 404 is not mistaken for a missing report.
    const nextPolicy = await climbReplayService.coachingPolicy(controller.signal)
    if (disposed || token !== generation) return
    resource = 'report'
    const nextEnvelope = await climbReplayService.coaching(jobId, controller.signal)
    if (disposed || token !== generation) return
    policy.value = nextPolicy
    accept(nextEnvelope, token)
    for (const key of Object.keys(personal)) personal[key] = nextEnvelope.personal?.[key] ?? ''
    for (const key of Object.keys(context)) context[key] = nextEnvelope.context?.[key] ?? emptyContext()[key]
  } catch (failure) {
    if (disposed || token !== generation) return
    error.value = messageFor(failure, '暂时无法读取个性化复盘，请重新读取。', resource)
    loadFailed.value = true
  } finally { if (!disposed && token === generation) loading.value = false }
}
async function refresh() {
  clearTimeout(timer)
  const token = generation
  const read = ++readVersion
  try {
    const value = await climbReplayService.coaching(props.job.id, controller?.signal)
    if (read === readVersion && accept(value, token)) error.value = ''
  }
  catch (failure) {
    if (disposed || token !== generation || read !== readVersion) return
    pollFailed.value = true
    error.value = messageFor(failure, '暂时无法查询报告进度，请重新查询。')
  }
}
async function openForm(mode = 'report') {
  if (preflightPending.value || !canGenerate.value || templateBusy.value || (busy.value && mode !== 'template')) return
  if (mode === 'template' && props.job.media?.source_video?.status !== 'available') return
  generationMode.value = mode
  preflightPending.value = true
  preflightReady.value = false
  error.value = ''
  const token = generation
  try {
    const value = await climbReplayService.coachingPreflight(props.job.id, controller?.signal)
    if (disposed || token !== generation) return
    if (value?.ready !== true) { error.value = '本次资料尚未通过检查，请重新读取状态后再试。'; return }
    policy.value = { ...policy.value, ...value }
    preflightReady.value = true
    consentGranted.value = false
    budgetAccepted.value = false
    observationOnlyAccepted.value = false
    showForm.value = true
    await nextTick()
    if (!disposed && token === generation) consentForm.value?.querySelector('textarea')?.focus({ preventScroll: false })
  } catch (failure) {
    if (!disposed && token === generation) error.value = messageFor(failure, '尚未完成视频与费用检查，请重试。', 'preflight')
  } finally { if (!disposed && token === generation) preflightPending.value = false }
}
async function generate() {
  if (!readyToSubmit.value || (busy.value && generationMode.value !== 'template')) return
  error.value = ''
  if (validTime(context.focus_start_seconds) !== validTime(context.focus_end_seconds)) {
    error.value = '关注片段需要同时填写开始与结束时间，也可以全部留空。'
    return
  }
  if (validTime(context.focus_start_seconds) && validTime(context.focus_end_seconds) && Number(context.focus_end_seconds) <= Number(context.focus_start_seconds)) {
    error.value = '关注片段的结束时间需要晚于开始时间。'
    return
  }
  submitting.value = true
  clearTimeout(timer)
  readVersion += 1
  const token = generation
  try {
    const isTemplate = generationMode.value === 'template'
    const create = isTemplate ? climbReplayService.generateTemplateVideo : climbReplayService.generateCoaching
    const value = await create(props.job.id, {
      consent_version: policy.value.version, consent_granted: true,
      indoor_bouldering_confirmed: true, budget_accepted: true, observation_only_accepted: observationOnlyAccepted.value,
      personal: cleanFields(personal), context: cleanFields(context),
    }, controller?.signal)
    if (disposed || token !== generation) return
    if (isTemplate) { templatePanel.value?.acceptGeneration(value); refresh() }
    else { accept(value, token); templatePanel.value?.reload() }
    showForm.value = false; consentGranted.value = false; budgetAccepted.value = false; observationOnlyAccepted.value = false; preflightReady.value = false; feedbackNotice.value = ''
  } catch (failure) {
    if (!disposed && token === generation) {
      error.value = generationMode.value === 'template' && failure?.response?.status === 404
        ? '模板成片服务或本次记录暂不可用，请更新或重启本地服务，并刷新复盘后重试。'
        : messageFor(failure, generationMode.value === 'template' ? '成片未能开始制作，请重新读取状态后重试。' : '报告未能开始生成，请稍后重试。')
      if (busy.value) timer = setTimeout(() => refresh(), 2500)
    }
  } finally { if (!disposed && token === generation) submitting.value = false }
}
async function cancel() {
  if (submitting.value || !busy.value) return
  submitting.value = true
  clearTimeout(timer)
  readVersion += 1
  const token = generation
  try { accept(await climbReplayService.cancelCoaching(props.job.id, controller?.signal), token) }
  catch (failure) {
    if (!disposed && token === generation) {
      error.value = messageFor(failure, '暂时无法停止，请稍后重试。')
      if (busy.value) timer = setTimeout(() => refresh(), 2500)
    }
  }
  finally { if (!disposed && token === generation) submitting.value = false }
}
async function withdrawConsent() {
  if (submitting.value) return
  submitting.value = true
  clearTimeout(timer)
  readVersion += 1
  const token = generation
  try {
    if (accept(await climbReplayService.withdrawCoachingConsent(props.job.id, controller?.signal), token)) {
      consentGranted.value = false
      error.value = ''
      templatePanel.value?.reload()
    }
  } catch (failure) {
    if (!disposed && token === generation) {
      error.value = messageFor(failure, '授权暂未撤回，请重试。')
      if (busy.value) timer = setTimeout(() => refresh(), 2500)
    }
  }
  finally { if (!disposed && token === generation) submitting.value = false }
}
function hasFeedback(itemId, kind) { return (envelope.value.feedback || []).some(item => item.item_id === itemId && item.kind === kind) }
async function submitFeedback(itemId, kind) {
  if (!currentReport.value || feedbackPending.value || submitting.value || busy.value || hasFeedback(itemId, kind)) return
  feedbackPending.value = itemId
  const token = generation
  const read = ++readVersion
  try {
    const value = await climbReplayService.coachingFeedback(props.job.id, { report_id: envelope.value.id, item_id: itemId, kind, ...(feedbackReasons[itemId] ? { reason: feedbackReasons[itemId] } : {}) }, controller?.signal)
    if (read === readVersion && accept(value, token)) feedbackNotice.value = '反馈已保存，用于人工复核，不会自动修改知识或历史报告。“有帮助”不等于建议已验证有效。'
  } catch (failure) { if (!disposed && token === generation && read === readVersion) error.value = messageFor(failure, '反馈暂未保存，请重试。') }
  finally { if (!disposed && token === generation) feedbackPending.value = '' }
}
watch(() => props.job.id, () => {
  envelope.value = { status: 'none', feedback: [] }
  policy.value = null
  showForm.value = false
  generationMode.value = 'report'
  consentGranted.value = false
  indoorBoulderingConfirmed.value = false
  budgetAccepted.value = false
  observationOnlyAccepted.value = false
  preflightPending.value = false
  preflightReady.value = false
  submitting.value = false
  feedbackPending.value = ''
  feedbackNotice.value = ''
  for (const key of Object.keys(feedbackReasons)) delete feedbackReasons[key]
  Object.assign(personal, emptyPersonal())
  Object.assign(context, emptyContext())
  load()
}, { immediate: true })
watch(() => props.job, (job, previous) => {
  if (job.id !== previous?.id) return
  preflightReady.value = false
  preflightPending.value = false
  showForm.value = false
  submitting.value = false
  feedbackPending.value = ''
  if (envelope.value.report) envelope.value = { ...envelope.value, stale: true, stale_reason: '正在核对更新后的复盘依据。' }
  // A same-job evidence change invalidates every outstanding read and preflight.
  // Reloading also prevents a late mutation response from reviving an old report.
  load()
})
onBeforeUnmount(() => { disposed = true; generation += 1; stopRequests() })
</script>

<style scoped>
.coaching-panel{padding:26px 24px;border-top:1px solid var(--ui-line);color:var(--ui-ink);font-size:13px;line-height:1.7;overflow-wrap:anywhere}
.coaching-panel ::selection{background:var(--ui-brand);color:var(--ui-brand-ink)}
.coaching-panel :is(button,input,textarea,select,summary,a):focus-visible{outline:2px solid var(--ui-focus);outline-offset:3px}.coaching-permission{margin-top:22px;padding-top:10px;border-top:1px solid var(--ui-line);font-size:12px}
.coaching-heading{display:flex;justify-content:space-between;align-items:flex-start;gap:16px;margin-bottom:18px}.coaching-heading h2{margin:0;font-size:20px;line-height:1.4}.coaching-heading p{margin:6px 0 0;color:var(--ui-ink-muted);max-width:70ch}.coaching-prototype{flex:none;padding:2px 8px;border-radius:6px;background:var(--ui-surface-subtle);color:var(--ui-ink-muted);font-size:11px}
.coaching-note{color:var(--ui-ink-muted);max-width:72ch}.coaching-error{color:var(--ui-danger);max-width:72ch}.coaching-stale{padding:12px 14px;background:var(--ui-brand-soft);color:var(--ui-brand-ink);border-radius:8px}.coaching-progress{margin:16px 0}.coaching-progress p{max-width:72ch}.coaching-progress button+button{margin-left:8px}
.coaching-panel button{font:inherit;cursor:pointer}.coaching-primary,.coaching-secondary{min-height:42px;padding:8px 16px;border-radius:var(--ui-radius-small);font-weight:600!important}.coaching-primary{border:1px solid transparent;background:var(--ui-brand);color:var(--ui-brand-ink)}.coaching-primary:hover:not(:disabled){filter:brightness(.96)}.coaching-secondary{border:1px solid var(--ui-line-strong);background:var(--ui-surface);color:var(--ui-ink)}.coaching-secondary:hover:not(:disabled){background:var(--ui-surface-subtle)}.coaching-panel button:disabled{cursor:not-allowed;opacity:.5}.coaching-entry{margin:16px 0 0}
.coaching-form{margin:20px 0 0}.coaching-form fieldset{margin:0;padding:0;border:0;min-width:0}.coaching-form legend{padding:0;margin-bottom:12px;font-size:15px;font-weight:600}.coaching-form legend span{margin-left:8px;font-size:12px;color:var(--ui-ink-muted);font-weight:400}.coaching-fields{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px;margin-top:12px}.coaching-field{display:grid;gap:5px;color:var(--ui-ink-muted);font-size:12px}.coaching-field input,.coaching-field textarea,.coaching-field select{box-sizing:border-box;min-width:0;width:100%;min-height:42px;padding:9px 10px;border:1px solid var(--ui-line-strong);border-radius:8px;background:var(--ui-surface);color:var(--ui-ink);font:inherit;font-size:13px;caret-color:var(--ui-brand-ink)}.coaching-field textarea{resize:vertical}.coaching-field :is(input,textarea)::placeholder{color:var(--ui-ink-muted)}.coaching-field-wide{grid-column:1/-1}.coaching-input-details{margin-top:18px}.coaching-panel summary{cursor:pointer;min-height:40px;align-content:center;color:var(--ui-ink);text-underline-offset:4px}.coaching-panel summary:hover{text-decoration:underline}.coaching-consent{margin-top:22px;padding:16px;background:var(--ui-surface-subtle);border-radius:12px}.coaching-consent p{max-width:72ch;margin:6px 0;color:var(--ui-ink-muted);font-size:12px}.coaching-consent label{display:flex;gap:9px;align-items:flex-start;margin-top:12px}.coaching-consent input{flex:none;accent-color:var(--ui-brand-ink);width:17px;height:17px;margin:3px 0 0}.coaching-actions{display:flex;gap:10px;flex-wrap:wrap;margin-top:16px}
.coaching-report{margin-top:24px}.coaching-report h3{margin:24px 0 9px;font-size:16px;line-height:1.5}.coaching-report p{max-width:72ch;margin:8px 0}.coaching-overview h3{margin-top:0}.coaching-knowledge-note{padding:12px 0;border-bottom:1px solid var(--ui-line)}.coaching-group{margin-top:26px}.coaching-item{padding:18px 0;border-bottom:1px solid var(--ui-line)}.coaching-item-heading{display:flex;gap:10px 18px;align-items:baseline;justify-content:space-between}.coaching-item h4{margin:0;font-size:14px}.coaching-item p>strong{display:block;margin-top:12px;font-size:12px;font-weight:600;color:var(--ui-ink-muted)}.coaching-clip{border:0;background:none;color:var(--ui-brand-ink);padding:7px 0;text-decoration:underline;text-underline-offset:4px;font-variant-numeric:tabular-nums}.coaching-item-heading>.coaching-clip{flex:none}.coaching-evidence{margin:12px 0 0;font-size:12px}.coaching-evidence-times{display:flex;align-items:center;gap:6px 12px;flex-wrap:wrap;color:var(--ui-ink-muted)}.coaching-sources{padding-left:20px}.coaching-sources li{margin:8px 0}.coaching-sources a{display:inline-block;margin-left:12px;color:var(--ui-brand-ink);text-underline-offset:4px}.coaching-feedback{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin-top:12px;font-size:12px}.coaching-feedback>span{color:var(--ui-ink-muted);margin-right:4px}.coaching-feedback button{min-height:36px;padding:5px 10px;border:1px solid var(--ui-line);border-radius:6px;background:var(--ui-surface);color:var(--ui-ink-muted)}.coaching-feedback button:hover:not(:disabled),.coaching-feedback button[aria-pressed=true]{background:var(--ui-brand-soft);border-color:var(--ui-line-strong);color:var(--ui-brand-ink)}.coaching-next{margin-top:26px;padding:1px 0 16px}.coaching-limitations{padding-top:10px;border-top:1px solid var(--ui-line);color:var(--ui-ink-muted);font-size:12px}.coaching-limitations li{margin:5px 0;max-width:72ch}
.coaching-panel :is(button,summary,a,input:not([type="checkbox"]),textarea,select),.coaching-consent label{box-sizing:border-box;min-width:44px;min-height:44px}
.coaching-consent label{padding:10px 0;cursor:pointer}.coaching-sources a{display:inline-flex;align-items:center}
.coaching-focus-fields{grid-template-columns:repeat(2,minmax(0,1fr))}
.coaching-feedback-reason{max-width:280px;margin-top:18px}.coaching-reasons{padding-left:20px;max-width:72ch}.coaching-reasons li{margin-top:8px}
.coaching-priority{padding:20px 0;border-top:1px solid var(--ui-line-strong);border-bottom:1px solid var(--ui-line-strong)}.coaching-priority h3{margin:0 0 10px;font-size:20px}.coaching-priority-text{font-size:17px;font-weight:600;color:var(--ui-ink)}.coaching-cost{margin:14px 0;font-size:13px;color:var(--ui-ink-muted)}.coaching-cost a{display:inline-flex;align-items:center;min-height:44px;color:var(--ui-brand-ink)}.coaching-evidence-label{color:var(--ui-ink-muted);font-size:12px}
@media(max-width:650px){.coaching-fields{grid-template-columns:repeat(2,minmax(0,1fr))}.coaching-item-heading{display:block}.coaching-item-heading>.coaching-clip{margin-top:5px}.coaching-heading{gap:10px}.coaching-panel{padding:22px 16px;font-size:16px}.coaching-heading p,.coaching-field,.coaching-consent p,.coaching-evidence-label,.coaching-limitations,.coaching-cost,.coaching-evidence,.coaching-feedback{font-size:14px}.coaching-field input,.coaching-field textarea,.coaching-field select{font-size:16px}.coaching-consent{padding:14px 12px}}
@media(max-width:360px){.coaching-fields{grid-template-columns:1fr}.coaching-heading{flex-wrap:wrap}}
</style>
