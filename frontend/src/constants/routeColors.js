export const ROUTE_COLORS = Object.freeze([
  { value: '红色', hex: '#c94747' },
  { value: '橙色', hex: '#dd792c' },
  { value: '黄色', hex: '#e1b91d' },
  { value: '绿色', hex: '#2f8c62' },
  { value: '青色', hex: '#20a6a6' },
  { value: '蓝色', hex: '#3478bc' },
  { value: '紫色', hex: '#8357a7' },
  { value: '粉色', hex: '#d86d91' },
  { value: '棕色', hex: '#8a5a3b' },
  { value: '黑色', hex: '#2b2c2f' },
  { value: '白色', hex: '#eeeae1' },
  { value: '灰色', hex: '#7c858c' },
])

export const ROUTE_COLOR_NAMES = Object.freeze(ROUTE_COLORS.map(({ value }) => value))
export const QUICK_ROUTE_COLORS = Object.freeze(ROUTE_COLORS.filter(({ value }) =>
  value !== '青色' && value !== '棕色'))

const ROUTE_COLOR_HEX = new Map(ROUTE_COLORS.map(({ value, hex }) => [value, hex]))

export function routeColorHex(value, fallback = '#7b7468') {
  return ROUTE_COLOR_HEX.get(value) || fallback
}

export function hexToRgb(hex) {
  const match = /^#([0-9a-f]{6})$/i.exec(String(hex || ''))
  if (!match) return null
  const value = Number.parseInt(match[1], 16)
  return [(value >> 16) & 255, (value >> 8) & 255, value & 255]
}

export function rgbToHex(rgb) {
  return `#${rgb.map((value) => Math.max(0, Math.min(255, Math.round(value))).toString(16).padStart(2, '0')).join('')}`
}

function rgbToLab(rgb) {
  const linear = rgb.map((value) => {
    const channel = value / 255
    return channel <= 0.04045 ? channel / 12.92 : ((channel + 0.055) / 1.055) ** 2.4
  })
  const [r, g, b] = linear
  const xyz = [
    (r * 0.4124564 + g * 0.3575761 + b * 0.1804375) / 0.95047,
    r * 0.2126729 + g * 0.7151522 + b * 0.072175,
    (r * 0.0193339 + g * 0.119192 + b * 0.9503041) / 1.08883,
  ].map((value) => value > 0.008856 ? Math.cbrt(value) : 7.787 * value + 16 / 116)
  return [116 * xyz[1] - 16, 500 * (xyz[0] - xyz[1]), 200 * (xyz[1] - xyz[2])]
}

export function nearestRouteColor(rgb) {
  const sample = rgbToLab(rgb)
  return ROUTE_COLORS.reduce((best, color) => {
    const candidate = rgbToLab(hexToRgb(color.hex))
    const distance = Math.hypot(...candidate.map((value, index) => value - sample[index]))
    return !best || distance < best.distance ? { ...color, distance } : best
  }, null)
}
