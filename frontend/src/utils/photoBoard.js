export const PHOTO_BOARD = Object.freeze({ columns: 30, rows: 20, board_width_mm: 6200, board_height_mm: 4100, hole_spacing_x_mm: 200, hole_spacing_y_mm: 200, margin_left_mm: 200, margin_right_mm: 200, margin_bottom_mm: 100, margin_top_mm: 200, snap_mode: 'none' })
export const clone = (value) => JSON.parse(JSON.stringify(value))
export const columnLabel = (index) => index < 26 ? String.fromCharCode(65 + index) : `A${String.fromCharCode(65 + index - 26)}`
export const photoHoles = () => Array.from({ length: 600 }, (_, index) => ({ id: `${columnLabel(index % 30)}${Math.floor(index / 30) + 1}`, x: 200 + (index % 30) * 200, y: 100 + Math.floor(index / 30) * 200 }))

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
    return b.left >= -1e-6 && b.bottom >= -1e-6 && b.right <= 6200 + 1e-6 && b.top <= 4100 + 1e-6
  })
}
export function fitPhotoObjects(objects) {
  if (!objects.length) return []
  const left = Math.min(...objects.map(o => o.source_bbox_px[0]))
  const top = Math.min(...objects.map(o => o.source_bbox_px[1]))
  const right = Math.max(...objects.map(o => o.source_bbox_px[0] + o.source_bbox_px[2]))
  const bottom = Math.max(...objects.map(o => o.source_bbox_px[1] + o.source_bbox_px[3]))
  const scale = Math.min(5800 / (right - left), 3800 / (bottom - top))
  return objects.map(o => ({ ...o, center_x_mm: 3100 + (o.source_bbox_px[0] + o.source_bbox_px[2] / 2 - (left + right) / 2) * scale, center_y_mm: 2000 - (o.source_bbox_px[1] + o.source_bbox_px[3] / 2 - (top + bottom) / 2) * scale, scale_mm_per_px: scale, rotation_deg: 0 }))
}
export function translateObjects(objects, dx, dy) {
  const b = union(objects)
  dx = Math.max(-b.left, Math.min(6200 - b.right, dx))
  dy = Math.max(-b.bottom, Math.min(4100 - b.top, dy))
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
