<template>
  <section class="page dashboard-page">
    <header class="dashboard-intro">
      <div>
        <h2>工作台总览</h2>
        <p>从当前岩板继续，或从岩点样品与模板开始一条新线路。</p>
      </div>
      <el-button :icon="Plus" @click="$emit('new-board')">新建岩板</el-button>
    </header>
    <section class="specimen-shelf" aria-labelledby="specimen-title">
      <div class="specimen-heading"><div><h3 id="specimen-title">岩点样品架 <small>{{ library.managedHolds.length }} 个岩点</small></h3></div><el-button text @click="$emit('navigate', 'library')">查看全部</el-button></div>
      <div class="specimen-track">
        <button v-for="hold in library.managedHolds.slice(0, 8)" :key="hold.key" type="button" class="specimen-item" @click="$emit('navigate', 'library')">
          <HoldPreview :hold="hold" mode="image" /><strong><i :style="{ background: holdColor(hold.hold_type) }" />{{ hold.hold_type }}</strong><small>{{ hold.hold_type }} {{ hold.variant }}</small>
        </button>
        <div v-if="!library.managedHolds.length" class="specimen-empty">岩点加载后将在这里形成你的样品架。</div>
      </div>
    </section>
    <div class="dashboard-workarea">
      <section class="current-board-panel">
        <div class="section-heading"><div><h3>当前岩板</h3><p>{{ studio.currentBoardSpec.label }} · {{ studio.currentBoardSpec.angleLabel }} · {{ studio.currentBoardSpec.spacingLabel }}</p></div><div class="current-board-actions"><span class="state-badge">{{ studio.unsavedChanges ? '设计中' : '已同步' }}</span></div></div>
        <div class="current-board-stage">
          <BoardThumbnail :label="studio.currentBoardSpec.cellLabel" :columns="studio.coordinateColumns" :rows="studio.coordinateRows" :holds="studio.placedHolds" :frame-style="studio.boardFrameStyle" :get-coord-style="studio.getCoordStyle" :resolve-hold-visual="library.resolveHoldVisual" />
          <div class="board-stage-copy">
            <div><strong>{{ studio.placedHolds.length }}</strong><span>个岩点</span></div>
            <div><strong>{{ studio.routeSteps.length }}</strong><span>个 Beta</span></div>
            <div><strong>{{ studio.currentBoard.difficulty || '待定' }}</strong><span>预计难度</span></div>
            <el-button type="primary" @click="$emit('navigate', 'studio')">继续定线</el-button>
          </div>
        </div>
      </section>
      <aside class="dashboard-side-stack">
        <section class="recent-panel">
          <div class="section-heading"><h3>最近编辑</h3><el-button text @click="$emit('navigate', 'boards')">查看全部</el-button></div>
          <div v-if="!boards.savedBoards.length" class="empty-state"><strong>还没有保存的岩板</strong><span>完成第一次保存后会出现在这里。</span></div>
          <button v-for="(board, index) in boards.savedBoards.slice(0, 4)" :key="board.saved_id || board.route_name" type="button" class="recent-board-row" @click="$emit('load-board', board)">
            <span class="recent-board-index">{{ String(index + 1).padStart(2, '0') }}</span><span><strong>{{ board.route_name || '未命名岩板' }}</strong><small>{{ board.placed_holds?.length || 0 }} 岩点 · {{ board.beta_sequence?.length || 0 }} Beta</small></span><em>{{ workflowLabel(board) }}</em>
          </button>
        </section>
        <BoardTemplatePicker :model-value="selectedTemplateId" :templates="studio.boardPresets" @update:model-value="$emit('update:selectedTemplateId', $event)" @confirm="$emit('create-from-template', $event)" />
      </aside>
    </div>
    <footer class="dashboard-status-strip">
      <span><strong>{{ studio.placedHolds.length }}</strong> 当前岩点</span><span><strong>{{ studio.routeSteps.length }}</strong> Beta 动作</span><span><strong>{{ boards.savedBoards.length }}</strong> 岩板资产</span><span><strong>{{ library.managedHolds.length }}</strong> 岩点资产</span>
      <button type="button" @click="$emit('navigate', 'ai-lab')">AI 实验室 <Histogram /></button>
    </footer>
  </section>
</template>

<script setup>
import { Histogram, Plus } from '@element-plus/icons-vue'
import BoardTemplatePicker from './BoardTemplatePicker.vue'
import BoardThumbnail from './BoardThumbnail.vue'
import HoldPreview from './HoldPreview.vue'
defineProps({ studio: { type: Object, required: true }, boards: { type: Object, required: true }, library: { type: Object, required: true }, selectedTemplateId: { type: String, required: true }, simulationEnabled: { type: Boolean, default: false }, workflowLabel: { type: Function, required: true } })
defineEmits(['navigate', 'new-board', 'create-from-template', 'load-board', 'update:selectedTemplateId'])

function holdColor(type) {
  return { Jug: '#1d7b9c', Crimp: '#58a56a', Sloper: '#d59032', Pinch: '#7457d8', Pocket: '#2f72c8', Foot: '#f4c430' }[type] || '#696c72'
}
</script>
