<template>
  <section class="page ai-page">
      <div class="lab-panel">
        <div class="lab-heading">
          <div>
            <p class="eyebrow">规则辅助实验</p>
            <h2>实验任务</h2>
          </div>
          <el-button :icon="Refresh" :loading="boards.loading" @click="boards.fetchMyBoards">刷新岩板</el-button>
        </div>
        <div class="ai-lab-scope" role="note" aria-label="AI 实验室功能定位">
          <strong>辅助定线，不替代试爬</strong>
          <span>用于讨论候选、发现明显结构问题、生成不覆盖原线路的草案，并保留可复核的评分和规则证据。</span>
        </div>
        <section class="ai-board-picker">
          <div class="panel-heading">
            <div>
              <h3>选择岩板资产</h3>
              <span>AI 实验室会基于这里选中的岩板执行任务。</span>
            </div>
            <el-button v-if="selectedAiBoard" plain @click="$emit('load-selected-board')">载入定线工作台</el-button>
          </div>
          <template v-if="aiAvailableBoards.length">
            <el-select v-model="aiExperiment.selectedBoardId" placeholder="选择岩板资产">
              <el-option
                v-for="board in aiAvailableBoards"
                :key="board.saved_id || board.route_name"
                :label="board.route_name || '未命名岩板'"
                :value="board.saved_id"
              />
            </el-select>
            <div class="ai-board-list">
              <button
                v-for="board in aiAvailableBoards"
                :key="board.saved_id || board.route_name"
                type="button"
                class="ai-board-option"
                :class="{ active: selectedAiBoard?.saved_id === board.saved_id }"
                @click="$emit('select-board', board)"
              >
                <strong>{{ board.route_name || '未命名岩板' }}</strong>
                <span>{{ boardSpecDisplayLabel(board) }} / {{ board.placed_holds?.length || 0 }} 岩点 / {{ board.beta_sequence?.length || 0 }} Beta</span>
                <span>{{ workflowLabel(board) }}{{ board.ai_eligible ? ' / AI 可用' : ' / 布局初审' }}</span>
              </button>
            </div>
          </template>
          <div v-else class="empty-state">
            <strong>{{ aiExperiment.mode === 'compose_route' ? '没有可用于 AI 组合的完整线路' : '没有可用于布局初审的 11×18 岩板' }}</strong>
            <span>{{ aiExperiment.mode === 'compose_route' ? '先在定线工作台按提示补全 Beta 和起终点，再保存线路。' : '先保存一块 11×18 岩板。' }}</span>
            <div class="command-row">
              <el-button type="primary" plain @click="$emit('navigate', 'boards')">查看岩板资产</el-button>
              <el-button @click="$emit('navigate', 'studio')">进入定线工作台</el-button>
            </div>
          </div>
          <div v-if="selectedAiBoard" class="selected-board-summary">
            <strong>{{ selectedAiBoard.route_name || '未命名岩板' }}</strong>
            <span>{{ selectedAiBoardStats.spec }}</span>
            <span>{{ selectedAiBoardStats.holds }} 岩点</span>
            <span>{{ selectedAiBoardStats.beta }} Beta</span>
            <span>{{ selectedAiBoardStats.difficulty }}</span>
            <span>{{ workflowLabel(selectedAiBoard) }}</span>
          </div>
          <el-alert
            v-if="aiBoardBlockingMessage"
            type="warning"
            :closable="false"
            :title="aiBoardBlockingMessage"
            show-icon
          />
          <el-alert
            v-else-if="aiBoardWarnings.length"
            type="info"
            :closable="false"
            title="提交前提示"
            :description="aiBoardWarnings.join(' ')"
            show-icon
          />
        </section>
        <div class="experiment-controls">
          <el-segmented
            v-model="aiExperiment.mode"
            :options="[
              { label: '重新组合路线', value: 'compose_route' },
              { label: '提出修改建议', value: 'review_route' },
            ]"
          />
          <el-select
            v-if="aiExperiment.mode === 'compose_route'"
            v-model="aiExperiment.generation_goal"
            aria-label="AI 组合目标"
            placeholder="选择组合目标"
          >
            <el-option label="质量优先" value="quality_first" />
            <el-option label="目标难度优先" value="grade_match" />
            <el-option label="动作风格多样" value="style_variation" />
          </el-select>
          <el-select
            v-else
            v-model="aiExperiment.review_focus"
            aria-label="AI 审核重点"
            placeholder="选择审核重点"
          >
            <el-option label="综合检查" value="overall" />
            <el-option label="脚点检查" value="footholds" />
            <el-option label="难度检查" value="difficulty" />
            <el-option label="动作顺序检查" value="beta_sequence" />
          </el-select>
          <p class="control-help">
            {{ aiExperiment.mode === 'compose_route'
              ? '只有通过完整静态人体工学门禁的岩板才会返回；无合格路径时建议保留原线路。'
              : '所选重点会改变专项检查；自动修复岩板同样必须通过完整静态门禁。' }}
          </p>
        </div>
        <div class="command-row">
          <el-button type="primary" :disabled="!canRunAiExperiment" :loading="routeGen.loading" @click="$emit('run-experiment')">提交所选岩板</el-button>
          <el-button v-if="routeGen.loading" @click="routeGen.cancelGeneration">取消任务</el-button>
          <el-button @click="$emit('navigate', 'studio')">返回定线工作台</el-button>
        </div>
        <el-alert
          v-if="routeGen.taskId"
          type="info"
          :closable="false"
          :title="`任务 ${routeGen.taskId} · ${aiTaskStatusLabel(routeGen.status)} · ${routeGen.elapsedSeconds} 秒`"
        />
        <el-alert v-if="routeGen.error" type="error" :closable="false" :title="routeGen.error" />
        <section v-if="routeGen.result" class="experiment-result">
          <header class="experiment-verdict">
            <div>
              <span>{{ routeGen.result.mode === 'review_route' ? '定线建议' : '重组建议' }}</span>
              <strong>{{ routeGen.result.recommendation?.title || routeGen.result.review_summary || routeGen.result.analysis_summary }}</strong>
              <p>{{ routeGen.result.recommendation?.summary || routeGen.result.review_summary }}</p>
            </div>
            <span
              v-if="routeGen.result.risk_level"
              :class="['verdict-risk', `is-${routeGen.result.metrics?.risk_assessment_status === 'partial' ? 'partial' : routeGen.result.risk_level}`]"
            >
              {{ riskAssessmentLabel(routeGen.result) }}
            </span>
          </header>

          <template v-if="routeGen.result.mode === 'compose_route'">
            <el-alert
              v-if="routeGen.result.failure_suggestion"
              type="warning"
              :closable="false"
              :title="routeGen.result.failure_suggestion"
              show-icon
            />
            <div v-if="routeGen.result.selected_routes?.[0]" class="ai-primary-board">
              <BoardComparisonPanel
                :board="routeGen.result.selected_routes[0]"
                label="最佳新岩板"
                loadable
                :show-beta="false"
                :show-movement-count="false"
                :show-details="false"
                :resolve-hold-visual="library.resolveHoldVisual"
                @load="$emit('load-candidate', routeGen.result.selected_routes[0])"
              />
            </div>
          </template>

          <template v-else>
            <article v-for="violation in routeGen.result.violations" :key="violation.code" class="result-card result-card-critical">
              <span>必须处理</span>
              <strong>{{ violation.message }}</strong>
              <small v-if="violation.hold_ids?.length">相关岩点：{{ violation.hold_ids.join('、') }}</small>
            </article>
            <article v-for="suggestion in routeGen.result.suggestions" :key="suggestion.title" class="result-card">
              <span>{{ suggestionGroupLabel(suggestion) }}</span>
              <strong>{{ suggestion.title }}</strong>
              <p>{{ suggestion.detail }}</p>
            </article>
            <div v-if="reviewRepairCandidate" class="ai-primary-board">
              <BoardComparisonPanel
                :board="reviewRepairCandidate"
                label="通过门禁的修复岩板"
                loadable
                :show-beta="false"
                :show-movement-count="false"
                :show-details="false"
                :resolve-hold-visual="library.resolveHoldVisual"
                @load="$emit('load-candidate', reviewRepairCandidate)"
              />
            </div>
          </template>

          <el-collapse class="ai-analysis-collapse">
            <el-collapse-item title="查看分析依据" name="analysis">
              <div class="result-context">
                <span>分析岩板：{{ selectedAiBoard?.route_name || '所选岩板' }}</span>
                <span>{{ selectedAiBoardStats.holds }} 岩点 / {{ selectedAiBoardStats.difficulty }}</span>
                <span>{{ routeGen.result.llm_enriched ? 'AI 已用中文润色' : '本地中文结果' }}</span>
              </div>
              <div class="result-metrics">
                <span v-if="routeGen.result.metrics?.target_grade">目标 {{ routeGen.result.metrics.target_grade }}</span>
                <span v-if="routeGen.result.metrics?.quality_score !== undefined">结构质量 {{ routeGen.result.metrics.quality_score }}</span>
                <span v-if="routeGen.result.metrics?.predicted_grade">MoonBoard 等效难度 {{ routeGen.result.metrics.predicted_grade }}</span>
                <span v-if="routeGen.result.metrics?.risk_score !== undefined">{{ riskMetricLabel(routeGen.result.metrics) }}</span>
                <span v-if="routeGen.result.risk_level">等级 {{ riskLevelLabel(routeGen.result.risk_level) }}</span>
                <span v-if="routeGen.result.metrics?.review_scope">{{ reviewScopeLabel(routeGen.result.metrics.review_scope) }}</span>
              </div>
              <div v-if="routeGen.result.applied_constraints?.length" class="result-metrics">
                <span v-for="constraint in routeGen.result.applied_constraints" :key="constraint">{{ constraint }}</span>
              </div>

              <div v-if="routeGen.result.mode === 'compose_route' && aiComparisonReference" class="ai-comparison-grid count-2">
                <BoardComparisonPanel
                  :board="aiComparisonReference"
                  label="原岩板"
                  baseline
                  :show-beta="false"
                  :show-movement-count="false"
                  :resolve-hold-visual="library.resolveHoldVisual"
                />
                <BoardComparisonPanel
                  v-if="routeGen.result.selected_routes?.[0]"
                  :board="routeGen.result.selected_routes[0]"
                  :reference="aiComparisonReference"
                  :label="candidateMeta(0).label_text || '最佳新岩板'"
                  :meta="candidateMeta(0)"
                  :show-beta="false"
                  :show-movement-count="false"
                  :resolve-hold-visual="library.resolveHoldVisual"
                />
              </div>

              <template v-if="routeGen.result.mode === 'review_route'">
                <div v-if="routeGen.result.board" class="review-board-preview">
                  <BoardComparisonPanel
                    :board="routeGen.result.board"
                    label="审核对象"
                    baseline
                    :show-movement-count="false"
                    :resolve-hold-visual="library.resolveHoldVisual"
                  />
                </div>
                <article v-for="suggestion in routeGen.result.suggestions" :key="`evidence-${suggestion.title}`" class="result-card">
                  <strong>{{ suggestion.title }}</strong>
                  <dl class="suggestion-evidence">
                    <div><dt>本次观测</dt><dd>{{ suggestion.observed || '暂无量化观测' }}</dd></div>
                    <div><dt>判定阈值</dt><dd>{{ suggestion.threshold || '未设置阈值' }}</dd></div>
                    <div><dt>预计改善</dt><dd>{{ suggestion.expected_effect || '需要定线者复核' }}</dd></div>
                  </dl>
                  <div class="suggestion-locators">
                    <span v-if="suggestion.hold_ids?.length">相关岩点：{{ suggestion.hold_ids.join('、') }}</span>
                    <span v-if="suggestion.beta_steps?.length">原线路 Beta 步骤：{{ suggestion.beta_steps.join('、') }}</span>
                    <span>证据{{ evidenceStatusLabel(suggestion.evidence_status) }} · {{ confidenceLabel(suggestion.confidence) }}</span>
                  </div>
                </article>
              </template>

              <AIExperimentExplanation
                v-if="routeGen.result.explanation"
                :explanation="routeGen.result.explanation"
              />
              <div v-if="routeGen.result.algorithm_notes?.length" class="result-metrics">
                <span v-for="note in routeGen.result.algorithm_notes" :key="note">{{ note }}</span>
              </div>
            </el-collapse-item>
          </el-collapse>
        </section>
      </div>
    </section>
</template>

<script setup>
import AIExperimentExplanation from './AIExperimentExplanation.vue'
import BoardComparisonPanel from './BoardComparisonPanel.vue'
import { Refresh } from '@element-plus/icons-vue'

defineProps({
  boards: { type: Object, required: true },
  library: { type: Object, required: true },
  routeGen: { type: Object, required: true },
  aiExperiment: { type: Object, required: true },
  aiAvailableBoards: { type: Array, default: () => [] },
  selectedAiBoard: { type: Object, default: null },
  selectedAiBoardStats: { type: Object, required: true },
  aiBoardWarnings: { type: Array, default: () => [] },
  aiBoardBlockingMessage: { type: String, default: '' },
  canRunAiExperiment: { type: Boolean, default: false },
  aiComparisonReference: { type: Object, default: null },
  reviewRepairCandidate: { type: Object, default: null },
  boardSpecDisplayLabel: { type: Function, required: true },
  workflowLabel: { type: Function, required: true },
  suggestionGroupLabel: { type: Function, required: true },
  riskAssessmentLabel: { type: Function, required: true },
  riskMetricLabel: { type: Function, required: true },
  riskLevelLabel: { type: Function, required: true },
  reviewScopeLabel: { type: Function, required: true },
  evidenceStatusLabel: { type: Function, required: true },
  confidenceLabel: { type: Function, required: true },
  aiTaskStatusLabel: { type: Function, required: true },
  candidateMeta: { type: Function, required: true },
})

defineEmits(['navigate', 'load-selected-board', 'select-board', 'run-experiment', 'load-candidate'])
</script>
