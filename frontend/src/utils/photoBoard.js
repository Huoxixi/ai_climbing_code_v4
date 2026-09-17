export const PHOTO_BOARD = Object.freeze({ columns: 20, rows: 30, board_width_mm: 4100, board_height_mm: 6200, hole_spacing_x_mm: 200, hole_spacing_y_mm: 200, margin_left_mm: 200, margin_right_mm: 100, margin_bottom_mm: 100, margin_top_mm: 300, snap_mode: 'none' })
export const clone = (value) => JSON.parse(JSON.stringify(value))
export const columnLabel = (index) => index < 26 ? String.fromCharCode(65 + index) : `A${String.fromCharCode(65 + index - 26)}`
export const photoHoles = () => Array.from({ length: PHOTO_BOARD.columns * PHOTO_BOARD.rows }, (_, index) => ({ id: `${columnLabel(index % PHOTO_BOARD.columns)}${Math.floor(index / PHOTO_BOARD.columns) + 1}`, x: PHOTO_BOARD.margin_left_mm + (index % PHOTO_BOARD.columns) * PHOTO_BOARD.hole_spacing_x_mm, y: PHOTO_BOARD.margin_bottom_mm + Math.floor(index / PHOTO_BOARD.columns) * PHOTO_BOARD.hole_spacing_y_mm }))

export function mapPhotoPoint(matrix, x, y) {
  if (!Array.isArray(matrix) || matrix.length !== 3 || matrix.some(row => !Array.isArray(row) || row.length !== 3)) return null
  const denominator = matrix[2][0] * x + matrix[2][1] * y + matrix[2][2]
  if (!Number.isFinite(denominator) || Math.abs(denominator) < 1e-9) return null
  const mapped = {
    x: (matrix[0][0] * x + matrix[0][1] * y + matrix[0][2]) / denominator,
    y: (matrix[1][0] * x + matrix[1][1] * y + matrix[1][2]) / denominator,
  }
  return Number.isFinite(mapped.x) && Number.isFinite(mapped.y) ? mapped : null
}

function invertMatrix3(matrix) {
  if (!Array.isArray(matrix) || matrix.length !== 3) return null
  const [a,b,c,d,e,f,g,h,i] = matrix.flat().map(Number)
  const determinant = a*(e*i-f*h)-b*(d*i-f*g)+c*(d*h-e*g)
  if (![a,b,c,d,e,f,g,h,i,determinant].every(Number.isFinite) || Math.abs(determinant) < 1e-9) return null
  return [
    [(e*i-f*h)/determinant,(c*h-b*i)/determinant,(b*f-c*e)/determinant],
    [(f*g-d*i)/determinant,(a*i-c*g)/determinant,(c*d-a*f)/determinant],
    [(d*h-e*g)/determinant,(b*g-a*h)/determinant,(a*e-b*d)/determinant],
  ]
}

export function photoGridOverlay(calibration) {
  const inverse = invertMatrix3(calibration?.matrix)
  if (!inverse) return null
  const left = PHOTO_BOARD.margin_left_mm
  const right = left + (PHOTO_BOARD.columns - 1) * PHOTO_BOARD.hole_spacing_x_mm
  const bottom = PHOTO_BOARD.margin_bottom_mm
  const top = bottom + (PHOTO_BOARD.rows - 1) * PHOTO_BOARD.hole_spacing_y_mm
  const point = (column, row) => mapPhotoPoint(inverse,
    left + column * PHOTO_BOARD.hole_spacing_x_mm,
    top - row * PHOTO_BOARD.hole_spacing_y_mm)
  const columns = Array.from({length:PHOTO_BOARD.columns},(_,column)=>({column,start:point(column,0),end:point(column,PHOTO_BOARD.rows-1)}))
  const rows = Array.from({length:PHOTO_BOARD.rows},(_,row)=>({row,start:point(0,row),end:point(PHOTO_BOARD.columns-1,row)}))
  if ([...columns,...rows].some(line=>!line.start||!line.end)) return null
  return { columns, rows, centerColumn:Math.floor(PHOTO_BOARD.columns/2) }
}

export function calibratedObjectSize(object, matrix) {
  const [x, y, width, height] = object?.source_bbox_px || []
  if (![x, y, width, height].every(Number.isFinite) || width <= 0 || height <= 0) return null
  const points = [
    mapPhotoPoint(matrix, x, y),
    mapPhotoPoint(matrix, x + width, y),
    mapPhotoPoint(matrix, x + width, y + height),
    mapPhotoPoint(matrix, x, y + height),
  ]
  if (points.some(point => !point)) return null
  const distance = (a, b) => Math.hypot(a.x - b.x, a.y - b.y)
  return {
    width: (distance(points[0], points[1]) + distance(points[3], points[2])) / 2,
    height: (distance(points[0], points[3]) + distance(points[1], points[2])) / 2,
  }
}

function median(values) {
  if (!values.length) return 0
  const sorted = [...values].sort((a, b) => a - b)
  const middle = Math.floor(sorted.length / 2)
  return sorted.length % 2 ? sorted[middle] : (sorted[middle - 1] + sorted[middle]) / 2
}

export function calibratedObjectCenter(object, matrix) {
  const [x, y, width, height] = object?.source_bbox_px || []
  const hasConfirmedAnchor = (object?.anchors || []).some(anchor => anchor.confirmed)
  if (hasConfirmedAnchor && [x, y, width, height].every(Number.isFinite) && width > 0 && height > 0) {
    const mapped = mapPhotoPoint(matrix, x + width / 2, y + height / 2)
    if (mapped) return mapped
  }
  return { x: Number(object?.center_x_mm || 0), y: Number(object?.center_y_mm || 0) }
}

export function photoRouteAxisLayout(objects, matrix) {
  if (!objects?.length) return { points:[], axis:null }
  const raw = objects.map(object => ({ object, point: calibratedObjectCenter(object, matrix) }))
  const routeCenterX = median(raw.map(item => item.point.x))
  const axisIndex = Math.max(0, Math.min(PHOTO_BOARD.columns - 1,
    Math.round((routeCenterX - PHOTO_BOARD.margin_left_mm) / PHOTO_BOARD.hole_spacing_x_mm)))
  const axisX = PHOTO_BOARD.margin_left_mm + axisIndex * PHOTO_BOARD.hole_spacing_x_mm
  const axisLabel = columnLabel(axisIndex)
  const axisDx = axisX - routeCenterX
  const axisDy = median(raw.map(({ point }) => {
    const rowIndex = Math.round((point.y - PHOTO_BOARD.margin_bottom_mm) / PHOTO_BOARD.hole_spacing_y_mm)
    return PHOTO_BOARD.margin_bottom_mm + rowIndex * PHOTO_BOARD.hole_spacing_y_mm - point.y
  }))
  const axisLaneHalfWidth = PHOTO_BOARD.hole_spacing_x_mm * .42
  const sideFor = (x) => {
    const alignedX = x + axisDx
    if (Math.abs(alignedX - axisX) <= axisLaneHalfWidth) return 'axis'
    return alignedX < axisX ? 'left' : 'right'
  }
  const sideCorrections = Object.fromEntries(['left','axis','right'].map(side => {
    const members = raw.filter(item => sideFor(item.point.x) === side)
    if (!members.length || side === 'axis') return [side,{ x:0, y:0 }]
    const corrections = members.map(({ object, point }) => {
      const confirmed = (object.anchors || []).filter(anchor => anchor.confirmed && Number.isFinite(anchor.x_mm) && Number.isFinite(anchor.y_mm))
      if (confirmed.length) {
        const targetX = confirmed.reduce((sum, anchor) => sum + anchor.x_mm, 0) / confirmed.length
        const targetY = confirmed.reduce((sum, anchor) => sum + anchor.y_mm, 0) / confirmed.length
        return { x:targetX - (point.x + axisDx), y:targetY - (point.y + axisDy), confirmed:true }
      }
      const hole = nearestPhotoHole(point.x + axisDx, point.y + axisDy, 150)
      return hole ? { x:hole.x - (point.x + axisDx), y:hole.y - (point.y + axisDy), confirmed:false } : { x:0, y:0, confirmed:false }
    })
    const confirmed = corrections.filter(item => item.confirmed)
    const evidence = confirmed.length ? confirmed : corrections
    return [side,{
      x:Math.max(-100,Math.min(100,median(evidence.map(item => item.x)))),
      y:Math.max(-100,Math.min(100,median(evidence.map(item => item.y)))),
    }]
  }))
  const points = raw.map(({ object, point }) => {
    const side = sideFor(point.x)
    const correction = sideCorrections[side]
    const x = Math.max(0,Math.min(PHOTO_BOARD.board_width_mm,point.x + axisDx + correction.x))
    const y = Math.max(0,Math.min(PHOTO_BOARD.board_height_mm,point.y + axisDy + correction.y))
    const confirmed = (object.anchors || []).filter(anchor => anchor.confirmed && Number.isFinite(anchor.x_mm) && Number.isFinite(anchor.y_mm))
    const suggested = nearestPhotoHole(x, y, 150)
    const target = confirmed.length ? {
      x: confirmed.reduce((sum, anchor) => sum + anchor.x_mm, 0) / confirmed.length,
      y: confirmed.reduce((sum, anchor) => sum + anchor.y_mm, 0) / confirmed.length,
      id: confirmed.map(anchor => anchor.hole_id).filter(Boolean).join(' / '),
    } : suggested ? { x:suggested.x, y:suggested.y, id:suggested.id } : null
    return {
      id: object.id,
      x,
      y,
      rawX: point.x,
      rawY: point.y,
      dx: axisDx + correction.x,
      dy: axisDy + correction.y,
      side,
      axisX,
      axisLabel,
      target,
      anchored: Boolean(confirmed.length),
      suggested: !confirmed.length && Boolean(target),
      residual: target ? Math.hypot(target.x - x, target.y - y) : null,
      label: target?.id || '',
    }
  })
  return {
    points,
    axis: {
      x: axisX,
      label: axisLabel,
      columnIndex: axisIndex,
      laneHalfWidth: axisLaneHalfWidth,
      counts: Object.fromEntries(['left','axis','right'].map(side => [side,points.filter(point => point.side === side).length])),
      corrections: sideCorrections,
    },
  }
}

export function relativePhotoLayout(objects, matrix) {
  return photoRouteAxisLayout(objects, matrix).points
}

export function objectInstallationPoint(object) {
  if (!object) return { x:0, y:0, anchored:false, suggested:false, label:'' }
  const confirmed = (object?.anchors || []).filter(anchor => anchor.confirmed && Number.isFinite(anchor.x_mm) && Number.isFinite(anchor.y_mm))
  if (confirmed.length) return {
    x: confirmed.reduce((sum, anchor) => sum + anchor.x_mm, 0) / confirmed.length,
    y: confirmed.reduce((sum, anchor) => sum + anchor.y_mm, 0) / confirmed.length,
    anchored: true,
    suggested: false,
    label: confirmed.map(anchor => anchor.hole_id).filter(Boolean).join(' / '),
  }
  const proposed = (object?.anchors || []).filter(anchor => Number.isFinite(anchor.x_mm) && Number.isFinite(anchor.y_mm))
  if (proposed.length) return {
    x: proposed.reduce((sum, anchor) => sum + anchor.x_mm, 0) / proposed.length,
    y: proposed.reduce((sum, anchor) => sum + anchor.y_mm, 0) / proposed.length,
    anchored: false,
    suggested: true,
    label: proposed.map(anchor => anchor.hole_id).filter(Boolean).join(' / '),
  }
  const nearest = nearestPhotoHole(object.center_x_mm, object.center_y_mm, 150)
  return nearest
    ? { x: nearest.x, y: nearest.y, anchored: false, suggested: true, label: nearest.id }
    : { x: object.center_x_mm, y: object.center_y_mm, anchored: false, suggested: false, label: '' }
}

export function nearestPhotoHole(x, y, threshold = 110) {
  const hole = photoHoles().reduce((best, item) => {
    const distance = Math.hypot(item.x - x, item.y - y)
    return !best || distance < best.distance ? { ...item, distance } : best
  }, null)
  return hole && hole.distance <= threshold ? hole : null
}

export function snapObjectToHole(object, threshold = 110) {
  const preview = nearestPhotoHole(object.center_x_mm, object.center_y_mm, threshold)
  if (!preview) return { object, preview: null }
  return {
    object: { ...object, center_x_mm: preview.x, center_y_mm: preview.y,
      anchors: [{ hole_id: preview.id, x_mm: preview.x, y_mm: preview.y, confidence: 1, confirmed: true }] },
    preview,
  }
}

export function bounds(object) {
  const angle = object.rotation_deg * Math.PI / 180
  const w = object.source_bbox_px[2] * object.scale_mm_per_px
  const h = object.source_bbox_px[3] * object.scale_mm_per_px
  const dx = (Math.abs(w * Math.cos(angle)) + Math.abs(h * Math.sin(angle))) / 2
  const dy = (Math.abs(w * Math.sin(angle)) + Math.abs(h * Math.cos(angle))) / 2
  return { left: object.center_x_mm - dx, right: object.center_x_mm + dx, bottom: object.center_y_mm - dy, top: object.center_y_mm + dy }
}
export function union(objects) {
  const boxes = objects.map(bounds)
  return { left: Math.min(...boxes.map(b => b.left)), right: Math.max(...boxes.map(b => b.right)), bottom: Math.min(...boxes.map(b => b.bottom)), top: Math.max(...boxes.map(b => b.top)) }
}
export function withinBoard(objects) {
  return objects.length > 0 && objects.every(o => {
    if (![o.center_x_mm, o.center_y_mm, o.scale_mm_per_px, o.rotation_deg].every(Number.isFinite) || o.scale_mm_per_px <= 0) return false
    const b = bounds(o)
    return b.left >= -1e-6 && b.bottom >= -1e-6 && b.right <= PHOTO_BOARD.board_width_mm + 1e-6 && b.top <= PHOTO_BOARD.board_height_mm + 1e-6
  })
}
export function fitPhotoObjects(objects) {
  if (!objects.length) return []
  const left = Math.min(...objects.map(o => o.source_bbox_px[0]))
  const top = Math.min(...objects.map(o => o.source_bbox_px[1]))
  const right = Math.max(...objects.map(o => o.source_bbox_px[0] + o.source_bbox_px[2]))
  const bottom = Math.max(...objects.map(o => o.source_bbox_px[1] + o.source_bbox_px[3]))
  const usableWidth = PHOTO_BOARD.board_width_mm - 400, usableHeight = PHOTO_BOARD.board_height_mm - 400
  const scale = Math.min(usableWidth / (right - left), usableHeight / (bottom - top))
  return objects.map(o => ({ ...o, center_x_mm: PHOTO_BOARD.board_width_mm / 2 + (o.source_bbox_px[0] + o.source_bbox_px[2] / 2 - (left + right) / 2) * scale, center_y_mm: PHOTO_BOARD.board_height_mm / 2 - (o.source_bbox_px[1] + o.source_bbox_px[3] / 2 - (top + bottom) / 2) * scale, scale_mm_per_px: scale, rotation_deg: 0 }))
}
export function translateObjects(objects, dx, dy) {
  const b = union(objects)
  dx = Math.max(-b.left, Math.min(PHOTO_BOARD.board_width_mm - b.right, dx))
  dy = Math.max(-b.bottom, Math.min(PHOTO_BOARD.board_height_mm - b.top, dy))
  return objects.map(o => ({ ...o, center_x_mm: o.center_x_mm + dx, center_y_mm: o.center_y_mm + dy }))
}
export function scaleObjects(objects, factor) {
  const b = union(objects)
  const cx = (b.left + b.right) / 2, cy = (b.bottom + b.top) / 2
  const result = objects.map(o => ({ ...o, center_x_mm: cx + (o.center_x_mm - cx) * factor, center_y_mm: cy + (o.center_y_mm - cy) * factor, scale_mm_per_px: o.scale_mm_per_px * factor }))
  return withinBoard(result) ? result : objects
}
export function patchObject(object, patch) {
  const next = { ...object, ...patch }
  return withinBoard([next]) ? next : object
}
export function createHistory(limit = 60) {
  const past = [], future = []
  return {
    get canUndo() { return past.length > 0 }, get canRedo() { return future.length > 0 },
    push(value) { past.push(clone(value)); if (past.length > limit) past.shift(); future.length = 0 },
    undo(value) { if (!past.length) return value; future.push(clone(value)); return past.pop() },
    redo(value) { if (!future.length) return value; past.push(clone(value)); return future.pop() },
    clear() { past.length = 0; future.length = 0 },
  }
}

// Zoom around a screen-space focal point; camera movement never edits world coordinates.
export function zoomCamera(camera, factor, point) {
  const zoom = Math.max(1, Math.min(8, camera.zoom * factor))
  const ratio = zoom / camera.zoom
  return { zoom, x: point.x - (point.x - camera.x) * ratio, y: point.y - (point.y - camera.y) * ratio }
}
