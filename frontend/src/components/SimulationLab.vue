<template>
  <section class="page simulation-page">
    <header class="simulation-heading">
      <div>
        <h2>仿真审核</h2>
        <p>三个体型优先寻找最简静态 Beta；静态确认无解后可验证一次动态动作，动态结果始终转真人复核。</p>
      </div>
      <el-segmented v-model="mode" :options="modeOptions" />
    </header>

    <el-alert v-if="error" type="error" :closable="false" :title="error" show-icon />

    <template v-if="mode === 'single'">
      <div class="simulation-toolbar">
        <el-select v-model="selectedSourceId" filterable placeholder="选择标准板线路" @change="loadRoute">
          <el-option v-for="route in routes" :key="route.source_id" :value="route.source_id" :label="`${route.display_name} · ${route.grade}`" />
        </el-select>
        <el-select v-model="abilityGrade" aria-label="能力等级">
          <el-option v-for="grade in grades" :key="grade" :label="`${grade} 能力`" :value="grade" />
        </el-select>
        <el-select v-model="motionMode" class="motion-mode-select" aria-label="动作模式">
          <el-option v-for="option in motionModeOptions" :key="option.value" :label="option.label" :value="option.value" />
        </el-select>
        <el-button type="primary" :loading="running" :disabled="!selectedSourceId" @click="runSingle">运行三体型审核</el-button>
        <el-button v-if="running" @click="cancelTask">取消任务</el-button>
        <el-button v-if="report && report.verdict !== 'pass'" :loading="repairing" @click="createRepairs">生成修复副本</el-button>
      </div>

      <div class="simulation-workspace">
        <section class="simulation-board-panel" aria-label="线路与骨架回放">
          <BoardCanvas
            v-if="activeDetail"
            class="standard-preview-canvas simulation-canvas"
            :columns="columns"
            :rows="rows"
            :base-holds="activeDetail.board_setup || []"
            :route-overlay="activeDetail.route_overlay || []"
            :holds="activeDetail.board_asset?.placed_holds || []"
            :route-steps="activeDetail.board_asset?.beta_sequence || []"
            :selected-hold="null"
            :board-spec="boardSpec"
            :frame-style="boardFrameStyle"
            :get-coord-style="getCoordStyle"
            :resolve-hold-visual="resolveHoldVisual"
            :skeleton-frame="activeFrame"
          />
          <div v-else class="simulation-empty">
            <strong>选择一条标准板线路</strong>
            <span>系统会保持线路可见，再开始仿真审核。</span>
          </div>

          <div v-if="playbackFrames.length" class="playback-controls">
            <el-button :aria-label="playing ? '暂停回放' : '播放回放'" @click="togglePlayback">{{ playing ? '暂停' : '播放' }}</el-button>
            <el-button :disabled="frameIndex <= 0" @click="frameIndex -= 1">上一步</el-button>
            <el-button :disabled="frameIndex >= playbackFrames.length - 1" @click="frameIndex += 1">下一步</el-button>
            <el-select v-model="playbackSpeed" class="playback-speed" size="small" aria-label="回放速度">
              <el-option v-for="speed in playbackSpeeds" :key="speed" :label="`${speed}×`" :value="speed" />
            </el-select>
            <el-slider v-model="frameIndex" :min="0" :max="Math.max(0, playbackFrames.length - 1)" :step="1" :show-tooltip="false" />
            <span>姿态 {{ frameIndex }} / {{ playbackFrames.length - 1 }}</span>
            <span v-if="activeFrame">{{ phaseLabel(activeFrame.phase) }} · 负荷 {{ percent(activeFrame.load_ratio) }} · 疲劳 {{ percent(activeFrame.fatigue) }}</span>
          </div>
        </section>

        <aside class="simulation-report-panel">
          <template v-if="report">
            <div class="verdict-row">
              <span class="simulation-verdict" :class="`is-${report.verdict}`">{{ report.verdict_label }}</span>
              <span>影子审核</span>
            </div>
            <h3>{{ report.route.display_name }}</h3>
            <p>{{ report.summary }}</p>

            <dl class="simulation-metrics">
              <div><dt>体型通过</dt><dd>{{ report.pass_count }} / {{ report.profile_count }}</dd></div>
              <div><dt>可行性</dt><dd>{{ Math.round(report.feasibility_score) }}</dd></div>
              <div><dt>等效难度</dt><dd>{{ report.predicted_grade || '-' }}</dd></div>
              <div><dt>置信度</dt><dd>{{ percent(report.confidence) }}</dd></div>
            </dl>

            <div class="simulation-run-tabs" role="tablist" aria-label="虚拟攀爬者">
              <button
                v-for="(run, index) in report.runs"
                :key="run.profile_id"
                :class="{ active: activeRunIndex === index }"
                role="tab"
                :aria-selected="activeRunIndex === index"
                @click="selectRun(index)"
              >
                <strong>{{ run.profile_label }}</strong>
                <span>{{ runStatus(run.status) }} · {{ percent(run.robustness) }}</span>
              </button>
            </div>

            <section v-if="activeRun && activeFrame" class="action-explanation" aria-live="polite">
              <header>
                <strong>本步动作</strong>
                <span>{{ activeAction ? `第 ${activeFrame.step} 步` : '起步姿态' }}</span>
              </header>
              <div class="action-movement">{{ actionMovementText }}</div>
              <p v-if="activeAction">
                目的：{{ activeAction.purpose }} · 技术：{{ techniqueLabel(activeAction.technique) }}
                <span v-if="isTechniqueException(activeAction.technique)" class="technique-exception">技术例外</span>
              </p>
              <p>{{ activeAction ? '保持支撑' : '当前支撑' }}：{{ actionSupportText }}</p>
            </section>

            <section v-if="activeRun" class="run-evidence">
              <strong>{{ activeRun.failure_reason || solutionSummary(activeRun) }}</strong>
              <span>解法：{{ solutionLabel(activeRun.solution_mode) }} · {{ activeRun.movement_count }} 个动作 · {{ activeRun.alternatives_found }} 条候选</span>
              <span v-if="activeRun.failure_hold_id">卡点：{{ activeRun.failure_hold_id }}，动作 {{ activeRun.failure_step }}</span>
              <span v-if="!activeRun.search_complete">搜索预算已用尽，当前结果不能作为不可攀结论。</span>
              <div v-if="activeRun.solution_mode === 'single_dynamic'" class="dynamic-review-notice" role="status">
                <strong>动态可行，仍需真人复核</strong>
                <span>动态可行性分 {{ Math.round(activeRun.dynamic_feasibility_score) }}，这不是成功概率，也不会计入自动通过。</span>
              </div>
              <span v-if="activeFrame && Object.keys(activeFrame.contact_loads || {}).length">接触负荷：{{ contactLoadText(activeFrame.contact_loads) }}</span>
              <span v-if="usedHoldIds.length">使用点：{{ usedHoldIds.join('、') }}<template v-if="skippedHoldIds.length">；跳过中间点：{{ skippedHoldIds.join('、') }}</template></span>
              <div class="demand-list">
                <span v-for="(value, key) in activeRun.demand" :key="key">{{ demandLabel(key) }} {{ Math.round(value) }}</span>
              </div>
            </section>

            <div class="route-tag-list">
              <span v-for="tag in report.tags" :key="tag" class="route-tag">{{ tag }}</span>
            </div>

            <section v-if="report.repair_candidates?.length" class="simulation-candidates">
              <h3>修复副本</h3>
              <article v-for="candidate in report.repair_candidates" :key="candidate.id">
                <div><strong>{{ candidate.label }}</strong><span>{{ candidate.reason }}</span></div>
                <small>复用 {{ percent(candidate.reuse_rate) }} · {{ candidate.predicted_grade || '-' }}</small>
                <el-button type="primary" plain @click="$emit('load-candidate', candidate.board_asset)">载入定线工作台</el-button>
              </article>
            </section>

            <el-collapse class="simulation-feedback">
              <el-collapse-item title="提交真人终审反馈" name="feedback">
                <el-form label-position="top">
                  <div class="feedback-grid">
                    <el-form-item label="实际结果"><el-select v-model="feedback.outcome"><el-option label="Flash" value="flash" /><el-option label="完成" value="send" /><el-option label="尝试" value="attempt" /><el-option label="失败" value="fail" /></el-select></el-form-item>
                    <el-form-item label="体型"><el-select v-model="feedback.profile_id" clearable><el-option v-for="profile in profiles" :key="profile.id" :label="profile.label" :value="profile.id" /></el-select></el-form-item>
                    <el-form-item label="体感难度"><el-select v-model="feedback.perceived_grade" clearable><el-option v-for="grade in grades" :key="grade" :label="grade" :value="grade" /></el-select></el-form-item>
                    <el-form-item label="系统是否正确"><el-select v-model="feedback.system_correct" clearable><el-option label="正确" :value="true" /><el-option label="不正确" :value="false" /></el-select></el-form-item>
                  </div>
                  <el-input v-model="feedback.notes" type="textarea" :rows="2" placeholder="卡在哪个动作，或系统遗漏了什么" />
                  <el-button type="primary" plain :loading="feedbackSaving" @click="submitFeedback">保存终审反馈</el-button>
                </el-form>
              </el-collapse-item>
            </el-collapse>
          </template>
          <el-skeleton v-else-if="running" :rows="8" animated />
          <div v-else class="simulation-empty compact">
            <strong>尚未运行仿真</strong>
            <span>选择能力等级后运行，结果不会直接改变线路状态。</span>
          </div>
        </aside>
      </div>
    </template>

    <template v-else-if="mode === 'batch'">
      <div class="simulation-toolbar">
        <el-select v-model="batchDifficulty" clearable placeholder="全部难度"><el-option v-for="grade in grades" :key="grade" :label="grade" :value="grade" /></el-select>
        <el-select v-model="motionMode" class="motion-mode-select" aria-label="批量动作模式"><el-option v-for="option in motionModeOptions" :key="option.value" :label="option.label" :value="option.value" /></el-select>
        <el-input-number v-model="batchLimit" :min="1" :max="100" />
        <el-button type="primary" :loading="batchRunning" @click="runBatch">批量运行影子审核</el-button>
      </div>
      <dl v-if="batchResult" class="batch-summary">
        <div><dt>已完成</dt><dd>{{ batchResult.completed }} / {{ batchResult.total }}</dd></div>
        <div><dt>通过</dt><dd>{{ batchResult.counts?.pass || 0 }}</dd></div>
        <div><dt>体型偏置</dt><dd>{{ batchResult.counts?.pass_body_bias || 0 }}</dd></div>
        <div><dt>待复核</dt><dd>{{ batchResult.counts?.review || 0 }}</dd></div>
        <div><dt>不通过</dt><dd>{{ batchResult.counts?.fail || 0 }}</dd></div>
      </dl>
      <el-table :data="batchResult?.reports || []" empty-text="运行批量审核后在这里查看结果" @row-click="openBatchReport">
        <el-table-column prop="route.display_name" label="线路" min-width="210" />
        <el-table-column prop="ability_grade" label="标称能力" width="100" />
        <el-table-column prop="predicted_grade" label="等效难度" width="100" />
        <el-table-column label="解法" width="90"><template #default="scope">{{ reportSolutionLabel(scope.row) }}</template></el-table-column>
        <el-table-column label="结论" width="170"><template #default="scope"><span class="simulation-verdict table" :class="`is-${scope.row.verdict}`">{{ scope.row.verdict_label }}</span></template></el-table-column>
        <el-table-column label="体型" width="100"><template #default="scope">{{ scope.row.pass_count }}/{{ scope.row.profile_count }}</template></el-table-column>
        <el-table-column label="置信度" width="110"><template #default="scope">{{ percent(scope.row.confidence) }}</template></el-table-column>
        <el-table-column prop="summary" label="依据" min-width="300" />
      </el-table>
    </template>

    <template v-else>
      <div class="hold-calibration-note">
        <strong>岩点手感标定</strong>
        <span>默认值可运行仿真，但人工确认后报告会显示更高的数据可信度。</span>
      </div>
      <el-table :data="holdProfiles" empty-text="正在读取岩点参数">
        <el-table-column prop="variant_id" label="岩点款式" min-width="180" />
        <el-table-column prop="hold_type" label="类型" width="90" />
        <el-table-column label="手感" width="150"><template #default="scope"><el-input-number v-model="scope.row.quality" :min="1" :max="5" size="small" /></template></el-table-column>
        <el-table-column label="适用" width="130"><template #default="scope"><el-select v-model="scope.row.usable_by" size="small"><el-option label="手" value="hand" /><el-option label="脚" value="foot" /><el-option label="手脚" value="both" /></el-select></template></el-table-column>
        <el-table-column label="受力方向" width="150"><template #default="scope"><el-input-number v-model="scope.row.preferred_direction_degrees" :min="0" :max="359" size="small" /></template></el-table-column>
        <el-table-column label="可信度" width="160"><template #default="scope"><el-slider v-model="scope.row.confidence" :min="0" :max="1" :step="0.05" /></template></el-table-column>
        <el-table-column label="操作" width="100"><template #default="scope"><el-button type="primary" plain size="small" @click="saveHold(scope.row)">保存</el-button></template></el-table-column>
      </el-table>
    </template>
  </section>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import BoardCanvas from './BoardCanvas.vue'
import standardBoardService from '../services/standardBoardService'
import simulationService from '../services/simulationService'
import { DEFAULT_FONT_GRADE, FONT_GRADES } from '../constants/gradeSystem'

const props = defineProps({
  initialSourceId: { type: String, default: '' },
  resolveHoldVisual: { type: Function, default: null },
})
defineEmits(['load-candidate'])

const modeOptions = [{ label: '单线回放', value: 'single' }, { label: '批量队列', value: 'batch' }, { label: '岩点标定', value: 'holds' }]
const motionModeOptions = [{ label: '静态优先 + 单次动态', value: 'static_then_single_dynamic' }, { label: '仅静态', value: 'static' }]
const grades = FONT_GRADES
const columns = Array.from({ length: 11 }, (_, index) => String.fromCharCode(65 + index))
const rows = Array.from({ length: 18 }, (_, index) => index + 1)
const boardSpec = { columns: 11, rows: 18, board_width_mm: 2440, board_height_mm: 3660, margin_left_mm: 220, margin_right_mm: 220, margin_bottom_mm: 130, margin_top_mm: 130, hole_spacing_x_mm: 200, hole_spacing_y_mm: 200, angle_degrees: 40 }
const boardFrameStyle = { '--board-ratio': `${boardSpec.board_width_mm} / ${boardSpec.board_height_mm}`, '--grid-left': `${(boardSpec.margin_left_mm / boardSpec.board_width_mm) * 100}%`, '--grid-right': `${(boardSpec.margin_right_mm / boardSpec.board_width_mm) * 100}%`, '--grid-bottom': `${(boardSpec.margin_bottom_mm / boardSpec.board_height_mm) * 100}%`, '--grid-top': `${(boardSpec.margin_top_mm / boardSpec.board_height_mm) * 100}%` }

const mode = ref('single')
const routes = ref([])
const selectedSourceId = ref(props.initialSourceId || '')
const abilityGrade = ref(DEFAULT_FONT_GRADE)
const motionMode = ref('static_then_single_dynamic')
const routeDetail = ref(null)
const report = ref(null)
const profiles = ref([])
const holdProfiles = ref([])
const running = ref(false)
const batchRunning = ref(false)
const repairing = ref(false)
const feedbackSaving = ref(false)
const taskId = ref('')
const error = ref('')
const activeRunIndex = ref(0)
const frameIndex = ref(0)
const playing = ref(false)
const playbackSpeed = ref(1)
const playbackSpeeds = [0.25, 0.5, 1, 2]
const playbackTime = ref(0)
let playbackAnimationFrame = 0
let previousPlaybackTick = 0
const batchDifficulty = ref(DEFAULT_FONT_GRADE)
const batchLimit = ref(12)
const batchResult = ref(null)
const feedback = reactive({ outcome: 'attempt', profile_id: '', perceived_grade: '', system_correct: null, notes: '' })

const activeDetail = computed(() => report.value?.route || routeDetail.value)
const activeRun = computed(() => report.value?.runs?.[activeRunIndex.value] || null)
const playbackFrames = computed(() => activeRun.value?.frames || [])
const activeFrame = computed(() => {
  const frames = playbackFrames.value
  if (!frames.length) return null
  return frames[Math.max(0, Math.min(frameIndex.value, frames.length - 1))] || frames[0]
})
const activeAction = computed(() => activeRun.value?.actions?.find((action) => action.step === activeFrame.value?.step) || null)
const movingLimbKeys = computed(() => (activeAction.value?.moving_limbs || [])
  .map((limb) => String(limb).toLowerCase()))
const actionMovementText = computed(() => {
  if (!activeAction.value) return '四肢已建立起步支撑'
  const limb = movingLimbKeys.value[0] || String(activeFrame.value?.moving_limb || '').toLowerCase()
  const from = activeAction.value.from_contacts?.[limb] || '未接触'
  const to = activeAction.value.to_contacts?.[limb] || activeAction.value.target_hold_ids?.[0] || '未接触'
  return `${limbLabel(limb)}：${from} → ${to}`
})
const actionSupportText = computed(() => {
  const contacts = activeAction.value?.to_contacts || activeFrame.value?.contacts || {}
  return contactSummary(contacts, movingLimbKeys.value) || '无其他支撑'
})
const usedHoldIds = computed(() => {
  const ids = new Set()
  for (const holdId of Object.values(activeRun.value?.frames?.[0]?.contacts || {})) if (holdId) ids.add(holdId)
  for (const action of activeRun.value?.actions || []) for (const holdId of Object.values(action.to_contacts || {})) if (holdId) ids.add(holdId)
  return [...ids]
})
const skippedHoldIds = computed(() => (activeDetail.value?.roles?.mid || []).filter((holdId) => !usedHoldIds.value.includes(holdId)))

onMounted(async () => {
  await Promise.all([loadRoutes(), loadProfiles(), loadHoldProfiles()])
  if (selectedSourceId.value) await loadRoute(selectedSourceId.value)
})
onBeforeUnmount(stopPlayback)
watch(() => props.initialSourceId, async (value) => {
  if (!value || value === selectedSourceId.value) return
  selectedSourceId.value = value
  mode.value = 'single'
  await loadRoute(value)
})
watch(abilityGrade, loadProfiles)
watch(frameIndex, (value) => {
  if (!playing.value) playbackTime.value = Number(playbackFrames.value[value]?.timestamp_seconds || 0)
  if (playing.value && playbackFrames.value.length && value >= playbackFrames.value.length - 1) stopPlayback()
})

async function loadRoutes() {
  try {
    const response = await standardBoardService.listRoutes({ limit: 100, offset: 0, sort: 'score_desc' })
    routes.value = response.data?.routes || []
    if (!selectedSourceId.value && routes.value.length) selectedSourceId.value = routes.value[0].source_id
  } catch (err) { error.value = err.response?.data?.detail || err.message }
}
async function loadProfiles() {
  try { profiles.value = (await simulationService.listProfiles(abilityGrade.value)).data || [] } catch (err) { error.value = err.message }
}
async function loadHoldProfiles() {
  try { holdProfiles.value = (await simulationService.listHoldProfiles()).data || [] } catch (err) { error.value = err.message }
}
async function loadRoute(sourceId) {
  stopPlayback()
  report.value = null
  activeRunIndex.value = 0
  frameIndex.value = 0
  if (!sourceId) return
  try {
    routeDetail.value = (await standardBoardService.getRoute(sourceId)).data
    abilityGrade.value = routeDetail.value?.grade || DEFAULT_FONT_GRADE
    try { report.value = (await simulationService.latest(sourceId)).data } catch (err) { if (err.response?.status !== 404) throw err }
  } catch (err) { error.value = err.response?.data?.detail || err.message }
}
async function runSingle() {
  error.value = ''
  running.value = true
  report.value = null
  try {
    taskId.value = (await simulationService.startRoute(selectedSourceId.value, { ability_grade: abilityGrade.value, motion_mode: motionMode.value })).data?.task_id
    report.value = await waitForTask(taskId.value)
    activeRunIndex.value = 0
    frameIndex.value = 0
    ElMessage.success('三体型仿真审核已完成')
  } catch (err) { error.value = err.response?.data?.detail || err.message || '仿真失败' } finally { running.value = false }
}
async function runBatch() {
  error.value = ''
  batchRunning.value = true
  try {
    const id = (await simulationService.startBatch({ difficulty: batchDifficulty.value || null, limit: batchLimit.value, motion_mode: motionMode.value })).data?.task_id
    batchResult.value = await waitForTask(id)
    ElMessage.success(`已完成 ${batchResult.value.completed || 0} 条影子审核`)
  } catch (err) { error.value = err.response?.data?.detail || err.message || '批量审核失败' } finally { batchRunning.value = false }
}
async function waitForTask(id) {
  for (let attempt = 0; attempt < 120; attempt += 1) {
    const response = await simulationService.task(id)
    if (response.data?.status === 'completed') return response.data.result
    if (['failed', 'cancelled'].includes(response.data?.status)) throw new Error(response.data?.error || '任务未完成')
    await new Promise((resolve) => window.setTimeout(resolve, 600))
  }
  throw new Error('任务运行时间过长，请稍后重试')
}
async function cancelTask() {
  if (!taskId.value) return
  await simulationService.cancel(taskId.value)
  running.value = false
}
async function createRepairs() {
  if (!report.value?.report_id) return
  repairing.value = true
  try {
    report.value.repair_candidates = (await simulationService.repairCandidates(report.value.report_id)).data || []
    if (report.value.repair_candidates.length) ElMessage.success('已生成不覆盖原线的修复副本')
    else ElMessage.info('没有找到同时满足复用率、难度和多数体型通过的安全候选')
  } catch (err) { error.value = err.response?.data?.detail || err.message } finally { repairing.value = false }
}
async function submitFeedback() {
  if (!report.value?.report_id) return
  feedbackSaving.value = true
  try {
    await simulationService.feedback(report.value.report_id, { ...feedback, profile_id: feedback.profile_id || null, perceived_grade: feedback.perceived_grade || null })
    feedback.notes = ''
    ElMessage.success('真人终审反馈已保存在本机')
  } catch (err) { error.value = err.response?.data?.detail || err.message } finally { feedbackSaving.value = false }
}
async function saveHold(profile) {
  try {
    const saved = (await simulationService.saveHoldProfile({ ...profile, notes: '人工标定', confidence: Math.max(0.8, profile.confidence || 0) })).data
    Object.assign(profile, saved)
    ElMessage.success(`已保存 ${profile.variant_id} 的手感标定`)
  } catch (err) { error.value = err.response?.data?.detail || err.message }
}
function openBatchReport(row) {
  report.value = row
  routeDetail.value = row.route
  selectedSourceId.value = row.source_id
  mode.value = 'single'
  activeRunIndex.value = 0
  frameIndex.value = 0
}
function selectRun(index) { stopPlayback(); activeRunIndex.value = index; frameIndex.value = 0 }
function togglePlayback() {
  if (playing.value) { stopPlayback(); return }
  if (!playbackFrames.value.length) return
  if (frameIndex.value >= playbackFrames.value.length - 1) frameIndex.value = 0
  playbackTime.value = Number(playbackFrames.value[frameIndex.value]?.timestamp_seconds || 0)
  playing.value = true
  previousPlaybackTick = performance.now()
  playbackAnimationFrame = window.requestAnimationFrame(playbackTick)
}
function playbackTick(now) {
  if (!playing.value) return
  const frames = playbackFrames.value
  const finalTime = Number(frames.at(-1)?.timestamp_seconds || 0)
  playbackTime.value = Math.min(
    finalTime,
    playbackTime.value + ((now - previousPlaybackTick) / 1000) * playbackSpeed.value,
  )
  previousPlaybackTick = now
  let index = frameIndex.value
  while (index < frames.length - 1 && Number(frames[index + 1].timestamp_seconds || 0) <= playbackTime.value) index += 1
  frameIndex.value = index
  if (playbackTime.value >= finalTime) { stopPlayback(); return }
  playbackAnimationFrame = window.requestAnimationFrame(playbackTick)
}
function stopPlayback() {
  playing.value = false
  if (playbackAnimationFrame) window.cancelAnimationFrame(playbackAnimationFrame)
  playbackAnimationFrame = 0
  previousPlaybackTick = 0
}
function getCoordStyle(coord = 'A1') {
  const match = String(coord).match(/^([A-Z]+)(\d+)$/i) || []
  const xIndex = Math.max(0, columns.indexOf((match[1] || 'A').toUpperCase()))
  const yIndex = Math.max(0, rows.indexOf(Number(match[2] || 1)))
  const xMm = boardSpec.margin_left_mm + xIndex * boardSpec.hole_spacing_x_mm
  const yMm = boardSpec.margin_bottom_mm + yIndex * boardSpec.hole_spacing_y_mm
  return { left: `${(xMm / boardSpec.board_width_mm) * 100}%`, bottom: `${(yMm / boardSpec.board_height_mm) * 100}%` }
}
function resolveHoldVisual(hold) {
  const resolved = props.resolveHoldVisual?.(hold) || {}
  return {
    imageUrl: resolved.imageUrl || hold.imageUrl || '',
    svgPath: resolved.svgPath || hold.svgPath || '',
  }
}
function percent(value) { return `${Math.round(Number(value || 0) * 100)}%` }
function runStatus(status) { return { passed: '通过', failed: '未通过', review: '待复核' }[status] || status }
function solutionLabel(modeValue) { return { static: '静态', single_dynamic: '单次动态', none: '无解' }[modeValue] || '无解' }
function solutionSummary(run) { return run.solution_mode === 'single_dynamic' ? '找到单次动态可行证据' : '找到通过姿态与受力重放的静态 Beta' }
function reportSolutionLabel(row) {
  if (row.runs?.some((run) => run.solution_mode === 'single_dynamic')) return '动态'
  if (row.runs?.some((run) => run.solution_mode === 'static')) return '静态'
  return '无解'
}
function phaseLabel(phase) {
  return {
    rest: '静止',
    weight_shift: '换重心',
    crouch: '屈腿准备',
    release: '释放',
    reach: '伸手 / 提膝',
    place: '放脚',
    push: '蹬伸',
    flight: '飞行',
    catch: '抓取',
    settle: '稳定',
    recovery: '恢复脚撑',
  }[phase] || phase
}
function limbLabel(limb) { return { LH: '左手', RH: '右手', LF: '左脚', RF: '右脚', lh: '左手', rh: '右手', lf: '左脚', rf: '右脚' }[limb] || limb }
function limbList(limbs) { return limbs.map(limbLabel).join('、') }
function contactSummary(contacts, excluded = []) {
  const skipped = new Set(excluded.map((limb) => String(limb).toLowerCase()))
  return Object.entries(contacts || {})
    .filter(([limb, holdId]) => holdId && !skipped.has(String(limb).toLowerCase()))
    .map(([limb, holdId]) => `${limbLabel(limb)} ${holdId}`)
    .join('、')
}
function isTechniqueException(technique) { return ['backstep', 'drop_knee', 'rock_over'].includes(technique) }
function contactLoadText(loads) { return Object.entries(loads).map(([limb, value]) => `${limbLabel(limb)} ${percent(value)}`).join(' · ') }
function techniqueLabel(value) {
  return {
    direct_reach: '直接伸手',
    weight_shift_reach: '换重心伸手',
    leg_drive_reach: '蹬腿伸手',
    hand_match: '双手匹配',
    foot_match: '双脚匹配',
    step_up: '提脚',
    high_step: '高脚',
    backstep: '外侧步',
    drop_knee: '沉膝',
    rock_over: '重心越脚',
    dynamic_leg_drive: '动态蹬伸',
    cut_loose_recovery: '脱脚摆荡恢复',
  }[value] || value || '基础动作'
}
function demandLabel(key) { return { reach: '触达', finger_strength: '指力', core_tension: '核心', mobility: '活动度', endurance: '耐力', explosiveness: '爆发' }[key] || key }
</script>
