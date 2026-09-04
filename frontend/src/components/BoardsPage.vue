<template>
  <section class="page">
    <div class="page-header">
      <div>
        <p class="eyebrow">本地线路资产</p>
        <h2>岩板资产</h2>
      </div>
      <div class="command-row">
        <el-button :icon="Refresh" :loading="boards.loading" @click="boards.fetchMyBoards">刷新</el-button>
        <el-button type="primary" :icon="Plus" @click="$emit('new-board')">新建岩板</el-button>
      </div>
    </div>
    <el-segmented
      v-model="assetMode"
      class="board-mode-switch"
      :options="[{ label: '资产列表', value: 'list' }, { label: '岩板对照', value: 'compare' }]"
    />

    <template v-if="assetMode === 'list'">
      <el-segmented
        v-model="boardView"
        :options="[
          { label: `已启用 ${boards.savedBoards.length}`, value: 'active' },
          { label: `归档箱 ${boards.archivedBoards.length}`, value: 'archived' },
        ]"
      />
      <section class="section-block board-tag-filter-panel">
        <div class="section-heading">
          <div>
            <h3>按标签筛选</h3>
            <span>已匹配 {{ filteredSavedBoards.length }} / {{ visibleSavedBoards.length }} 个岩板资产</span>
          </div>
          <el-button text :disabled="!savedBoardFilters.tagIds.length" @click="$emit('clear-tags')">清除标签</el-button>
        </div>
        <div class="tag-filter-controls">
          <el-select v-model="savedBoardFilters.tagIds" multiple clearable collapse-tags collapse-tags-tooltip placeholder="选择标签">
            <el-option-group v-for="group in savedBoardTagGroups" :key="group.key" :label="group.label">
              <el-option v-for="tag in group.tags" :key="tag.id" :label="tag.label" :value="tag.id" />
            </el-option-group>
          </el-select>
          <el-segmented
            v-model="savedBoardFilters.match"
            :options="[{ label: '全部满足', value: 'all' }, { label: '满足任一', value: 'any' }]"
          />
        </div>
      </section>
      <div class="board-assets">
        <article v-for="board in filteredSavedBoards" :key="board.saved_id || board.route_name" class="board-card">
          <div>
            <strong>{{ board.route_name || '未命名岩板' }}</strong>
            <span>{{ boardSpecDisplayLabel(board) }} / {{ board.placed_holds?.length || 0 }} 岩点 / {{ board.beta_sequence?.length || 0 }} Beta</span>
            <div class="board-readiness">
              <span class="state-badge" :class="{ ready: board.workflow_status === 'ready_for_review' }">{{ workflowLabel(board) }}</span>
              <span v-if="board.ai_eligible && !board.archived_at" class="state-badge ready">AI 可用</span>
              <span v-else-if="!board.archived_at" class="state-badge">AI 不可用</span>
            </div>
            <small v-if="board.readiness_issues?.length" class="readiness-note">{{ board.readiness_issues.slice(0, 2).join('；') }}</small>
            <div class="route-tag-list" aria-label="岩板标签">
              <span v-for="tag in resolvedBoardTags(board)" :key="tag" class="route-tag">{{ tagLabel(tag) }}</span>
            </div>
          </div>
          <div class="card-actions">
            <template v-if="!board.archived_at">
              <el-button :icon="Edit" @click="$emit('load-board', board)">载入编辑</el-button>
              <el-button :icon="EditPen" @click="$emit('rename-board', board)">重命名</el-button>
              <el-button type="danger" plain :icon="Delete" @click="$emit('archive-board', board)">归档</el-button>
            </template>
            <el-button v-else type="primary" plain @click="$emit('restore-board', board)">恢复岩板</el-button>
          </div>
        </article>
        <div v-if="!visibleSavedBoards.length" class="empty-state">
          <strong>{{ boardView === 'archived' ? '归档箱为空' : '暂无保存的岩板资产' }}</strong>
          <span>{{ boardView === 'archived' ? '归档资产可以在这里恢复。' : '完成保存后会在这里显示。' }}</span>
        </div>
        <div v-else-if="!filteredSavedBoards.length" class="empty-state">
          <strong>没有匹配的岩板资产</strong>
          <span>清除或调整标签条件后再试。</span>
        </div>
      </div>
    </template>

    <template v-else>
      <section class="section-block board-compare-picker">
        <div class="section-heading">
          <div>
            <h3>选择 2–4 块已启用岩板</h3>
            <span>第一块自动作为基准；对照仅在当前页面保留，不会修改或保存岩板。</span>
          </div>
          <el-button text :disabled="!comparisonIds.length" @click="$emit('clear-comparison')">清空对照</el-button>
        </div>
        <el-checkbox-group v-model="comparisonIds" :max="4" class="board-compare-options">
          <el-checkbox
            v-for="board in boards.savedBoards"
            :key="board.saved_id"
            :value="board.saved_id"
            border
          >
            {{ board.route_name || '未命名岩板' }} · {{ board.board_spec?.cellLabel || `${board.board_spec?.columns || board.board_spec?.cols || 11} × ${board.board_spec?.rows || 18}` }}
          </el-checkbox>
        </el-checkbox-group>
        <p v-if="boards.savedBoards.length < 2" class="control-help">至少需要两块已启用岩板。归档岩板恢复后才可加入对照。</p>
        <p v-else-if="comparisonIds.length < 2" class="control-help">还需选择 {{ 2 - comparisonIds.length }} 块岩板才能开始对照。</p>
      </section>

      <div v-if="comparedBoards.length >= 2" :class="['board-comparison-grid', `count-${comparedBoards.length}`]">
        <BoardComparisonPanel
          v-for="(board, index) in comparedBoards"
          :key="board.saved_id"
          :board="board"
          :reference="index === 0 ? null : comparedBoards[0]"
          :label="index === 0 ? '基准岩板' : `对照岩板 ${index}`"
          :baseline="index === 0"
          :can-set-baseline="index > 0"
          removable
          :resolve-hold-visual="library.resolveHoldVisual"
          @set-baseline="$emit('set-baseline', board.saved_id)"
          @remove="$emit('remove-compared', board.saved_id)"
        />
      </div>
    </template>
  </section>
</template>

<script setup>
import { computed } from 'vue'
import { Delete, Edit, EditPen, Plus, Refresh } from '@element-plus/icons-vue'
import BoardComparisonPanel from './BoardComparisonPanel.vue'

const props = defineProps({
  boards: { type: Object, required: true },
  library: { type: Object, required: true },
  boardAssetMode: { type: String, required: true },
  savedBoardView: { type: String, required: true },
  compareBoardIds: { type: Array, default: () => [] },
  savedBoardFilters: { type: Object, required: true },
  savedBoardTagGroups: { type: Array, default: () => [] },
  visibleSavedBoards: { type: Array, default: () => [] },
  filteredSavedBoards: { type: Array, default: () => [] },
  comparedBoards: { type: Array, default: () => [] },
  boardSpecDisplayLabel: { type: Function, required: true },
  workflowLabel: { type: Function, required: true },
  resolvedBoardTags: { type: Function, required: true },
  tagLabel: { type: Function, required: true },
})

const emit = defineEmits([
  'update:boardAssetMode', 'update:savedBoardView', 'update:compareBoardIds',
  'new-board', 'clear-tags', 'load-board', 'rename-board', 'archive-board', 'restore-board',
  'clear-comparison', 'set-baseline', 'remove-compared',
])

const assetMode = computed({ get: () => props.boardAssetMode, set: (value) => emit('update:boardAssetMode', value) })
const boardView = computed({ get: () => props.savedBoardView, set: (value) => emit('update:savedBoardView', value) })
const comparisonIds = computed({ get: () => props.compareBoardIds, set: (value) => emit('update:compareBoardIds', value) })
</script>
