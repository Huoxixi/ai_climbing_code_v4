const regions = [
  ['左上区域', '上方中央', '右上区域'],
  ['左侧中部', '中央区域', '右侧中部'],
  ['左下区域', '下方中央', '右下区域'],
]

function centroid(contour = []) {
  if (!contour.length) return [0.5, 0.5]
  const total = contour.reduce((sum, point) => [sum[0] + Number(point[0] || 0), sum[1] + Number(point[1] || 0)], [0, 0])
  return [total[0] / contour.length, total[1] / contour.length]
}

export function photoObjectPosition(object, board) {
  const [x, y] = centroid(object?.contour)
  const width = Math.max(Number(board?.width || 1), 1)
  const height = Math.max(Number(board?.height || 1), 1)
  const column = Math.min(2, Math.max(0, Math.floor((x / width) * 3)))
  const row = Math.min(2, Math.max(0, Math.floor((y / height) * 3)))
  return regions[row][column]
}

export function photoObjectLabel(object, board, { member = false, action = 'select' } = {}) {
  const color = object?.color_group && object.color_group !== '待确认' ? `${object.color_group}岩点` : '岩点'
  const position = photoObjectPosition(object, board)
  if (action === 'view') return `${color}，照片${position}`
  return `${color}，照片${position}，${member ? '已在线路中' : '可加入线路'}`
}
