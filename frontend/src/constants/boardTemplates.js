const DEFAULT_HOLE_SPACING_MM = 200

const LEGACY_TEMPLATE_ALIASES = {
  'studio-13x21': 'studio-14x20',
  'commercial-15x24': 'commercial-16x24',
  'competition-17x28': 'competition-18x22',
}

function buildBoardTemplate({
  id,
  template_key,
  label,
  columns,
  rows,
  angle_degrees,
  material,
  skinClass,
  description,
  reference_system = 'system-spray-wall',
  board_width_mm,
  board_height_mm,
  margin_left_mm = 220,
  margin_right_mm = 220,
  margin_bottom_mm = 130,
  margin_top_mm = 130,
  hole_spacing_x_mm = DEFAULT_HOLE_SPACING_MM,
  hole_spacing_y_mm = DEFAULT_HOLE_SPACING_MM,
}) {
  const grid_width_mm = (columns - 1) * hole_spacing_x_mm
  const grid_height_mm = (rows - 1) * hole_spacing_y_mm
  const resolved_width_mm = board_width_mm || grid_width_mm + margin_left_mm + margin_right_mm
  const resolved_height_mm = board_height_mm || grid_height_mm + margin_bottom_mm + margin_top_mm
  const total_holes = columns * rows
  const cellLabel = `${columns} x ${rows}`
  const angleLabel = `${angle_degrees} deg`
  const physicalLabel = `${resolved_width_mm} x ${resolved_height_mm} mm`
  const spacingLabel = `${hole_spacing_x_mm} x ${hole_spacing_y_mm} mm`

  return {
    id,
    template_key,
    label,
    name: label,
    columns,
    cols: columns,
    rows,
    hole_spacing_x_mm,
    hole_spacing_y_mm,
    board_width_mm: resolved_width_mm,
    board_height_mm: resolved_height_mm,
    grid_width_mm,
    grid_height_mm,
    margin_left_mm,
    margin_right_mm,
    margin_bottom_mm,
    margin_top_mm,
    angle_degrees,
    total_holes,
    unit: 'mm',
    reference_system,
    cellLabel,
    angleLabel,
    physicalLabel,
    spacingLabel,
    material,
    skinClass,
    description,
    // Legacy visual consumers still read width/height. Keep them derived from real millimeters.
    width: resolved_width_mm,
    height: resolved_height_mm,
  }
}

export const BOARD_TEMPLATES = [
  buildBoardTemplate({
    id: 'classic-11x18',
    template_key: 'spray-small',
    label: 'MoonBoard 风格标准板',
    columns: 11,
    rows: 18,
    board_width_mm: 2440,
    board_height_mm: 3660,
    angle_degrees: 40,
    reference_system: 'moonboard-derived',
    material: '深色木纹复合板',
    skinClass: 'skin-wood-classic',
    description: '以 200mm 孔距和 11 x 18 坐标作为 AI 生成默认规格，兼容现有路线算法。',
  }),
  buildBoardTemplate({
    id: 'studio-14x20',
    template_key: 'spray-medium',
    label: 'Studio 扩展喷点板',
    columns: 14,
    rows: 20,
    angle_degrees: 10,
    material: '桦木纹理 + 密集孔位',
    skinClass: 'skin-birch-studio',
    description: '系统扩展规格，适合中等规模手动布点和自由组合岩点。',
  }),
  buildBoardTemplate({
    id: 'commercial-16x24',
    template_key: 'spray-large',
    label: 'Commercial 大型喷点板',
    columns: 16,
    rows: 24,
    angle_degrees: 15,
    material: '灰黑防滑板面',
    skinClass: 'skin-commercial-dark',
    description: '系统扩展规格，提供更多横向移动空间和更高的路线容量。',
  }),
  buildBoardTemplate({
    id: 'competition-18x22',
    template_key: 'competition-wide',
    label: 'Competition 宽体训练板',
    columns: 18,
    rows: 22,
    angle_degrees: 20,
    material: '蓝灰竞赛板面',
    skinClass: 'skin-competition-blue',
    description: '系统扩展规格，适合大跨度横移、协调动作和复杂组合模拟。',
  }),
]

export const DEFAULT_BOARD_TEMPLATE_ID = 'studio-14x20'
export const LEGACY_BOARD_TEMPLATE_ID = 'classic-11x18'

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

function completePhysicalSpec(spec, template, columns, rows) {
  const hole_spacing_x_mm = Number(spec?.hole_spacing_x_mm || template.hole_spacing_x_mm || DEFAULT_HOLE_SPACING_MM)
  const hole_spacing_y_mm = Number(spec?.hole_spacing_y_mm || template.hole_spacing_y_mm || DEFAULT_HOLE_SPACING_MM)
  const grid_width_mm = Number(spec?.grid_width_mm || (columns - 1) * hole_spacing_x_mm)
  const grid_height_mm = Number(spec?.grid_height_mm || (rows - 1) * hole_spacing_y_mm)
  const margin_left_mm = Number(spec?.margin_left_mm ?? template.margin_left_mm)
  const margin_right_mm = Number(spec?.margin_right_mm ?? template.margin_right_mm)
  const margin_bottom_mm = Number(spec?.margin_bottom_mm ?? template.margin_bottom_mm)
  const margin_top_mm = Number(spec?.margin_top_mm ?? template.margin_top_mm)
  const legacy_width_mm = Number(spec?.width || 0) > 1000 ? Number(spec.width) : 0
  const legacy_height_mm = Number(spec?.height || 0) > 1000 ? Number(spec.height) : 0
  const board_width_mm = Number(spec?.board_width_mm || template.board_width_mm || legacy_width_mm || grid_width_mm + margin_left_mm + margin_right_mm)
  const board_height_mm = Number(spec?.board_height_mm || template.board_height_mm || legacy_height_mm || grid_height_mm + margin_bottom_mm + margin_top_mm)
  const angle_degrees = Number(spec?.angle_degrees ?? template.angle_degrees)

  return {
    hole_spacing_x_mm,
    hole_spacing_y_mm,
    board_width_mm,
    board_height_mm,
    grid_width_mm,
    grid_height_mm,
    margin_left_mm,
    margin_right_mm,
    margin_bottom_mm,
    margin_top_mm,
    angle_degrees,
    total_holes: columns * rows,
    unit: spec?.unit || template.unit || 'mm',
    reference_system: spec?.reference_system || template.reference_system,
    physicalLabel: `${board_width_mm} x ${board_height_mm} mm`,
    spacingLabel: `${hole_spacing_x_mm} x ${hole_spacing_y_mm} mm`,
    angleLabel: `${angle_degrees} deg`,
    width: board_width_mm,
    height: board_height_mm,
  }
}

export function createBoardSpecSnapshot(template = getBoardTemplateById(DEFAULT_BOARD_TEMPLATE_ID)) {
  const normalizedTemplate = getBoardTemplateById(template?.id || template?.template_key || DEFAULT_BOARD_TEMPLATE_ID)
  const columns = Number(template?.columns || template?.cols || normalizedTemplate.columns)
  const rows = Number(template?.rows || normalizedTemplate.rows)
  const physicalSpec = completePhysicalSpec(template, normalizedTemplate, columns, rows)

  return {
    ...physicalSpec,
    preset_id: normalizedTemplate.id,
    template_key: normalizedTemplate.template_key,
    label: template?.label || template?.name || normalizedTemplate.label,
    name: template?.name || template?.label || normalizedTemplate.name,
    columns,
    cols: columns,
    rows,
    cellLabel: template?.cellLabel || `${columns} x ${rows}`,
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
  const physicalSpec = completePhysicalSpec(spec, template, columns, rows)

  return {
    ...createBoardSpecSnapshot(template),
    ...spec,
    ...physicalSpec,
    preset_id: template.id,
    template_key: template.template_key,
    columns,
    cols: columns,
    rows,
    cellLabel: spec.cellLabel || `${columns} x ${rows}`,
    xLabels: Array.isArray(spec.xLabels) && spec.xLabels.length ? spec.xLabels : createAxisLabels(columns),
    yLabels: Array.isArray(spec.yLabels) && spec.yLabels.length ? spec.yLabels : Array.from({ length: rows }, (_, index) => index + 1),
  }
}
