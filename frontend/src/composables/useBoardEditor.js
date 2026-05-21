import { computed, ref } from 'vue'

export function createBlankBoard(overrides = {}) {
  const now = new Date().toISOString()
  return {
    saved_id: null,
    owner_id: null,
    source_type: 'manual',
    visibility: 'private',
    tags: [],
    difficulty: 'V未定',
    created_at: now,
    updated_at: now,
    route_name: '空白手动岩板',
    setter_commentary: '从空白岩板开始手动布点；可直接保存，也可后续接入 AI 生成与云端同步。',
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