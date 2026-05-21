export const BOARD_TEMPLATES = [
  {
    id: 'classic-11x18',
    template_key: 'spray-small',
    label: '标准训练板',
    name: '标准训练板',
    cellLabel: '11 × 18',
    columns: 11,
    cols: 11,
    rows: 18,
    width: 450,
    height: 650,
    angleLabel: '垂直 / 轻微外倾',
    material: '深色木纹复合板',
    skinClass: 'skin-wood-classic',
    description: '保留原始 11×18 训练规格，适合轻量级手动布点与快速试验。',
  },
  {
    id: 'studio-14x20',
    template_key: 'spray-medium',
    label: '扩展训练板',
    name: '扩展训练板',
    cellLabel: '14 × 20',
    columns: 14,
    cols: 14,
    rows: 20,
    width: 560,
    height: 760,
    angleLabel: '10° 可调外倾',
    material: '桦木纹理 + 密集孔位',
    skinClass: 'skin-birch-studio',
    description: '更宽更高的模拟设计规格，适合中等规模训练线路与自由组合岩点。',
  },
  {
    id: 'commercial-16x24',
    template_key: 'spray-large',
    label: '大型设计板',
    name: '大型设计板',
    cellLabel: '16 × 24',
    columns: 16,
    cols: 16,
    rows: 24,
    width: 680,
    height: 920,
    angleLabel: '15° 训练外倾',
    material: '灰黑防滑板面',
    skinClass: 'skin-commercial-dark',
    description: '面向更多岩点和更复杂路线设计，提供更大的横向移动与动作组合空间。',
  },
  {
    id: 'competition-18x22',
    template_key: 'competition-wide',
    label: '宽体比赛板',
    name: '宽体比赛板',
    cellLabel: '18 × 22',
    columns: 18,
    cols: 18,
    rows: 22,
    width: 820,
    height: 860,
    angleLabel: '20° 动作模拟外倾',
    material: '蓝灰竞赛板面',
    skinClass: 'skin-competition-blue',
    description: '宽体比赛模拟规格，适合大跨度横移、协调动作和复杂组合模拟。',
  },
]

export const DEFAULT_BOARD_TEMPLATE_ID = 'studio-14x20'
export const LEGACY_BOARD_TEMPLATE_ID = 'classic-11x18'

const LEGACY_TEMPLATE_ALIASES = {
  'studio-13x21': 'studio-14x20',
  'commercial-15x24': 'commercial-16x24',
  'competition-17x28': 'competition-18x22',
}

export function getBoardTemplateById(id) {
  const normalizedId = LEGACY_TEMPLATE_ALIASES[id] || id
  return BOARD_TEMPLATES.find((template) => template.id === normalizedId || template.template_key === normalizedId) || BOARD_TEMPLATES[0]
}

export function createAxisLabels(count) {
  return Array.from({ length: count }, (_, index) => {
    let label = ''
    let n = index

    do {
      label = String.fromCharCode(65 + (n % 26)) + label
      n = Math.floor(n / 26) - 1
    } while (n >= 0)

    return label
  })
}

export function createBoardSpecSnapshot(template = getBoardTemplateById(DEFAULT_BOARD_TEMPLATE_ID)) {
  const normalizedTemplate = getBoardTemplateById(template?.id || template?.template_key || DEFAULT_BOARD_TEMPLATE_ID)
  const columns = Number(template?.columns || template?.cols || normalizedTemplate.columns)
  const rows = Number(template?.rows || normalizedTemplate.rows)

  return {
    preset_id: normalizedTemplate.id,
    template_key: normalizedTemplate.template_key,
    label: template?.label || template?.name || normalizedTemplate.label,
    name: template?.name || template?.label || normalizedTemplate.name,
    columns,
    cols: columns,
    rows,
    width: Number(template?.width || normalizedTemplate.width),
    height: Number(template?.height || normalizedTemplate.height),
    cellLabel: template?.cellLabel || `${columns} × ${rows}`,
    angleLabel: template?.angleLabel || normalizedTemplate.angleLabel,
    material: template?.material || normalizedTemplate.material,
    skinClass: template?.skinClass || normalizedTemplate.skinClass,
    description: template?.description || normalizedTemplate.description,
    xLabels: createAxisLabels(columns),
    yLabels: Array.from({ length: rows }, (_, index) => index + 1),
  }
}

export function normalizeBoardSpec(spec) {
  if (!spec) return createBoardSpecSnapshot(getBoardTemplateById(LEGACY_BOARD_TEMPLATE_ID))

  const template = getBoardTemplateById(spec.preset_id || spec.template_key)
  const columns = Number(spec.columns || spec.cols || template.columns)
  const rows = Number(spec.rows || template.rows)

  return {
    ...createBoardSpecSnapshot(template),
    ...spec,
    preset_id: template.id,
    template_key: template.template_key,
    columns,
    cols: columns,
    rows,
    xLabels: Array.isArray(spec.xLabels) && spec.xLabels.length
      ? spec.xLabels
      : createAxisLabels(columns),
    yLabels: Array.isArray(spec.yLabels) && spec.yLabels.length
      ? spec.yLabels
      : Array.from({ length: rows }, (_, index) => index + 1),
  }
}