// Preserve the reference image's aspect ratio; missing observations stay disconnected.
export function torsoTrajectoryPlot(trajectory) {
  const segments = (trajectory?.segments || []).filter(run => Array.isArray(run) && run.length >= 2)
  const points = segments.flat()
  const [width, height] = trajectory?.reference_size || []
  if (trajectory?.status === 'insufficient' || points.length < 3 || !(width > 0 && height > 0)
    || points.some(point => !Array.isArray(point.xy) || !point.xy.every(Number.isFinite))) return null
  const xs = points.map(point => point.xy[0] * width), ys = points.map(point => point.xy[1] * height)
  const minX = Math.min(...xs), maxX = Math.max(...xs), minY = Math.min(...ys), maxY = Math.max(...ys)
  const scale = Math.min(420 / Math.max(width * .08, maxX - minX), 172 / Math.max(height * .08, maxY - minY))
  const x = value => 240 + (value * width - (minX + maxX) / 2) * scale
  const y = value => 112 + (value * height - (minY + maxY) / 2) * scale
  const mapped = segments.map(run => run.map(point => ({ x: x(point.xy[0]), y: y(point.xy[1]), time: point.time_seconds })))
  return { paths: mapped.map(run => run.map(point => `${point.x},${point.y}`).join(' ')),
    start: mapped[0][0], end: mapped.at(-1).at(-1), pointCount: points.length }
}

// Map the registered source coordinates into the same cropped route-map
// coordinate plane used by the split replay renderer. Keeping the viewBox in
// source pixels lets the end-of-video overlay line up with the baked holds.
export function torsoRoutePlot(trajectory, holds = []) {
  const segments = (trajectory?.segments || []).filter(run => Array.isArray(run) && run.length >= 2)
  const [width, height] = trajectory?.reference_size || []
  const points = segments.flat()
  if (trajectory?.status === 'insufficient' || points.length < 3 || !(width > 0 && height > 0)
    || points.some(point => !Array.isArray(point.xy) || !point.xy.every(Number.isFinite))) return null

  const boxes = holds
    .map(hold => hold?.bbox)
    .filter(box => Array.isArray(box) && box.length >= 4 && box.slice(0, 4).every(Number.isFinite))
  let left = 0, top = 0, right = 1, bottom = 1
  if (boxes.length) {
    left = Math.min(...boxes.map(box => Number(box[0])))
    top = Math.min(...boxes.map(box => Number(box[1])))
    right = Math.max(...boxes.map(box => Number(box[0]) + Number(box[2])))
    bottom = Math.max(...boxes.map(box => Number(box[1]) + Number(box[3])))
    const routeWidth = Math.max(.02, right - left)
    const routeHeight = Math.max(.02, bottom - top)
    left = Math.max(0, left - routeWidth * .1)
    right = Math.min(1, right + routeWidth * .1)
    top = Math.max(0, top - routeHeight * .1)
    bottom = Math.min(1, bottom + routeHeight * .1)
  }
  const mapped = segments.map(run => run.map(point => ({
    x: point.xy[0] * width,
    y: point.xy[1] * height,
  })))
  const viewBox = [left * width, top * height, Math.max(1, (right - left) * width), Math.max(1, (bottom - top) * height)]
  return {
    paths: mapped.map(run => run.map(point => `${point.x},${point.y}`).join(' ')),
    start: mapped[0][0], end: mapped.at(-1).at(-1), viewBox,
  }
}

export function horizontalShiftLabel(metrics) {
  const value = metrics?.net_horizontal_percent
  if (!Number.isFinite(value)) return '左右偏移暂不能比较'
  if (value === 0) return '首末观测在同一列'
  return `首末净横移：向${value > 0 ? '右' : '左'} ${Math.abs(value).toFixed(1)}%`
}
