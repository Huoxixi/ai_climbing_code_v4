export const clamp = value => Math.max(0, Math.min(1, value))
export function imagePoint(clientX, clientY, bounds) {
  return [clamp((clientX - bounds.left) / bounds.width), clamp((clientY - bounds.top) / bounds.height)]
}

// Trace the pixel boundary, including concavities. Reject disconnected pieces and
// enclosed holes rather than silently dropping part of a user's drawing.
export function contourFromBinary(pixels, width, height) {
  const edges = new Map()
  const key = (x, y) => y * (width + 1) + x
  const filled = (x, y) => x >= 0 && y >= 0 && x < width && y < height && pixels[y * width + x]
  const add = (x, y, nx, ny) => {
    const k = key(x, y)
    if (edges.has(k)) throw new Error('轮廓在角点相交，请稍微补画连接处或撤销这一步。')
    edges.set(k, key(nx, ny))
  }
  for (let y = 0; y < height; y++) for (let x = 0; x < width; x++) if (filled(x, y)) {
    if (!filled(x, y - 1)) add(x, y, x + 1, y)
    if (!filled(x + 1, y)) add(x + 1, y, x + 1, y + 1)
    if (!filled(x, y + 1)) add(x + 1, y + 1, x, y + 1)
    if (!filled(x - 1, y)) add(x, y + 1, x, y)
  }
  if (edges.size < 4) throw new Error('轮廓已擦空，请撤销或重新描边。')
  const first = edges.keys().next().value, points = []
  let current = first
  do {
    points.push([current % (width + 1), Math.floor(current / (width + 1))])
    const next = edges.get(current)
    edges.delete(current)
    if (next === undefined) throw new Error('轮廓不闭合，请撤销后重新描边。')
    current = next
  } while (current !== first)
  if (edges.size) throw new Error('请保留一个连续岩点，擦除时从边缘修剪，避免产生孤立区域或内部孔洞。')
  const corners = points.filter((p, i) => {
    const a = points[(i + points.length - 1) % points.length], b = points[(i + 1) % points.length]
    return (p[0] - a[0]) * (b[1] - p[1]) !== (p[1] - a[1]) * (b[0] - p[0])
  })
  return corners.map(p => [p[0] / width, p[1] / height])
}

export function simplifyContour(points, tolerance = .0004) {
  if (points.length <= 3) return points
  const distance = (p, a, b) => {
    const dx = b[0] - a[0], dy = b[1] - a[1], t = dx || dy ? clamp(((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / (dx * dx + dy * dy)) : 0
    return Math.hypot(p[0] - a[0] - t * dx, p[1] - a[1] - t * dy)
  }
  const reduce = line => {
    let max = tolerance, index = 0
    for (let i = 1; i < line.length - 1; i++) {
      const d = distance(line[i], line[0], line.at(-1))
      if (d > max) { max = d; index = i }
    }
    return index ? [...reduce(line.slice(0, index + 1)).slice(0, -1), ...reduce(line.slice(index))] : [line[0], line.at(-1)]
  }
  const half = Math.floor(points.length / 2)
  return [...reduce(points.slice(0, half + 1)).slice(0, -1), ...reduce([...points.slice(half), points[0]]).slice(0, -1)]
}
