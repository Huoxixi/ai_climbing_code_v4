import { computed, ref } from 'vue'
import { DEFAULT_BOARD_TEMPLATE_ID, createBoardSpecSnapshot, getBoardTemplateById } from '../constants/boardTemplates'

export function createBlankBoard(overrides = {}) {
  const now = new Date().toISOString()
  const template = getBoardTemplateById(
    overrides.board_spec?.preset_id || overrides.board_spec?.template_key || overrides.template_id || DEFAULT_BOARD_TEMPLATE_ID
  )
  const boardSpec = overrides.board_spec || createBoardSpecSnapshot(template)

  return {
    saved_id: null,
    owner_id: null,
    source_type: 'manual',
    visibility: 'private',
    tags: [],
    difficulty: 'V未定',
    created_at: now,
    updated_at: now,
    route_name: `${template.label} · 空白模拟岩板`,
    setter_commentary: `从 ${template.label}（${template.columns}×${template.rows}）开始手动布点；当前版本优先支持岩板模拟设计与资产保存。`,
    board_spec: boardSpec,
    placed_holds: [],
    beta_sequence: [],
    ...overrides,
  }
}

export function useBoardEditor(initialBoard = null) {
  const editorMode = ref(initialBoard?.source_type === 'ai-generated' ? 'generated' : 'manual')
  const boardDraft = ref(initialBoard || createBlankBoard())
  const selectedHold = ref(null)
  const unsavedChanges = ref(false)

  const boardStats = computed(() => ({
    holds: boardDraft.value?.placed_holds?.length || 0,
    moves: boardDraft.value?.beta_sequence?.length || 0,
  }))

  return {
    editorMode,
    boardDraft,
    selectedHold,
    unsavedChanges,
    boardStats,
  }
}