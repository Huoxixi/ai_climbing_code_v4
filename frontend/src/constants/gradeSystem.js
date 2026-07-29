export const FONT_GRADES = Object.freeze([
  '6B', '6B+', '6C', '6C+', '7A', '7A+', '7B',
  '7B+', '7C', '7C+', '8A', '8A+', '8B', '8B+',
])

export const DEFAULT_FONT_GRADE = '6B+'
export const UNGRADED = '未定级'

export function fontGradeTag(grade) {
  const normalized = String(grade || '').trim().toUpperCase()
  return FONT_GRADES.includes(normalized)
    ? `difficulty:${normalized.toLowerCase().replace('+', '-plus')}`
    : 'difficulty:ungraded'
}

export function confidenceLabel(value) {
  return { high: '高可信', medium: '中可信', low: '低可信' }[value] || '低可信'
}

export function calibrationLabel(value) {
  return {
    ready: '已校准',
    calibrating: '试算／校准中',
    uncalibrated: '未校准',
  }[value] || '未校准'
}
