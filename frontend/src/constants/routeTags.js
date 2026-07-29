import { FONT_GRADES, fontGradeTag } from './gradeSystem'

const difficultyTags = FONT_GRADES.map((grade) => ({
  id: fontGradeTag(grade),
  label: grade,
}))

export const ROUTE_TAG_GROUPS = [
  { key: 'difficulty', label: '难度', tags: [...difficultyTags, { id: 'difficulty:ungraded', label: '未定级' }] },
  {
    key: 'quality',
    label: '质量',
    tags: [
      { id: 'quality:excellent', label: '优秀' },
      { id: 'quality:good', label: '良好' },
      { id: 'quality:climbable', label: '可攀' },
      { id: 'quality:review', label: '需复核' },
    ],
  },
  {
    key: 'style',
    label: '动作特征',
    tags: [
      { id: 'style:big-span', label: '大跨度' },
      { id: 'style:small-hold-strength', label: '小点力量' },
      { id: 'style:technical-footwork', label: '技术脚法' },
      { id: 'style:sustained', label: '持续挑战' },
      { id: 'style:crux-start-finish', label: '起终关键' },
    ],
  },
  {
    key: 'trust',
    label: '可信度',
    tags: [
      { id: 'trust:benchmark', label: '标杆线' },
      { id: 'trust:needs-review', label: '难度待复核' },
    ],
  },
  {
    key: 'source',
    label: '来源',
    tags: [
      { id: 'source:manual', label: '手动定线' },
      { id: 'source:ai-generated', label: 'AI 生成' },
      { id: 'source:imported', label: '导入线路' },
    ],
  },
]

export const MANUAL_BOARD_TAG_IDS = ROUTE_TAG_GROUPS.find((group) => group.key === 'style').tags.map((tag) => tag.id)

const knownTags = ROUTE_TAG_GROUPS.flatMap((group) => group.tags)
export const ROUTE_TAG_LABELS = Object.fromEntries(knownTags.map((tag) => [tag.id, tag.label]))

export function tagLabel(tagId) {
  return ROUTE_TAG_LABELS[tagId] || tagId
}

export function boardSystemTags(board = {}) {
  const difficultyTag = fontGradeTag(board.difficulty)
  const source = ['manual', 'ai-generated', 'imported'].includes(board.source_type) ? board.source_type : 'manual'
  return [difficultyTag, `source:${source}`]
}

export function boardTags(board = {}) {
  return [...new Set([...boardSystemTags(board), ...(Array.isArray(board.tags) ? board.tags : [])])]
}

export function matchesTags(tags = [], selectedTags = [], mode = 'all') {
  if (!selectedTags.length) return true
  const available = new Set(tags)
  return mode === 'any'
    ? selectedTags.some((tag) => available.has(tag))
    : selectedTags.every((tag) => available.has(tag))
}
