<template>
  <article class="board-comparison-panel">
    <header class="comparison-panel-heading">
      <div>
        <span class="comparison-kicker">{{ label }}</span>
        <h3>{{ board.route_name || '未命名岩板' }}</h3>
      </div>
      <span v-if="baseline" class="state-badge ready">基准岩板</span>
    </header>

    <div class="comparison-board-meta" aria-label="岩板基本信息">
      <span>{{ view.spec.cellLabel }}</span>
      <span>MoonBoard 等效 {{ board.difficulty || '未定级' }}</span>
      <span>{{ confidenceLabel(board.confidence_tier) }}</span>
      <span>{{ board.placed_holds?.length || 0 }} 个岩点</span>
      <span v-if="showMovementCount">{{ board.beta_sequence?.length || 0 }} 个动作</span>
      <span>{{ workflowLabel }}</span>
    </div>

    <div v-if="comparison?.specMismatch" class="comparison-warning" role="note">
      规格不同：坐标仅按名称比较，不代表两个岩点的物理位置完全一致。
    </div>

    <div class="comparison-canvas">
      <BoardCanvas
        :columns="view.columns"
        :rows="view.rows"
        :holds="displayHolds"
        :route-steps="board.beta_sequence || []"
        :board-spec="view.spec"
        :frame-style="view.frameStyle"
        :get-coord-style="view.getCoordStyle"
        :resolve-hold-visual="resolveHoldVisual"
        :comparison-status-by-id="comparison?.statusById || {}"
        readonly
        :show-beta-steps="showBeta"
      />
    </div>

    <div v-if="showDetails && comparison" class="comparison-legend" aria-label="差异图例">
      <span><i class="legend-dot retained" />保留 {{ comparison.retained.length }}</span>
      <span><i class="legend-dot added" />新增 {{ comparison.added.length }}</span>
      <span><i class="legend-dot removed" />移除 {{ comparison.removed.length }}</span>
      <span><i class="legend-dot changed" />修改 {{ comparison.changed.length }}</span>
    </div>

    <div v-if="showDetails && comparison" class="comparison-summary">
      <strong>变化说明</strong>
      <p>{{ comparison.summary }}</p>
      <p>
        复用率 {{ percent(comparison.reuseRate) }}，
        <span :class="`reuse-tier ${comparison.reuseTier.key}`">{{ comparison.reuseTier.label }}</span>
      </p>
      <dl class="coordinate-diff-list">
        <template v-if="comparison.retained.length">
          <dt>保留</dt><dd>{{ coordinates(comparison.retained) }}</dd>
        </template>
        <template v-if="comparison.added.length">
          <dt>新增</dt><dd>{{ coordinates(comparison.added) }}</dd>
        </template>
        <template v-if="comparison.removed.length">
          <dt>移除</dt><dd>{{ coordinates(comparison.removed) }}</dd>
        </template>
        <template v-if="comparison.changed.length">
          <dt>修改</dt>
          <dd>{{ comparison.changed.map((item) => `${item.id}（${item.labels.join('、')}）`).join('；') }}</dd>
        </template>
      </dl>
    </div>

    <div v-if="showDetails && meta && Object.keys(meta).length" class="candidate-facts" aria-label="候选质量信息">
      <span>结构质量 {{ meta.quality_score ?? '-' }}</span>
      <span>等效难度 {{ meta.predicted_grade || '-' }}</span>
      <span>{{ confidenceLabel(meta.confidence_tier) }} · {{ calibrationLabel(meta.calibration_status) }}</span>
      <span>{{ candidateRiskLabel(meta) }}</span>
    </div>
    <p v-if="showDetails && meta?.why_selected" class="candidate-selection-reason">
      <strong>入选原因</strong>
      {{ meta.why_selected }}
    </p>
    <ul v-if="showDetails && meta?.selection_basis?.length" class="candidate-selection-basis">
      <li v-for="item in meta.selection_basis" :key="item">{{ item }}</li>
    </ul>
    <p v-if="showDetails && meta?.change_evidence?.strategy_reason" class="candidate-change-reason">
      <strong>重组依据</strong>
      {{ meta.change_evidence.strategy_reason }}
    </p>
    <dl v-if="showDetails && meta?.before_after" class="candidate-before-after">
      <div>
        <dt>原线路</dt>
        <dd>{{ metricSnapshot(meta.before_after.before) }}</dd>
      </div>
      <div>
        <dt>候选草案</dt>
        <dd>{{ metricSnapshot(meta.before_after.after) }}</dd>
      </div>
    </dl>
    <p v-if="showDetails && board.setter_commentary" class="candidate-commentary">{{ board.setter_commentary }}</p>
    <small v-if="showDetails && meta?.notes?.length" class="candidate-notes">{{ meta.notes.join('；') }}</small>

    <section v-if="showBeta" class="comparison-beta">
      <strong>{{ meta?.movement_validation_status === 'not_run' ? '动作草案' : '完整动作序列' }}</strong>
      <p v-if="meta?.movement_validation_status === 'not_run'" class="beta-boundary">
        按岩点顺序生成，尚未通过完整身体平衡检查，不代表推荐 Beta。
      </p>
      <ol v-if="board.beta_sequence?.length">
        <li v-for="(step, index) in sortedSteps" :key="`${step.step}-${step.limb}-${step.hold_id}-${index}`">
          {{ betaStepLabel(step, index) }}
        </li>
      </ol>
      <p v-else>尚未设置 Beta 动作。</p>
    </section>

    <footer v-if="canSetBaseline || removable || loadable" class="comparison-actions">
      <el-button v-if="canSetBaseline" @click="$emit('set-baseline')">设为基准</el-button>
      <el-button v-if="removable" plain @click="$emit('remove')">移出对照</el-button>
      <el-button v-if="loadable" type="primary" @click="$emit('load')">载入定线工作台</el-button>
    </footer>
  </article>
</template>

<script setup>
import { computed } from 'vue'
import BoardCanvas from './BoardCanvas.vue'
import { betaStepLabel, boardViewModel, compareBoards } from '../utils/boardComparison.js'
import { calibrationLabel, confidenceLabel } from '../constants/gradeSystem'

const props = defineProps({
  board: { type: Object, required: true },
  reference: { type: Object, default: null },
  label: { type: String, default: '对照岩板' },
  baseline: { type: Boolean, default: false },
  canSetBaseline: { type: Boolean, default: false },
  removable: { type: Boolean, default: false },
  loadable: { type: Boolean, default: false },
  meta: { type: Object, default: null },
  showBeta: { type: Boolean, default: true },
  showMovementCount: { type: Boolean, default: true },
  showDetails: { type: Boolean, default: true },
  resolveHoldVisual: { type: Function, required: true },
})

defineEmits(['set-baseline', 'remove', 'load'])

const view = computed(() => boardViewModel(props.board))
const comparison = computed(() => props.reference ? compareBoards(props.reference, props.board) : null)
const displayHolds = computed(() => comparison.value?.displayHolds || props.board.placed_holds || [])
const sortedSteps = computed(() => [...(props.board.beta_sequence || [])].sort((a, b) => Number(a.step || 0) - Number(b.step || 0)))
const workflowLabel = computed(() => {
  if (props.meta) return '未保存副本'
  if (props.board.archived_at) return '已归档'
  return props.board.workflow_status === 'ready_for_review' ? '可检查' : '草稿'
})

function coordinates(items) {
  return items.map((item) => item.id).sort((a, b) => a.localeCompare(b, 'en', { numeric: true })).join('、')
}

function percent(value) {
  return `${Math.round(Number(value || 0) * 100)}%`
}

function candidateRiskLabel(meta) {
  if (meta.risk_assessment_status === 'partial') {
    return `结构风险 ${meta.structural_risk_score ?? meta.risk_score ?? '-'} · 动作未评估`
  }
  return `风险 ${meta.risk_score ?? '-'}`
}

function metricSnapshot(snapshot = {}) {
  return [
    `结构质量 ${snapshot.structural_quality ?? '-'}`,
    `等效难度 ${snapshot.predicted_grade || '-'}`,
    `岩点 ${snapshot.hold_count ?? '-'}`,
    `横向 ${snapshot.horizontal_span ?? '-'} 列`,
    `最大断档 ${snapshot.max_vertical_gap ?? '-'} 排`,
  ].join('，')
}
</script>
