<template>
  <AppShell
    :active="activePage"
    :workspace="workspace"
    @update:active="changePage"
    :title="pageTitle"
    :board-label="activePage === 'photo-routes' ? '个人照片线路' : studio.currentBoardSpec.label"
    :hold-count="activePage === 'photo-routes' ? photoStatus.count : studio.placedHolds.length"
    :dirty="activePage === 'photo-routes' ? photoStatus.dirty : studio.unsavedChanges"
    :save-label="activePage === 'photo-routes' ? photoStatus.state : ''"
    :simulation-enabled="simulationEnabled"
    :photo-section="photoSection"
    @close-settings="closeSettings"
    @change-workspace="requestWorkspaceChange"
  >
    <div v-if="workspace === 'boulder' && (photoWork.state.uploading || (photoWork.state.session && !['saved','abandoned'].includes(photoWork.state.session.status)))" class="photo-task-notice" role="status">
      <span>{{ photoWork.state.uploading ? '照片正在上传，可以继续使用其他功能' : photoWork.state.session.status === 'ready' ? (photoWork.state.session.viewed ? '当前线路进度已保存' : '线路已提取，进度已保存') : photoWork.state.session.stage }}</span>
      <button type="button" @click="returnPhotoWork">{{ photoWork.state.session?.status === 'ready' ? '返回查看' : '查看当前线路' }}</button>
      <span v-if="photoWork.state.connectionLost">暂时断开，正在重新连接</span>
    </div>
    <SettingsPage v-if="activePage === 'settings'" />
    <DashboardPage
      v-else-if="activePage === 'dashboard'"
      v-model:selected-template-id="selectedDashboardTemplateId"
      :studio="studio"
      :boards="boards"
      :library="library"
      :simulation-enabled="simulationEnabled"
      :workflow-label="workflowLabel"
      @navigate="changePage"
      @new-board="startBlankStudio"
      @create-from-template="createFromTemplate"
      @load-board="loadBoardIntoStudio"
    />

    <PhotoRouteWorkflowPage
      v-else-if="activePage === 'photo-routes'"
      ref="photoPage"
      @section-change="photoSection = $event"
    />

    <StudioPage
      v-else-if="activePage === 'studio'"
      :studio="studio"
      :boards="boards"
      :library="library"
      @new-board="startBlankStudio"
      @save-board="saveCurrentBoard"
      @select-hold="selectPlacedHold"
    />

    <HoldLibraryPage v-else-if="activePage === 'library'" :library="library" />

    <BoardsPage
      v-else-if="activePage === 'boards'"
      v-model:board-asset-mode="boardAssetMode"
      v-model:saved-board-view="savedBoardView"
      v-model:compare-board-ids="compareBoardIds"
      :boards="boards"
      :library="library"
      :saved-board-filters="savedBoardFilters"
      :saved-board-tag-groups="savedBoardTagGroups"
      :visible-saved-boards="visibleSavedBoards"
      :filtered-saved-boards="filteredSavedBoards"
      :compared-boards="comparedBoards"
      :board-spec-display-label="boardSpecDisplayLabel"
      :workflow-label="workflowLabel"
      :resolved-board-tags="resolvedBoardTags"
      :tag-label="tagLabel"
      @new-board="startBlankStudio"
      @clear-tags="clearSavedBoardTags"
      @load-board="loadBoardIntoStudio"
      @rename-board="renameBoard"
      @archive-board="archiveBoard"
      @restore-board="restoreBoard"
      @clear-comparison="clearBoardComparison"
      @set-baseline="setComparisonBaseline"
      @remove-compared="removeComparedBoard"
    />

    <StandardBoardPage
      v-else-if="activePage === 'standard-board'"
      :standard-board="standardBoard"
      :standard-route-tag-groups="standardRouteTagGroups"
      :standard-board-spec="standardBoardSpec"
      :standard-board-frame-style="standardBoardFrameStyle"
      :library="library"
      :simulation-enabled="simulationEnabled"
      :all-visible-repaired-selected="allVisibleRepairedSelected"
      :some-visible-repaired-selected="someVisibleRepairedSelected"
      :fetch-standard-routes="fetchStandardRoutes"
      :generate-standard-route="generateStandardRoute"
      :handle-standard-mode-change="handleStandardModeChange"
      :apply-standard-filters="applyStandardFilters"
      :change-standard-page="changeStandardPage"
      :load-standard-route="loadStandardRoute"
      :load-standard-into-studio="loadStandardIntoStudio"
      :open-selected-route-simulation="openSelectedRouteSimulation"
      :toggle-standard-favorite="toggleStandardFavorite"
      :rate-standard-route="rateStandardRoute"
      :submit-standard-ascent-log="submitStandardAscentLog"
      :fetch-repair-routes="fetchRepairRoutes"
      :apply-repair-filters="applyRepairFilters"
      :change-repair-page="changeRepairPage"
      :load-repair-route="loadRepairRoute"
      :preview-repair-route="previewRepairRoute"
      :load-repair-into-studio="loadRepairIntoStudio"
      :toggle-visible-repair-selection="toggleVisibleRepairSelection"
      :publish-selected-repairs="publishSelectedRepairs"
      :is-repair-selected="isRepairSelected"
      :toggle-repair-selection="toggleRepairSelection"
      :get-standard-board-coord-style="getStandardBoardCoordStyle"
      :tier-label="tierLabel"
      :marker-label="markerLabel"
      :result-label="resultLabel"
      :repair-status-label="repairStatusLabel"
      :grade-warning-label="gradeWarningLabel"
      :percent-label="percentLabel"
      :score-breakdown-items="scoreBreakdownItems"
      :difficulty-breakdown-items="difficultyBreakdownItems"
      :tag-label="tagLabel"
      :calibration-label="calibrationLabel"
      :confidence-label="confidenceLabel"
    />
    <SimulationLab
      v-else-if="simulationEnabled && activePage === 'simulation'"
      :initial-source-id="simulationSourceId"
      :resolve-hold-visual="library.resolveHoldVisual"
      @load-candidate="loadSimulationCandidate"
    />

    <AILabPage
      v-else
      :boards="boards"
      :library="library"
      :route-gen="routeGen"
      :ai-experiment="aiExperiment"
      :ai-available-boards="aiAvailableBoards"
      :selected-ai-board="selectedAiBoard"
      :selected-ai-board-stats="selectedAiBoardStats"
      :ai-board-warnings="aiBoardWarnings"
      :ai-board-blocking-message="aiBoardBlockingMessage"
      :can-run-ai-experiment="canRunAiExperiment"
      :ai-comparison-reference="aiComparisonReference"
      :review-repair-candidate="reviewRepairCandidate"
      :board-spec-display-label="boardSpecDisplayLabel"
      :workflow-label="workflowLabel"
      :suggestion-group-label="suggestionGroupLabel"
      :risk-assessment-label="riskAssessmentLabel"
      :risk-metric-label="riskMetricLabel"
      :risk-level-label="riskLevelLabel"
      :review-scope-label="reviewScopeLabel"
      :evidence-status-label="evidenceStatusLabel"
      :confidence-label="confidenceLabel"
      :ai-task-status-label="aiTaskStatusLabel"
      :candidate-meta="candidateMeta"
      @navigate="changePage"
      @load-selected-board="loadSelectedAiBoardIntoStudio"
      @select-board="selectAiBoard"
      @run-experiment="runAiExperiment"
      @load-candidate="loadAiCandidateIntoStudio"
    />
  </AppShell>
</template>

<script setup>
import { computed, inject, provide, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import AppShell from './components/AppShell.vue'
import SettingsPage from './components/SettingsPage.vue'
import DashboardPage from './components/DashboardPage.vue'
import StudioPage from './components/StudioPage.vue'
import AILabPage from './components/AILabPage.vue'
import BoardsPage from './components/BoardsPage.vue'
import HoldLibraryPage from './components/HoldLibraryPage.vue'
import PhotoRouteWorkflowPage from './components/PhotoRouteWorkflowPage.vue'
import { createPhotoWorkflow } from './composables/usePhotoWorkflow'
import SimulationLab from './components/SimulationLab.vue'
import StandardBoardPage from './components/StandardBoardPage.vue'
import { useBoardPersistence } from './composables/useBoardPersistence'
import { useHoldLibrary } from './composables/useHoldLibrary'
import { useRouteGeneration } from './composables/useRouteGeneration'
import { useStudioEditor } from './composables/useStudioEditor'
import { appPageFromHash, parsePhotoWorkflowHash } from './utils/photoWorkflowRoute.js'
import { DEFAULT_FONT_GRADE, FONT_GRADES, UNGRADED, calibrationLabel, confidenceLabel } from './constants/gradeSystem'
import { ROUTE_TAG_GROUPS, boardSystemTags, boardTags, matchesTags, tagLabel } from './constants/routeTags'
import standardBoardService from './services/standardBoardService'

const props = defineProps({ workspace: { type: String, required: true } })
const emit = defineEmits(['change-workspace'])
const appPages = ['dashboard','studio','photo-routes','library','boards','standard-board','simulation','ai-lab','settings']
const workspacePages = {
  boulder: ['photo-routes', 'settings'],
  setter: ['dashboard', 'studio', 'library', 'boards', 'standard-board', 'simulation', 'ai-lab', 'settings'],
}
const workspaceHome = props.workspace === 'boulder' ? 'photo-routes' : 'dashboard'
const requestedPage = appPageFromHash(location.hash, appPages, workspaceHome)
const activePage = ref(workspacePages[props.workspace].includes(requestedPage) ? requestedPage : workspaceHome)
const settingsReturnPage = ref(activePage.value === 'settings' ? workspaceHome : activePage.value)
const photoAccess = inject('pilotAccess')
const photoWork = createPhotoWorkflow(photoAccess.session.username || 'local')
provide('photoWorkflow', photoWork)
async function returnPhotoWork() {
  await changePage('photo-routes')
  if(activePage.value==='photo-routes') {
    await photoPage.value?.returnCurrent()
    if(photoWork.state.session?.status==='ready') await photoWork.change('viewed').catch(()=>{})
  }
}
function appHashChanged() {
  photoSection.value = ['library', 'route'].includes(parsePhotoWorkflowHash(location.hash).screen) ? 'library' : 'routes'
  const requested = appPageFromHash(location.hash, appPages, workspaceHome)
  const nextPage = workspacePages[props.workspace].includes(requested) ? requested : workspaceHome
  if (requested !== nextPage) history.replaceState(null, '', `#/${nextPage}`)
  changePage(nextPage, { fromHistory:true, replace:true })
}
onMounted(() => {
  photoWork.init()
  if (appPageFromHash(location.hash, appPages, workspaceHome) !== activePage.value) history.replaceState(null, '', `#/${activePage.value}`)
  window.addEventListener('hashchange', appHashChanged)
})
onBeforeUnmount(() => { photoWork.close(); window.removeEventListener('hashchange', appHashChanged) })
const simulationEnabled = import.meta.env.VITE_ENABLE_SIMULATION === 'true'
const library = reactive(useHoldLibrary())
const boards = reactive(useBoardPersistence())
const studio = reactive(useStudioEditor())
const photoPage = ref(null)
const photoSection = ref(['library', 'route'].includes(parsePhotoWorkflowHash(location.hash).screen) ? 'library' : 'routes')
const photoStatus = computed(() => ({count:photoWork.state.session?.route?.members.length || 0,dirty:!!photoWork.state.pendingChange,state:photoWork.state.saving?'保存中…':photoWork.state.session?.stage || '已同步'}))
const routeGen = reactive(useRouteGeneration())
const selectedDashboardTemplateId = ref(studio.activeBoardPresetId)
const aiExperiment = reactive({
  mode: 'compose_route',
  generation_goal: 'quality_first',
  review_focus: 'overall',
  selectedBoardId: '',
})
const simulationSourceId = ref('')
const boardAssetMode = ref('list')
const savedBoardView = ref('active')
const compareBoardIds = ref([])
const savedBoardFilters = reactive({ tagIds: [], match: 'all' })
const standardBoardColumns = Array.from({ length: 11 }, (_, index) => String.fromCharCode(65 + index))
const standardBoardRows = Array.from({ length: 18 }, (_, index) => index + 1)
const standardBoardSpec = {
  preset_id: 'classic-11x18',
  template_key: 'spray-small',
  label: '11×18 标准训练板',
  name: '11×18 标准训练板',
  columns: 11,
  cols: 11,
  rows: 18,
  hole_spacing_x_mm: 200,
  hole_spacing_y_mm: 200,
  board_width_mm: 2440,
  board_height_mm: 3660,
  grid_width_mm: 2000,
  grid_height_mm: 3400,
  margin_left_mm: 220,
  margin_right_mm: 220,
  margin_bottom_mm: 130,
  margin_top_mm: 130,
  angle_degrees: 40,
  total_holes: 198,
  unit: 'mm',
  reference_system: 'standard-board-derived',
  cellLabel: '11 x 18',
  physicalLabel: '2440 x 3660 mm',
  spacingLabel: '200 x 200 mm',
  angleLabel: '40°',
  material: null,
  skinClass: null,
}
const standardBoard = reactive({
  mode: 'routes',
  loading: false,
  generating: false,
  activityLoading: false,
  repairLoading: false,
  repairPublishing: false,
  error: '',
  routes: [],
  repairs: [],
  selected: null,
  selectedRepair: null,
  repairPreview: null,
  repairComparison: null,
  selectedRepairIds: [],
  activity: null,
  generatedMeta: null,
  total: 0,
  repairTotal: 0,
  difficulties: FONT_GRADES,
  filters: {
    q: '',
    difficulty: DEFAULT_FONT_GRADE,
    predicted_grade: '',
    grade_warning: '',
    benchmark_only: false,
    tag_ids: [],
    tag_match: 'all',
    sort: 'score_desc',
    limit: 24,
    offset: 0,
  },
  repairFilters: {
    q: '',
    status: '',
    limit: 24,
    offset: 0,
  },
  activityForm: {
    result: 'attempt',
    attempts: 1,
    perceived_grade: '',
    notes: '',
  },
})

const pageTitle = computed(() => ({
  settings: '设置',
  dashboard: '总览',
  studio: '定线工作台',
  'photo-routes': '抱石线路',
  library: '岩点库',
  boards: '岩板资产',
  'standard-board': '标准板库',
  simulation: '仿真审核',
  'ai-lab': 'AI 实验室',
}[activePage.value] || '攀岩定线辅助系统'))

const aiAvailableBoards = computed(() => boards.savedBoards.filter((board) => {
  const columns = Number(board.board_spec?.columns || board.board_spec?.cols || 11)
  const rows = Number(board.board_spec?.rows || 18)
  if (columns !== 11 || rows !== 18) return false
  return aiExperiment.mode === 'review_route' || board.ai_eligible
}))

const selectedAiBoard = computed(() => {
  if (!aiAvailableBoards.value.length) return null
  return aiAvailableBoards.value.find((board) => board.saved_id === aiExperiment.selectedBoardId) || aiAvailableBoards.value[0]
})

const selectedAiBoardStats = computed(() => {
  const board = selectedAiBoard.value
  return {
    holds: board?.placed_holds?.length || 0,
    beta: board?.beta_sequence?.length || 0,
    difficulty: board?.difficulty || UNGRADED,
    spec: boardSpecDisplayLabel(board),
  }
})

const aiBoardWarnings = computed(() => {
  const board = selectedAiBoard.value
  if (!board) return ['请先从岩板资产中选择一块岩板。']

  return board.readiness_warnings || []
})

const aiBoardBlockingMessage = computed(() => {
  const board = selectedAiBoard.value
  if (!board) return '请先选择一块已保存的岩板。'

  const holds = board.placed_holds || []
  if (!holds.length) return '所选岩板没有岩点，无法提交。'
  const columns = Number(board.board_spec?.columns || board.board_spec?.cols || 11)
  const rows = Number(board.board_spec?.rows || 18)
  const angle = Number(board.board_spec?.angle_degrees || 40)
  if (columns !== 11 || rows !== 18 || angle !== 40) return 'AI 实验目前只支持 11×18、40° 岩板，其他规格可以继续手工编辑。'
  if (aiExperiment.mode === 'compose_route' && !board.ai_eligible) {
    return board.readiness_issues?.[0] || 'AI 组合只接受通过完整性检查的线路。'
  }
  return ''
})

const canRunAiExperiment = computed(() => !routeGen.loading && !aiBoardBlockingMessage.value)

const visibleRepairedIds = computed(() => standardBoard.repairs
  .filter((repair) => repair.repair_status === 'repaired')
  .map((repair) => repair.source_id))

const allVisibleRepairedSelected = computed(() => (
  visibleRepairedIds.value.length > 0
  && visibleRepairedIds.value.every((sourceId) => standardBoard.selectedRepairIds.includes(sourceId))
))

const standardRouteTagGroups = computed(() => ROUTE_TAG_GROUPS.filter((group) => group.key !== 'source'))
const savedBoardTagGroups = computed(() => {
  const known = ROUTE_TAG_GROUPS.map((group) => ({ ...group, tags: [...group.tags] }))
  const knownIds = new Set(known.flatMap((group) => group.tags.map((tag) => tag.id)))
  const legacyTags = [...new Set(boards.savedBoards.flatMap((board) => board.tags || []))]
    .filter((tag) => !knownIds.has(tag))
    .map((id) => ({ id, label: tagLabel(id) }))
  if (legacyTags.length) known.push({ key: 'legacy', label: '已有标签', tags: legacyTags })
  return known
})
const visibleSavedBoards = computed(() => savedBoardView.value === 'archived' ? boards.archivedBoards : boards.savedBoards)
const filteredSavedBoards = computed(() => visibleSavedBoards.value.filter((board) => (
  matchesTags(boardTags(board), savedBoardFilters.tagIds, savedBoardFilters.match)
)))
const comparedBoards = computed(() => compareBoardIds.value
  .map((savedId) => boards.savedBoards.find((board) => board.saved_id === savedId))
  .filter(Boolean))
const aiComparisonReference = computed(() => routeGen.result?.board || selectedAiBoard.value)
const reviewRepairCandidate = computed(() => (
  routeGen.result?.suggestions?.find((suggestion) => suggestion.candidate_route)?.candidate_route || null
))

const someVisibleRepairedSelected = computed(() => (
  visibleRepairedIds.value.some((sourceId) => standardBoard.selectedRepairIds.includes(sourceId))
  && !allVisibleRepairedSelected.value
))

const standardBoardFrameStyle = computed(() => ({
  '--board-ratio': `${standardBoardSpec.board_width_mm} / ${standardBoardSpec.board_height_mm}`,
  '--board-columns': standardBoardSpec.columns,
  '--board-rows': standardBoardSpec.rows,
  '--grid-left': `${(standardBoardSpec.margin_left_mm / standardBoardSpec.board_width_mm) * 100}%`,
  '--grid-right': `${(standardBoardSpec.margin_right_mm / standardBoardSpec.board_width_mm) * 100}%`,
  '--grid-bottom': `${(standardBoardSpec.margin_bottom_mm / standardBoardSpec.board_height_mm) * 100}%`,
  '--grid-top': `${(standardBoardSpec.margin_top_mm / standardBoardSpec.board_height_mm) * 100}%`,
}))

function warnBeforeUnload(event) {
  if (!studio.unsavedChanges) return
  event.preventDefault()
  event.returnValue = ''
}

onMounted(async () => {
  window.addEventListener('beforeunload', warnBeforeUnload)
  await Promise.all([library.fetchAllHoldData(), boards.fetchMyBoards(), fetchStandardRoutes()])
  if (!studio.currentBoard.saved_id && !studio.placedHolds.length && boards.savedBoards[0]) {
    studio.loadBoard(boards.savedBoards[0])
  }
})

onBeforeUnmount(() => {
  window.removeEventListener('beforeunload', warnBeforeUnload)
})

watch(
  [() => boards.savedBoards, () => aiExperiment.mode],
  () => {
    const availableBoards = aiAvailableBoards.value
    if (!availableBoards.length) {
      aiExperiment.selectedBoardId = ''
      return
    }
    if (!availableBoards.some((board) => board.saved_id === aiExperiment.selectedBoardId)) {
      aiExperiment.selectedBoardId = availableBoards[0].saved_id || ''
    }
  },
  { immediate: true }
)

watch(
  () => boards.savedBoards,
  (activeBoards) => {
    const activeIds = new Set(activeBoards.map((board) => board.saved_id))
    compareBoardIds.value = compareBoardIds.value.filter((savedId) => activeIds.has(savedId)).slice(0, 4)
  },
  { deep: true }
)

watch(activePage, () => {
  window.requestAnimationFrame(() => window.scrollTo({ top: 0, left: 0, behavior: 'auto' }))
})

async function changePage(nextPage, { fromHistory=false, replace=false } = {}) {
  if (props.workspace === 'boulder' && nextPage === 'photo-library') {
    await photoPage.value?.openLibrary()
    return
  }
  if (props.workspace === 'boulder' && nextPage === 'photo-routes' && activePage.value === 'photo-routes') {
    await photoPage.value?.openCurrent()
    return
  }
  if (!workspacePages[props.workspace].includes(nextPage)) nextPage = workspaceHome
  if (nextPage === 'simulation' && !simulationEnabled) return
  if (nextPage === activePage.value) return
  if (activePage.value === 'photo-routes' && !(await photoPage.value?.beforeLeave())) return
  if (activePage.value === 'studio' && studio.unsavedChanges) {
    try {
      await ElMessageBox.confirm('当前修改仍会保留在本次工作区，但尚未写入本地岩板库。是否切换页面？', '未保存的草稿', {
        confirmButtonText: '离开并保留草稿',
        cancelButtonText: '继续编辑',
        type: 'warning',
      })
    } catch {
      return
    }
  }
  if (nextPage === 'settings' && activePage.value !== 'settings') settingsReturnPage.value = activePage.value
  activePage.value = nextPage
  if (!fromHistory) history[replace ? 'replaceState' : 'pushState'](null, '', nextPage === 'photo-routes' ? '#/photo-routes' : '#/' + nextPage)
}

function closeSettings() {
  changePage(settingsReturnPage.value || workspaceHome, { replace: true })
}

async function requestWorkspaceChange() {
  if (activePage.value === 'photo-routes' && !(await photoPage.value?.beforeLeave())) return
  if (activePage.value === 'studio' && studio.unsavedChanges) {
    try {
      await ElMessageBox.confirm('当前定线草稿尚未保存。切换项目后，本次未保存修改将不会写入岩板库。', '切换项目？', {
        confirmButtonText: '切换项目', cancelButtonText: '继续编辑', type: 'warning',
      })
    } catch { return }
  }
  emit('change-workspace')
}

function startBlankStudio() {
  studio.newBlankBoard().then((created) => {
    if (created) activePage.value = 'studio'
  })
}

function createFromTemplate(templateId) {
  studio.newBlankBoard(templateId).then((created) => {
    if (created) activePage.value = 'studio'
  })
}

function selectPlacedHold(hold) {
  studio.selectedHold = hold
  studio.betaForm.hold_id = hold.id
}

async function saveCurrentBoard() {
  const boardToSave = {
    ...studio.currentBoard,
    tags: [...new Set([...(studio.currentBoard.tags || []), ...boardSystemTags(studio.currentBoard)])],
  }
  const saved = await boards.saveBoard(boardToSave)
  if (!saved) return
  studio.loadBoard({ ...boardToSave, ...saved })
  if (saved.workflow_status === 'draft') {
    ElMessage.warning(`已保存为草稿：${saved.readiness_issues?.[0] || '线路尚未通过完整性检查'}`)
  } else {
    ElMessage.success(saved.ai_eligible ? '线路已保存，可进入 AI 实验' : '线路已保存，可进行人工检查')
  }
}

function resolvedBoardTags(board) {
  return boardTags(board)
}

function boardSpecDisplayLabel(board = {}) {
  const currentBoard = board || {}
  const columns = Number(currentBoard.board_spec?.columns || currentBoard.board_spec?.cols || 11)
  const rows = Number(currentBoard.board_spec?.rows || 18)
  return {
    '11x18': '11×18 标准训练板',
    '14x20': '14×20 扩展训练板',
    '16x24': '16×24 大型训练板',
    '18x22': '18×22 宽体训练板',
  }[`${columns}x${rows}`] || `${columns}×${rows} 岩板`
}

function clearSavedBoardTags() {
  savedBoardFilters.tagIds = []
}

function clearBoardComparison() {
  compareBoardIds.value = []
}

function setComparisonBaseline(savedId) {
  compareBoardIds.value = [savedId, ...compareBoardIds.value.filter((id) => id !== savedId)]
}

function removeComparedBoard(savedId) {
  compareBoardIds.value = compareBoardIds.value.filter((id) => id !== savedId)
}

function loadBoardIntoStudio(board) {
  studio.loadBoard(board)
  activePage.value = 'studio'
}

function loadAiCandidateIntoStudio(route) {
  studio.loadBoard(route, { markUnsaved: true })
  activePage.value = 'studio'
  ElMessage.info('候选路线已载入定线工作台；保存后才会写入本地岩板库。')
}

async function renameBoard(board) {
  const renamed = await boards.renameSavedBoard(board)
  if (renamed && studio.currentBoard.saved_id === renamed.saved_id) studio.loadBoard(renamed)
}

async function archiveBoard(board) {
  const archived = await boards.archiveSavedBoard(board)
  if (archived && studio.currentBoard.saved_id === board.saved_id) await studio.newBlankBoard()
}

async function restoreBoard(board) {
  await boards.restoreSavedBoard(board)
}

function workflowLabel(board = {}) {
  if (board.archived_at) return '已归档'
  return board.workflow_status === 'ready_for_review' ? '可检查' : '草稿'
}

async function fetchStandardRoutes() {
  standardBoard.loading = true
  standardBoard.error = ''
  try {
    const response = await standardBoardService.listRoutes(standardBoard.filters)
    standardBoard.routes = response.data?.routes || []
    standardBoard.total = response.data?.total || 0
    const selectedStillVisible = standardBoard.routes.some((route) => route.source_id === standardBoard.selected?.source_id)
    if ((!standardBoard.selected || !selectedStillVisible) && standardBoard.routes.length) {
      await loadStandardRoute(standardBoard.routes[0].source_id)
    }
  } catch (error) {
    standardBoard.error = error.response?.data?.detail || error.message || '标准板线路加载失败'
  } finally {
    standardBoard.loading = false
  }
}

function applyStandardFilters() {
  standardBoard.filters.offset = 0
  fetchStandardRoutes()
}

function changeStandardPage(page) {
  standardBoard.filters.offset = (page - 1) * standardBoard.filters.limit
  fetchStandardRoutes()
}

async function loadStandardRoute(sourceId) {
  standardBoard.error = ''
  try {
    const response = await standardBoardService.getRoute(sourceId)
    standardBoard.selected = response.data
    await fetchStandardActivity(sourceId)
  } catch (error) {
    standardBoard.error = error.response?.data?.detail || error.message || '标准板线路详情加载失败'
  }
}

async function fetchStandardActivity(sourceId = standardBoard.selected?.source_id) {
  if (!sourceId) return
  standardBoard.activityLoading = true
  try {
    const response = await standardBoardService.getActivity(sourceId)
    standardBoard.activity = response.data
  } catch (error) {
    standardBoard.activity = {
      favorite: false,
      rating: null,
      logs: [],
      stats: { attempts_total: 0, sends_total: 0, flashes_total: 0, last_result: null },
    }
    standardBoard.error = error.response?.data?.detail || '训练记录暂时不可用'
  } finally {
    standardBoard.activityLoading = false
  }
}

async function toggleStandardFavorite() {
  if (!standardBoard.selected?.source_id) return
  standardBoard.activityLoading = true
  try {
    const response = standardBoard.activity?.favorite
      ? await standardBoardService.unfavoriteRoute(standardBoard.selected.source_id)
      : await standardBoardService.favoriteRoute(standardBoard.selected.source_id)
    standardBoard.activity = response.data
  } catch (error) {
    standardBoard.error = error.response?.data?.detail || error.message || '收藏状态更新失败'
  } finally {
    standardBoard.activityLoading = false
  }
}

async function rateStandardRoute(rating) {
  if (!standardBoard.selected?.source_id || !rating) return
  standardBoard.activityLoading = true
  try {
    const response = await standardBoardService.rateRoute(standardBoard.selected.source_id, rating)
    standardBoard.activity = response.data
  } catch (error) {
    standardBoard.error = error.response?.data?.detail || error.message || '评分保存失败'
  } finally {
    standardBoard.activityLoading = false
  }
}

async function submitStandardAscentLog() {
  if (!standardBoard.selected?.source_id) return
  standardBoard.activityLoading = true
  try {
    const response = await standardBoardService.logAscent(standardBoard.selected.source_id, {
      result: standardBoard.activityForm.result,
      attempts: standardBoard.activityForm.attempts,
      perceived_grade: standardBoard.activityForm.perceived_grade || null,
      notes: standardBoard.activityForm.notes,
    })
    standardBoard.activity = response.data
    standardBoard.activityForm.notes = ''
    standardBoard.activityForm.attempts = 1
    ElMessage.success('训练记录已保存')
  } catch (error) {
    standardBoard.error = error.response?.data?.detail || error.message || '训练记录保存失败'
  } finally {
    standardBoard.activityLoading = false
  }
}

async function fetchRepairRoutes() {
  standardBoard.repairLoading = true
  standardBoard.error = ''
  try {
    const response = await standardBoardService.listRepairs(standardBoard.repairFilters)
    standardBoard.repairs = response.data?.routes || []
    standardBoard.repairTotal = response.data?.total || 0
    const currentIds = new Set(standardBoard.repairs.map((repair) => repair.source_id))
    standardBoard.selectedRepairIds = standardBoard.selectedRepairIds.filter((sourceId) => currentIds.has(sourceId))
    if ((!standardBoard.selectedRepair || !standardBoard.repairs.some((repair) => repair.source_id === standardBoard.selectedRepair?.source_id)) && standardBoard.repairs.length) {
      await loadRepairRoute(standardBoard.repairs[0].source_id)
    }
  } catch (error) {
    standardBoard.error = error.response?.data?.detail || error.message || '待修复路线加载失败'
  } finally {
    standardBoard.repairLoading = false
  }
}

function applyRepairFilters() {
  standardBoard.repairFilters.offset = 0
  fetchRepairRoutes()
}

function changeRepairPage(page) {
  standardBoard.repairFilters.offset = (page - 1) * standardBoard.repairFilters.limit
  fetchRepairRoutes()
}

async function loadRepairRoute(sourceId) {
  standardBoard.error = ''
  try {
    const response = await standardBoardService.compareRepair(sourceId)
    standardBoard.repairComparison = response.data
    standardBoard.selectedRepair = response.data?.candidate || null
    standardBoard.repairPreview = response.data?.repaired || null
  } catch (error) {
    standardBoard.error = error.response?.data?.detail || error.message || '修复候选加载失败'
  }
}

async function previewRepairRoute(sourceId) {
  standardBoard.error = ''
  try {
    const response = await standardBoardService.compareRepair(sourceId)
    standardBoard.repairComparison = response.data
    standardBoard.selectedRepair = response.data?.candidate || standardBoard.selectedRepair
    standardBoard.repairPreview = response.data?.repaired || null
  } catch (error) {
    standardBoard.error = error.response?.data?.detail || error.message || '修复预览加载失败'
  }
}

function loadRepairIntoStudio() {
  const boardAsset = standardBoard.repairComparison?.repaired?.board_asset || standardBoard.repairPreview?.board_asset
  if (!boardAsset) return
  studio.loadBoard(boardAsset, { markUnsaved: true })
  activePage.value = 'studio'
  ElMessage.info('修复副本已载入定线工作台；保存后才会写入本地岩板库。')
}

function isRepairSelected(sourceId) {
  return standardBoard.selectedRepairIds.includes(sourceId)
}

function toggleRepairSelection(sourceId, selected) {
  if (selected) {
    if (!standardBoard.selectedRepairIds.includes(sourceId)) {
      standardBoard.selectedRepairIds.push(sourceId)
    }
    return
  }
  standardBoard.selectedRepairIds = standardBoard.selectedRepairIds.filter((item) => item !== sourceId)
}

function toggleVisibleRepairSelection(selected) {
  if (!selected) {
    standardBoard.selectedRepairIds = standardBoard.selectedRepairIds.filter((sourceId) => !visibleRepairedIds.value.includes(sourceId))
    return
  }
  const selectedSet = new Set(standardBoard.selectedRepairIds)
  visibleRepairedIds.value.forEach((sourceId) => selectedSet.add(sourceId))
  standardBoard.selectedRepairIds = Array.from(selectedSet)
}

async function publishSelectedRepairs() {
  if (!standardBoard.selectedRepairIds.length) return
  standardBoard.repairPublishing = true
  standardBoard.error = ''
  try {
    const response = await standardBoardService.publishRepairs(standardBoard.selectedRepairIds)
    const published = response.data?.published || []
    const skipped = response.data?.skipped || []
    standardBoard.selectedRepairIds = []
    await Promise.all([fetchStandardRoutes(), fetchRepairRoutes()])
    if (published.length) ElMessage.success(`已放入线路库 ${published.length} 条`)
    if (skipped.length) ElMessage.warning(`有 ${skipped.length} 条未发布，请查看状态`)
  } catch (error) {
    standardBoard.error = error.response?.data?.detail || error.message || '修复路线发布失败'
  } finally {
    standardBoard.repairPublishing = false
  }
}

function handleStandardModeChange(mode) {
  if (mode === 'repairs' && !standardBoard.repairs.length) fetchRepairRoutes()
  if (mode === 'routes' && !standardBoard.routes.length) fetchStandardRoutes()
}

function getStandardBoardCoordStyle(coord = 'A1') {
  const [, rawColumn = 'A', rawRow = '1'] = String(coord).match(/^([A-Z]+)(\d+)$/i) || []
  const column = rawColumn.toUpperCase()
  const row = Number(rawRow) || 1
  const xIndex = Math.max(0, standardBoardColumns.indexOf(column))
  const yIndex = Math.max(0, standardBoardRows.indexOf(row))
  const xMm = standardBoardSpec.margin_left_mm + xIndex * standardBoardSpec.hole_spacing_x_mm
  const yMm = standardBoardSpec.margin_bottom_mm + yIndex * standardBoardSpec.hole_spacing_y_mm
  return {
    left: `${(xMm / standardBoardSpec.board_width_mm) * 100}%`,
    bottom: `${(yMm / standardBoardSpec.board_height_mm) * 100}%`,
  }
}

async function generateStandardRoute() {
  standardBoard.generating = true
  standardBoard.error = ''
  standardBoard.generatedMeta = null
  try {
    const response = await standardBoardService.generateRoute({
      target_difficulty: standardBoard.filters.difficulty,
      benchmark_only: standardBoard.filters.benchmark_only,
      variation: true,
    })
    standardBoard.selected = response.data?.route || null
    standardBoard.generatedMeta = {
      reuse_rate: response.data?.reuse_rate || 0,
      reuse_quality: response.data?.reuse_quality || 'below_pass',
    }
    ElMessage.success('候选线路已生成并加载坐标预览')
  } catch (error) {
    standardBoard.error = error.response?.data?.detail || error.message || '标准板线路生成失败'
  } finally {
    standardBoard.generating = false
  }
}

function loadStandardIntoStudio() {
  if (!standardBoard.selected?.board_asset) return
  studio.loadBoard(standardBoard.selected.board_asset, { markUnsaved: true })
  activePage.value = 'studio'
  ElMessage.info('标准线路副本已载入定线工作台；原始线路不会被覆盖。')
}

function openSelectedRouteSimulation() {
  if (!simulationEnabled) return
  if (!standardBoard.selected?.source_id) return
  simulationSourceId.value = standardBoard.selected.source_id
  activePage.value = 'simulation'
}

function loadSimulationCandidate(board) {
  if (!board) return
  studio.loadBoard(board, { markUnsaved: true })
  activePage.value = 'studio'
  ElMessage.success('修复副本已载入定线工作台，原线路未被覆盖')
}

function tierLabel(tier) {
  return {
    excellent: '优质',
    good: '好线',
    climbable: '可爬',
    review: '需复核',
    rejected: '已淘汰',
  }[tier] || '需复核'
}

function markerLabel(role) {
  return {
    start: '起点',
    start_hand: '手起点',
    start_foot: '脚起点',
    mid: '中间点',
    end: '终点',
  }[role] || role
}

function resultLabel(result) {
  return {
    flash: 'Flash',
    send: '完成',
    attempt: '尝试',
    fail: '失败',
  }[result] || '无记录'
}

function repairStatusLabel(status) {
  return {
    repairable: '可尝试',
    repaired: '已修复候选',
    unrepairable: '不可修复',
  }[status] || status
}

function gradeWarningLabel(route = {}) {
  if (!route?.grade_warning || route.grade_warning === 'none') return '难度匹配'
  if (route.grade_warning === 'uncertain') return '难度可信度不足'
  const direction = Number(route.grade_delta || 0) > 0 ? '疑似偏硬' : '疑似偏软'
  return route.grade_warning === 'hard' ? `${direction}，需复核` : direction
}

function percentLabel(value) {
  if (value === undefined || value === null) return '-'
  return `${Math.round(Number(value) * 100)}%`
}

function scoreBreakdownItems(breakdown = {}) {
  const labels = {
    movement_quality: '动作质量',
    climbable_structure: '可攀结构',
    grade_confidence: '难度可信',
    aesthetics: '线路变化',
    data_support: '数据辅助',
  }
  return Object.entries(labels)
    .filter(([key]) => breakdown[key] !== undefined)
    .map(([key, label]) => ({ key, label, value: Number(breakdown[key]).toFixed(1) }))
}

function difficultyBreakdownItems(breakdown = {}) {
  const labels = {
    move_distance: '跨度',
    hold_demand: '岩点',
    foot_demand: '脚点',
    body_tension: '张力',
    sequence_complexity: '复杂度',
    start_finish_pressure: '起终压力',
    data_adjustment: '数据修正',
  }
  return Object.entries(labels)
    .filter(([key]) => breakdown[key] !== undefined)
    .map(([key, label]) => ({ key, label, value: Number(breakdown[key]).toFixed(1) }))
}

function selectAiBoard(board) {
  aiExperiment.selectedBoardId = board.saved_id || ''
}

function loadSelectedAiBoardIntoStudio() {
  if (!selectedAiBoard.value) return
  loadBoardIntoStudio(selectedAiBoard.value)
}

function cloneBoardForAi(board) {
  return JSON.parse(JSON.stringify(board))
}

function suggestionGroupLabel(suggestion) {
  if (suggestion.group === 'must_fix') return '必须修'
  if (suggestion.group === 'should_fix') return '建议修'
  if (suggestion.group === 'optional') return '可选优化'
  const text = `${suggestion.title || ''} ${suggestion.detail || ''}`
  if (text.includes('Beta') || text.includes('动作序列')) return '信息补充'
  if (text.includes('修正') || text.includes('调整') || text.includes('风险')) return '必须修'
  return '建议优化'
}

function reuseQualityLabel(value) {
  return {
    below_pass: '低于通过标准',
    pass: '达到通过标准',
    optimal: '达到最优标准',
  }[value] || '待复核'
}

function riskLevelLabel(level) {
  return {
    low: '低',
    medium: '中',
    high: '高',
  }[level] || level
}

function riskAssessmentLabel(result) {
  if (result?.metrics?.risk_assessment_status === 'partial') return '风险未完整评估'
  return `风险${riskLevelLabel(result?.risk_level)}`
}

function riskMetricLabel(metrics = {}) {
  const scope = metrics.risk_scope
  if (metrics.risk_assessment_status === 'partial') {
    return `结构风险 ${metrics.risk_score} / 动作未完整评估`
  }
  if (scope === 'structure_and_action') return `结构与动作风险 ${metrics.risk_score}`
  if (scope === 'structure_and_difficulty') return `结构与难度风险 ${metrics.risk_score}`
  return `结构风险 ${metrics.risk_score}`
}

function reviewScopeLabel(scope) {
  return {
    full_beta: '已执行完整 Beta 检查',
    layout_and_difficulty: '结构与难度专项检查',
    layout_only: '岩点布局初审',
  }[scope] || scope
}

function evidenceStatusLabel(status) {
  return {
    measured: '已量化',
    estimated: '为模型估算',
    not_measured: '尚未量化',
  }[status] || '待复核'
}

function aiTaskStatusLabel(status) {
  return {
    idle: '尚未提交',
    pending: '等待执行',
    running: '正在计算',
    completed: '已完成',
    failed: '执行失败',
    cancelled: '已取消',
  }[status] || status
}

function candidateMeta(index) {
  return routeGen.result?.candidate_routes?.[index] || {}
}

function runAiExperiment() {
  if (aiBoardBlockingMessage.value) {
    ElMessage.warning(aiBoardBlockingMessage.value)
    return
  }

  const board = cloneBoardForAi(selectedAiBoard.value)
  ElMessage.info(`已提交“${board.route_name || '未命名岩板'}”，AI 实验室将返回可查询任务结果。`)
  routeGen.generateRoute({
    mode: aiExperiment.mode,
    board,
    generation_goal: aiExperiment.generation_goal,
    review_focus: aiExperiment.review_focus,
    target_difficulty: FONT_GRADES.includes(board.difficulty) ? board.difficulty : DEFAULT_FONT_GRADE,
  })
}
</script>
<style scoped>
.photo-task-notice {display:flex;align-items:center;flex-wrap:wrap;gap:12px;padding:10px 20px;background:#fff3c4;color:#453709;border-bottom:1px solid #e2d297;font-size:14px}
.photo-task-notice button {min-height:36px;padding:6px 12px;border:1px solid #aa8a28;border-radius:6px;background:transparent;color:inherit;cursor:pointer}
</style>
