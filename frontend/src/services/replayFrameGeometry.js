// Mirror saved renderer geometry; adapt old movies without modifying them.
const round = v => v % 1 === .5 ? 2 * Math.round(v / 2) : Math.round(v)
const fit = (sw, sh, x, y, w, h) => {
  const s = Math.min(w / sw, h / sh), rw = Math.max(1, round(sw * s)), rh = Math.max(1, round(sh * s))
  return [x + Math.floor((w - rw) / 2), y + Math.floor((h - rh) / 2), rw, rh]
}
export function replayFrameGeometry(result) {
  const o = result?.overlay || {}, source = result?.video || {}
  if (!['split_route_map_actions_v8', 'split_route_map_stats_v9', 'split_route_map_equal_v10', 'split_analysis_right_v11'].includes(o.layout)
    || ![o.width, o.height, source.width, source.height].every(v => Number.isFinite(v) && v > 0)) return null
  const { width: w, height: h } = o, count = o.action_count || 0
  const columns = count ? Math.min(Math.max(1, count), Math.max(5, Math.min(10, Math.floor(w / 110)))) : 1
  const rows = Math.max(1, Math.ceil(count / columns))
  const strip = o.layout.endsWith('v8') ? count ? Math.max(54, round(h * Math.min(.28, .075 + .065 * rows))) : Math.max(42, round(h * .10)) : 0
  const content = Math.max(2, h - strip), oldPane = round(w * (o.layout.endsWith('v10') || o.layout.endsWith('v11') ? .5 : strip ? .64 : .70))
  const oldVideo = o.video_rect || fit(source.width, source.height, 0, 0, oldPane, content)
  const video = [0, 0, source.width, source.height]
  const panel = [source.width, 0, source.width, source.height]
  return { width: source.width * 2, height: source.height, oldVideo, video,
    oldPanel: [oldPane, 0, w - oldPane, content], panel, map: panel, mapClip: panel, source }
}
export const projectPoint = (xy, rect) => [rect[0] + xy[0] * rect[2], rect[1] + xy[1] * rect[3]]
export function referenceToFrame(xy, matrix, source) {
  if (!Array.isArray(matrix) || matrix.length !== 3 || matrix.some(row => !Array.isArray(row) || row.length !== 3 || !row.every(Number.isFinite))) return null
  const [[a,b,c],[d,e,f],[g,h,i]] = matrix
  const inv = [[e*i-f*h,c*h-b*i,b*f-c*e],[f*g-d*i,a*i-c*g,c*d-a*f],[d*h-e*g,b*g-a*h,a*e-b*d]]
  const det = a*inv[0][0]+b*inv[1][0]+c*inv[2][0]
  if (Math.abs(det) < 1e-9) return null
  const p = [xy[0]*source.width, xy[1]*source.height, 1]
  const mapped = inv.map(row => row.reduce((sum, v, k) => sum+v*p[k], 0))
  if (Math.abs(mapped[2]) < 1e-9) return null
  return [mapped[0]/mapped[2]/source.width, mapped[1]/mapped[2]/source.height]
}
