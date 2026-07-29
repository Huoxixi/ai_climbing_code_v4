import { normalizeBoardSpec } from '../constants/boardTemplates.js'

const LIMB_LABELS = {
  LH: '左手',
  RH: '右手',
  LF: '左脚',
  RF: '右脚',
  lh: '左手',
  rh: '右手',
  lf: '左脚',
  rf: '右脚',
}

const CHANGE_LABELS = {
  hold_type: '类型',
  variant: '变体',
  rotation: '旋转',
  scale: '缩放',
  is_start: '起点角色',
  is_top: '终点角色',
}

function holdSnapshot(hold = {}, topIds = new Set()) {
  return {
    hold_type: hold.hold_type || hold.type || 'Jug',
    variant: hold.variant || '',
    rotation: Number(hold.rotation || 0),
    scale: Number(hold.scale || 1),
    is_start: Boolean(hold.is_start),
    is_top: topIds.has(hold.id),
  }
}

function changedFields(referenceHold, targetHold, referenceTopIds, targetTopIds) {
  const reference = holdSnapshot(referenceHold, referenceTopIds)
  const target = holdSnapshot(targetHold, targetTopIds)
  return Object.keys(reference).filter((field) => reference[field] !== target[field])
}

function orderedSteps(board = {}) {
  return [...(board.beta_sequence || [])].sort((a, b) => (
    Number(a.step || 0) - Number(b.step || 0)
  ))
}

function stepSignature(step = {}) {
  return `${String(step.limb || '').toUpperCase()}:${step.hold_id || ''}:${Boolean(step.is_top)}`
}

function stepTopIds(board = {}) {
  return new Set((board.beta_sequence || []).filter((step) => step.is_top).map((step) => step.hold_id))
}

function sortedCoordinates(items) {
  return [...items].sort((a, b) => String(a).localeCompare(String(b), 'en', { numeric: true }))
}

function coordinateList(items, pick = (item) => item.id) {
  return sortedCoordinates(items.map(pick).filter(Boolean))
}

export function reuseTierFor(rate) {
  if (rate >= 0.7) return { key: 'optimal', label: '达到最优标准' }
  if (rate >= 0.4) return { key: 'pass', label: '达到通过标准' }
  return { key: 'large-change', label: '变化较大' }
}

export function betaStepLabel(step = {}, index = 0) {
  const number = Number.isFinite(Number(step.step)) ? Number(step.step) : index + 1
  const limb = LIMB_LABELS[step.limb] || step.limb || '动作'
  const top = step.is_top ? '并登顶' : ''
  return `第 ${number} 步：${limb}到 ${step.hold_id || '未指定岩点'}${top}`
}

export function boardViewModel(board = {}) {
  const spec = normalizeBoardSpec(board.board_spec)
  const columns = spec.xLabels
  const rows = spec.yLabels
  const frameStyle = {
    '--board-ratio': `${spec.board_width_mm} / ${spec.board_height_mm}`,
    '--board-columns': spec.columns,
    '--board-rows': spec.rows,
    '--grid-left': `${(spec.margin_left_mm / spec.board_width_mm) * 100}%`,
    '--grid-right': `${(spec.margin_right_mm / spec.board_width_mm) * 100}%`,
    '--grid-bottom': `${(spec.margin_bottom_mm / spec.board_height_mm) * 100}%`,
    '--grid-top': `${(spec.margin_top_mm / spec.board_height_mm) * 100}%`,
  }

  function getCoordStyle(coord = 'A1') {
    const [, rawColumn = 'A', rawRow = '1'] = String(coord).match(/^([A-Z]+)(\d+)$/i) || []
    const xIndex = Math.max(0, columns.indexOf(rawColumn.toUpperCase()))
    const yIndex = Math.max(0, rows.indexOf(Number(rawRow)))
    const xMm = spec.margin_left_mm + xIndex * spec.hole_spacing_x_mm
    const yMm = spec.margin_bottom_mm + yIndex * spec.hole_spacing_y_mm
    return {
      left: `${(xMm / spec.board_width_mm) * 100}%`,
      bottom: `${(yMm / spec.board_height_mm) * 100}%`,
    }
  }

  return { spec, columns, rows, frameStyle, getCoordStyle }
}

export function compareBoards(reference = {}, target = {}) {
  const referenceHolds = reference.placed_holds || []
  const targetHolds = target.placed_holds || []
  const referenceMap = new Map(referenceHolds.map((hold) => [hold.id, hold]))
  const targetMap = new Map(targetHolds.map((hold) => [hold.id, hold]))
  const referenceTopIds = stepTopIds(reference)
  const targetTopIds = stepTopIds(target)
  const retained = []
  const changed = []
  const added = []
  const removed = []
  const statusById = {}

  for (const hold of referenceHolds) {
    const targetHold = targetMap.get(hold.id)
    if (!targetHold) {
      removed.push(hold)
      statusById[hold.id] = 'removed'
      continue
    }
    const fields = changedFields(hold, targetHold, referenceTopIds, targetTopIds)
    if (fields.length) {
      changed.push({ id: hold.id, fields, labels: fields.map((field) => CHANGE_LABELS[field]) })
      statusById[hold.id] = 'changed'
    } else {
      retained.push(targetHold)
      statusById[hold.id] = 'retained'
    }
  }

  for (const hold of targetHolds) {
    if (!referenceMap.has(hold.id)) {
      added.push(hold)
      statusById[hold.id] = 'added'
    }
  }

  const referenceSteps = orderedSteps(reference)
  const targetSteps = orderedSteps(target)
  const referenceSequence = referenceSteps.map(stepSignature)
  const targetSequence = targetSteps.map(stepSignature)
  const referenceStarts = new Set(referenceHolds.filter((hold) => hold.is_start).map((hold) => hold.id))
  const targetStarts = new Set(targetHolds.filter((hold) => hold.is_start).map((hold) => hold.id))
  const startAdded = [...targetStarts].filter((id) => !referenceStarts.has(id))
  const startRemoved = [...referenceStarts].filter((id) => !targetStarts.has(id))
  const topAdded = [...targetTopIds].filter((id) => !referenceTopIds.has(id))
  const topRemoved = [...referenceTopIds].filter((id) => !targetTopIds.has(id))
  const betaChanged = referenceSequence.join('|') !== targetSequence.join('|')
  const reuseRate = referenceHolds.length ? retained.length / referenceHolds.length : 1
  const reuseTier = reuseTierFor(reuseRate)
  const referenceSpec = normalizeBoardSpec(reference.board_spec)
  const targetSpec = normalizeBoardSpec(target.board_spec)
  const specMismatch = (
    referenceSpec.columns !== targetSpec.columns
    || referenceSpec.rows !== targetSpec.rows
    || referenceSpec.hole_spacing_x_mm !== targetSpec.hole_spacing_x_mm
    || referenceSpec.hole_spacing_y_mm !== targetSpec.hole_spacing_y_mm
  )

  const summaryParts = []
  if (removed.length) summaryParts.push(`取消 ${removed.length} 个岩点（${coordinateList(removed).join('、')}）`)
  if (added.length) summaryParts.push(`新增 ${added.length} 个岩点（${coordinateList(added).join('、')}）`)
  if (changed.length) summaryParts.push(`调整 ${changed.length} 个同坐标岩点（${coordinateList(changed).join('、')}）`)
  if (!removed.length && !added.length && !changed.length) summaryParts.push('岩点布局保持不变')
  if (topAdded.length || topRemoved.length) {
    summaryParts.push(`终点由 ${sortedCoordinates([...referenceTopIds]).join('、') || '未设置'} 调整为 ${sortedCoordinates([...targetTopIds]).join('、') || '未设置'}`)
  } else {
    summaryParts.push(`终点${targetTopIds.size ? `保持在 ${sortedCoordinates([...targetTopIds]).join('、')}` : '仍未设置'}`)
  }
  if (betaChanged) summaryParts.push(`Beta 从 ${referenceSteps.length} 步调整为 ${targetSteps.length} 步`)
  else summaryParts.push(`Beta 保持 ${targetSteps.length} 步`)

  const displayHolds = [
    ...targetHolds,
    ...removed.map((hold) => ({ ...hold, comparison_ghost: true })),
  ]

  return {
    retained,
    changed,
    added,
    removed,
    statusById,
    displayHolds,
    reuseRate,
    reuseTier,
    startAdded: sortedCoordinates(startAdded),
    startRemoved: sortedCoordinates(startRemoved),
    topAdded: sortedCoordinates(topAdded),
    topRemoved: sortedCoordinates(topRemoved),
    betaChanged,
    referenceStepCount: referenceSteps.length,
    targetStepCount: targetSteps.length,
    referenceSequence,
    targetSequence,
    specMismatch,
    summary: `${summaryParts.join('；')}。`,
  }
}
