// Resolve overlaps geometrically instead of letting SVG drawing order choose.
export function pickPhotoObject(objects, point, tolerance = 0) {
  const [x, y] = point
  const hits = objects.map(object => {
    const polygon = object.contour
    let inside = false, distance = Infinity, area = 0
    for (let i = 0, j = polygon.length - 1; i < polygon.length; j = i++) {
      const [ax, ay] = polygon[j], [bx, by] = polygon[i]
      if ((ay > y) !== (by > y) && x < (bx - ax) * (y - ay) / (by - ay) + ax) inside = !inside
      const dx = bx - ax, dy = by - ay, length = dx * dx + dy * dy
      const t = length ? Math.max(0, Math.min(1, ((x - ax) * dx + (y - ay) * dy) / length)) : 0
      distance = Math.min(distance, Math.hypot(x - ax - t * dx, y - ay - t * dy))
      area += ax * by - bx * ay
    }
    return { object, inside: inside || distance < 1e-7, distance, area: Math.abs(area) / 2 }
  }).filter(hit => hit.inside || hit.distance <= tolerance)
  hits.sort((a, b) => Number(b.inside) - Number(a.inside) ||
    (a.inside ? a.area - b.area : a.distance - b.distance) || a.object.id.localeCompare(b.object.id))
  return hits[0]?.object || null
}
