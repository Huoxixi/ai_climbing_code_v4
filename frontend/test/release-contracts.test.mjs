import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

import {
  BOARD_TEMPLATES,
  DEFAULT_BOARD_TEMPLATE_ID,
  getBoardTemplateById,
  normalizeBoardSpec,
} from '../src/constants/boardTemplates.js'
import { DEFAULT_FONT_GRADE, FONT_GRADES } from '../src/constants/gradeSystem.js'

const surfaceFiles = [
  '../src/App.vue',
  '../src/components/DashboardPage.vue',
  '../src/components/StudioPage.vue',
  '../src/components/HoldLibraryPage.vue',
  '../src/components/BoardsPage.vue',
  '../src/components/StandardBoardPage.vue',
  '../src/components/AILabPage.vue',
]

async function readAppSurface() {
  return (await Promise.all(surfaceFiles.map((path) => readFile(new URL(path, import.meta.url), 'utf8')))).join('\n')
}

test('公开评级只使用完整的 MoonBoard Font 等级序列', async () => {
  assert.deepEqual(FONT_GRADES, [
    '6B', '6B+', '6C', '6C+', '7A', '7A+', '7B',
    '7B+', '7C', '7C+', '8A', '8A+', '8B', '8B+',
  ])
  assert.equal(DEFAULT_FONT_GRADE, '6B+')
  const appSource = await readAppSurface()
  const serviceSource = await readFile(new URL('../src/services/standardBoardService.js', import.meta.url), 'utf8')
  assert.doesNotMatch(appSource + serviceSource, /predicted_v_grade|target_v_grade|\bv_grade\b/)
  assert.match(appSource, /MoonBoard 原始等级/)
  assert.match(appSource, /MoonBoard 等效难度/)
})

test('11×18 是默认模板且只有它支持 AI', () => {
  const defaultTemplate = getBoardTemplateById(DEFAULT_BOARD_TEMPLATE_ID)
  assert.equal(defaultTemplate.columns, 11)
  assert.equal(defaultTemplate.rows, 18)
  assert.equal(defaultTemplate.ai_supported, true)

  const manualOnly = BOARD_TEMPLATES.filter((template) => !template.ai_supported)
  assert.deepEqual(
    manualOnly.map((template) => `${template.columns}x${template.rows}`),
    ['14x20', '16x24', '18x22'],
  )
})

test('当前岩板模板不再宣称未经确认的材质或商业型号', () => {
  assert.deepEqual(
    BOARD_TEMPLATES.map((template) => template.label),
    ['11×18 标准训练板', '14×20 扩展训练板', '16×24 大型训练板', '18×22 宽体训练板'],
  )
  for (const template of BOARD_TEMPLATES) {
    assert.equal(template.material, null)
    assert.equal(template.skinClass, null)
    assert.match(template.angleLabel, /°$/)
  }
})

test('旧岩板规格名称在兼容读取时归一为当前中文模板名', () => {
  const normalized = normalizeBoardSpec({
    preset_id: 'classic-11x18',
    template_key: 'spray-small',
    label: 'Standard training board 11x18',
    name: 'Standard training board 11x18',
    columns: 11,
    rows: 18,
  })
  assert.equal(normalized.label, '11×18 标准训练板')
  assert.equal(normalized.name, '11×18 标准训练板')
})

test('客户界面不再宣传账号体系或自由文本 AI 要求', async () => {
  const appSource = await readAppSurface()
  assert.doesNotMatch(appSource, /登录|注册|邮箱验证|user_requirements|currentUser|useAuth/)
  assert.match(appSource, /generation_goal/)
  assert.match(appSource, /review_focus/)
})

test('客户界面不显示旧材质和过时工作区名称', async () => {
  const appSource = await readAppSurface()
  assert.doesNotMatch(appSource, /深色木纹|桦木纹理|灰黑防滑|蓝灰竞赛|wood composite/)
  assert.doesNotMatch(appSource, />AI Lab<|>Studio</)
  assert.doesNotMatch(appSource, />Routes<|>Selected Route<|>Difficulty<|>Training Log<|>Repair Queue<|>Repair Candidate</)
  assert.match(appSource, /AI 实验室/)
  assert.match(appSource, /定线工作台/)
})

test('AI 实验室把风险、润色状态和解释证据显示为通俗中文', async () => {
  const appSource = await readAppSurface()
  const explanationSource = await readFile(new URL('../src/components/AIExperimentExplanation.vue', import.meta.url), 'utf8')
  assert.match(appSource, /riskAssessmentLabel\(routeGen\.result\)/)
  assert.match(appSource, /风险未完整评估/)
  assert.match(appSource, /结构与动作风险/)
  assert.match(appSource, /AI 已用中文润色/)
  assert.match(appSource, /本地中文结果/)
  assert.match(appSource, /AIExperimentExplanation/)
  assert.match(explanationSource, /本次结果如何得出/)
  assert.match(explanationSource, /规则检查清单/)
  assert.match(explanationSource, /候选选择过程/)
  assert.match(explanationSource, /通过.*需关注.*未通过.*未检查/s)
  assert.doesNotMatch(appSource, /风险\{\{ routeGen\.result\.risk_level \}\}/)
})

test('AI 实验室首屏收敛，量化证据默认折叠且不展示内部动作', async () => {
  const appSource = await readAppSurface()
  const comparisonSource = await readFile(new URL('../src/components/BoardComparisonPanel.vue', import.meta.url), 'utf8')

  assert.match(appSource, /辅助定线，不替代试爬/)
  assert.match(appSource, /查看分析依据/)
  assert.match(appSource, /最佳新岩板/)
  assert.match(appSource, /:show-beta="false"/)
  assert.match(appSource, /:show-movement-count="false"/)
  assert.match(appSource, /本次观测/)
  assert.match(appSource, /判定阈值/)
  assert.match(appSource, /预计改善/)
  assert.match(appSource, /原线路 Beta 步骤/)
  assert.match(appSource, /审核对象/)
  assert.match(comparisonSource, /重组依据/)
  assert.match(comparisonSource, /原线路/)
  assert.match(comparisonSource, /候选草案/)
  assert.match(comparisonSource, /v-if="showBeta"/)
  assert.match(comparisonSource, /:show-beta-steps="showBeta"/)
})

test('总览不再展示固定客户推荐，标准线路库入口仍然保留', async () => {
  const appSource = await readAppSurface()
  const removedHeading = ['客户演示', '推荐'].join('')
  const removedStateName = ['recommended', 'Routes'].join('')
  const removedActionName = ['open', 'Recommended', 'Route'].join('')
  assert.equal(appSource.includes(removedHeading), false)
  assert.equal(appSource.includes(removedStateName), false)
  assert.equal(appSource.includes(removedActionName), false)
  assert.match(appSource, /标准线路库/)
  assert.match(appSource, /standard-board/)
})

test('试运行构建通过环境开关隐藏仿真入口', async () => {
  const appSource = await readAppSurface()
  const shellSource = await readFile(new URL('../src/components/AppShell.vue', import.meta.url), 'utf8')

  assert.match(appSource, /VITE_ENABLE_SIMULATION/)
  assert.match(appSource, /v-if="simulationEnabled"/)
  assert.match(appSource, /simulationEnabled && activePage === 'simulation'/)
  assert.match(shellSource, /item\.key !== 'simulation' \|\| props\.simulationEnabled/)
})
