import { computed, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { BOARD_TEMPLATES, DEFAULT_BOARD_TEMPLATE_ID, createAxisLabels, createBoardSpecSnapshot, getBoardTemplateById, normalizeBoardSpec } from '../constants/boardTemplates'
import { createBlankBoard } from './useBoardEditor'

export function useStudioEditor() {
  const currentBoard = ref(createBlankBoard())
  const activeBoardPresetId = ref(DEFAULT_BOARD_TEMPLATE_ID)
  const selectedHold = ref(null)
  const selectedPoolHold = ref(null)
  const unsavedChanges = ref(false)
  const betaForm = reactive({ limb: 'LH', hold_id: '', is_top: false })

  const currentBoardSpec = computed(() => normalizeBoardSpec(currentBoard.value.board_spec))
  const coordinateColumns = computed(() => currentBoardSpec.value.xLabels || createAxisLabels(currentBoardSpec.value.columns))
  const coordinateRows = computed(() => currentBoardSpec.value.yLabels || Array.from({ length: currentBoardSpec.value.rows }, (_, index) => index + 1))
  const placedHolds = computed(() => currentBoard.value.placed_holds || [])
  const routeSteps = computed(() => currentBoard.value.beta_sequence || [])

  const boardFrameStyle = computed(() => {
    const spec = currentBoardSpec.value
    return {
      '--board-ratio': `${spec.board_width_mm || spec.width || 560} / ${spec.board_height_mm || spec.height || 760}`,
      '--board-columns': spec.columns,
      '--board-rows': spec.rows,
      '--grid-left': `${(Number(spec.margin_left_mm || 0) / Number(spec.board_width_mm || spec.width || 1)) * 100}%`,
      '--grid-right': `${(Number(spec.margin_right_mm || 0) / Number(spec.board_width_mm || spec.width || 1)) * 100}%`,
      '--grid-bottom': `${(Number(spec.margin_bottom_mm || 0) / Number(spec.board_height_mm || spec.height || 1)) * 100}%`,
      '--grid-top': `${(Number(spec.margin_top_mm || 0) / Number(spec.board_height_mm || spec.height || 1)) * 100}%`,
    }
  })

  function markUnsaved() {
    unsavedChanges.value = true
    currentBoard.value.updated_at = new Date().toISOString()
  }

  function getCoordParts(coord = 'A1') {
    const [, column = 'A', row = '1'] = String(coord).match(/^([A-Z]+)(\d+)$/i) || []
    return { column: column.toUpperCase(), row: Number(row) || 1 }
  }

  function getCoordStyle(coord) {
    const { column, row } = getCoordParts(coord)
    const xIndex = coordinateColumns.value.indexOf(column)
    const yIndex = coordinateRows.value.indexOf(row)
    const spec = currentBoardSpec.value
    const boardWidth = Number(spec.board_width_mm || spec.width || 1)
    const boardHeight = Number(spec.board_height_mm || spec.height || 1)
    const xMm = Number(spec.margin_left_mm || 0) + Math.max(0, xIndex) * Number(spec.hole_spacing_x_mm || 200)
    const yMm = Number(spec.margin_bottom_mm || 0) + Math.max(0, yIndex) * Number(spec.hole_spacing_y_mm || 200)
    return {
      left: `${(xMm / boardWidth) * 100}%`,
      bottom: `${(yMm / boardHeight) * 100}%`,
    }
  }

  function selectPoolHold(hold) {
    selectedPoolHold.value = { ...hold }
  }

  function placeHold(coord) {
    if (!selectedPoolHold.value) {
      ElMessage.info('请先从左侧选择一个岩点')
      return
    }
    if (placedHolds.value.some((hold) => hold.id === coord)) {
      ElMessage.warning(`孔位 ${coord} 已有岩点`)
      return
    }

    const hold = {
      id: coord,
      x: getCoordParts(coord).column,
      y: getCoordParts(coord).row,
      hold_type: selectedPoolHold.value.hold_type || selectedPoolHold.value.type || 'Jug',
      type: selectedPoolHold.value.hold_type || selectedPoolHold.value.type || 'Jug',
      variant: selectedPoolHold.value.variant || 'default',
      rotation: Number(selectedPoolHold.value.rotation || 0),
      scale: Number(selectedPoolHold.value.scale || 1),
      is_start: false,
    }
    currentBoard.value.placed_holds.push(hold)
    selectedHold.value = hold
    betaForm.hold_id = hold.id
    markUnsaved()
  }

  function updateSelectedHold(patch) {
    if (!selectedHold.value) return
    Object.assign(selectedHold.value, patch)
    markUnsaved()
  }

  function deleteSelectedHold() {
    if (!selectedHold.value) return
    const holdId = selectedHold.value.id
    currentBoard.value.placed_holds = placedHolds.value.filter((hold) => hold.id !== holdId)
    currentBoard.value.beta_sequence = routeSteps.value.filter((step) => step.hold_id !== holdId)
    selectedHold.value = null
    markUnsaved()
  }

  function addBetaStep() {
    const holdId = betaForm.hold_id || selectedHold.value?.id
    if (!holdId) {
      ElMessage.info('请先选择动作目标岩点')
      return
    }
    currentBoard.value.beta_sequence.push({
      step: routeSteps.value.length,
      limb: betaForm.limb,
      hold_id: holdId,
      is_top: betaForm.is_top,
    })
    betaForm.is_top = false
    markUnsaved()
  }

  function deleteBetaStep(index) {
    currentBoard.value.beta_sequence = routeSteps.value
      .filter((_, stepIndex) => stepIndex !== index)
      .map((step, stepIndex) => ({ ...step, step: stepIndex }))
    markUnsaved()
  }

  async function applyBoardPreset(presetId) {
    const preset = getBoardTemplateById(presetId)
    if (!preset) return
    const outOfRange = placedHolds.value.filter((hold) => {
      const { column, row } = getCoordParts(hold.id)
      return !createAxisLabels(preset.columns).includes(column) || row < 1 || row > preset.rows
    })
    if (outOfRange.length) {
      try {
        await ElMessageBox.confirm(`当前有 ${outOfRange.length} 个岩点超出新岩板范围，切换规格会移除这些岩点及相关 Beta。`, '切换岩板规格', {
          confirmButtonText: '继续',
          cancelButtonText: '取消',
          type: 'warning',
        })
      } catch {
        return
      }
      const removedIds = new Set(outOfRange.map((hold) => hold.id))
      currentBoard.value.placed_holds = placedHolds.value.filter((hold) => !removedIds.has(hold.id))
      currentBoard.value.beta_sequence = routeSteps.value.filter((step) => !removedIds.has(step.hold_id))
    }
    activeBoardPresetId.value = preset.id
    currentBoard.value.board_spec = createBoardSpecSnapshot(preset)
    markUnsaved()
  }

  async function newBlankBoard(presetId = activeBoardPresetId.value) {
    if (unsavedChanges.value) {
      try {
        await ElMessageBox.confirm('当前岩板有未保存修改，确定新建岩板？', '新建岩板', {
          confirmButtonText: '新建',
          cancelButtonText: '取消',
          type: 'warning',
        })
      } catch {
        return false
      }
    }
    const preset = getBoardTemplateById(presetId)
    currentBoard.value = createBlankBoard({ board_spec: createBoardSpecSnapshot(preset) })
    activeBoardPresetId.value = preset.id
    selectedHold.value = null
    unsavedChanges.value = false
    return true
  }

  async function clearBoard() {
    try {
      await ElMessageBox.confirm('确定清空当前岩板上的所有岩点和 Beta 序列？', '清空岩板', {
        confirmButtonText: '清空',
        cancelButtonText: '取消',
        type: 'warning',
      })
    } catch {
      return
    }
    currentBoard.value.placed_holds = []
    currentBoard.value.beta_sequence = []
    selectedHold.value = null
    markUnsaved()
  }

  function loadBoard(board, { markUnsaved = false } = {}) {
    const copy = JSON.parse(JSON.stringify(board))
    if (markUnsaved) delete copy.saved_id
    copy.board_spec = normalizeBoardSpec(copy.board_spec)
    copy.placed_holds = Array.isArray(copy.placed_holds) ? copy.placed_holds : []
    copy.beta_sequence = Array.isArray(copy.beta_sequence) ? copy.beta_sequence : []
    currentBoard.value = copy
    activeBoardPresetId.value = copy.board_spec.preset_id || DEFAULT_BOARD_TEMPLATE_ID
    selectedHold.value = null
    unsavedChanges.value = markUnsaved
  }

  return {
    boardPresets: BOARD_TEMPLATES,
    currentBoard,
    activeBoardPresetId,
    selectedHold,
    selectedPoolHold,
    unsavedChanges,
    betaForm,
    currentBoardSpec,
    coordinateColumns,
    coordinateRows,
    placedHolds,
    routeSteps,
    boardFrameStyle,
    getCoordStyle,
    selectPoolHold,
    placeHold,
    updateSelectedHold,
    deleteSelectedHold,
    addBetaStep,
    deleteBetaStep,
    applyBoardPreset,
    newBlankBoard,
    clearBoard,
    loadBoard,
    markUnsaved,
  }
}
