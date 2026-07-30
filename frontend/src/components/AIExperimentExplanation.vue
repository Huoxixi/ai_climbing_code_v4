<template>
  <section class="ai-explanation" aria-labelledby="ai-explanation-title">
    <header class="ai-explanation-heading">
      <div>
        <h3 id="ai-explanation-title">本次结果如何得出</h3>
        <p>候选和检查结论由本地规则决定，难度由固定版本模型估算，中文润色不参与判定。</p>
      </div>
      <span class="explanation-total">结构质量 {{ scoreTotal }}/100</span>
    </header>

    <div class="explanation-sources" aria-label="决策来源">
      <article v-for="source in explanation.decision_sources || []" :key="source.name">
        <strong>{{ source.name }}</strong>
        <span>{{ source.source }}</span>
        <p>{{ source.role }}</p>
      </article>
    </div>

    <div v-if="explanation.uncertainties?.length" class="explanation-limitations" role="note">
      <strong>结果边界</strong>
      <ul>
        <li v-for="item in explanation.uncertainties" :key="item">{{ item }}</li>
      </ul>
    </div>

    <section class="explanation-section" aria-labelledby="score-breakdown-title">
      <div class="explanation-section-heading">
        <h4 id="score-breakdown-title">结构质量评分</h4>
        <span>分项总和等于最终质量分</span>
      </div>
      <div class="score-breakdown-list">
        <article
          v-for="item in explanation.score_breakdown || []"
          :key="item.id"
          class="score-breakdown-row"
          :style="{ '--score-ratio': scoreRatio(item) }"
        >
          <div class="score-row-title">
            <strong>{{ item.label }}</strong>
            <span>{{ number(item.score) }} / {{ number(item.max_score) }}</span>
          </div>
          <div class="score-track" aria-hidden="true"><i /></div>
          <p>{{ item.observed }}，标准：{{ item.threshold }}</p>
          <small>{{ item.explanation }}</small>
          <small v-if="item.related_hold_ids?.length">相关岩点：{{ item.related_hold_ids.join('、') }}</small>
        </article>
      </div>
    </section>

    <section v-if="explanation.risk_breakdown?.length" class="explanation-section" aria-labelledby="risk-breakdown-title">
      <div class="explanation-section-heading">
        <h4 id="risk-breakdown-title">风险分构成</h4>
        <span>只列出本次实际触发的风险因素</span>
      </div>
      <dl class="risk-breakdown-list">
        <div v-for="item in explanation.risk_breakdown" :key="item.id">
          <dt>{{ item.label }}</dt>
          <dd :class="{ deduction: Number(item.points) < 0 }">{{ signedPoints(item.points) }}</dd>
          <small>{{ item.explanation }}</small>
        </div>
      </dl>
    </section>

    <section class="explanation-section" aria-labelledby="rule-checks-title">
      <div class="explanation-section-heading">
        <h4 id="rule-checks-title">规则检查清单</h4>
        <span>通过项、风险项和未检查项均会保留</span>
      </div>
      <div class="rule-check-table" role="table" aria-label="规则检查清单">
        <div class="rule-check-header" role="row">
          <span role="columnheader">检查项</span>
          <span role="columnheader">状态</span>
          <span role="columnheader">本次观测</span>
          <span role="columnheader">判定标准</span>
        </div>
        <article v-for="check in explanation.checks || []" :key="check.id" class="rule-check-row" role="row">
          <div role="cell">
            <strong>{{ check.label }}</strong>
            <small>{{ check.explanation }}</small>
            <small v-if="check.related_hold_ids?.length">相关岩点：{{ check.related_hold_ids.join('、') }}</small>
          </div>
          <span role="cell" :class="['check-status', `is-${check.status}`]">{{ checkStatusLabel(check.status) }}</span>
          <span role="cell">{{ check.observed }}</span>
          <span role="cell">{{ check.threshold }}</span>
        </article>
      </div>
    </section>

    <section v-if="explanation.candidate_trace?.length" class="explanation-section" aria-labelledby="candidate-trace-title">
      <div class="explanation-section-heading">
        <h4 id="candidate-trace-title">候选选择过程</h4>
        <span>展示结构化筛选证据，不展示模型内部推理</span>
      </div>
      <ol class="candidate-trace-list">
        <li v-for="(trace, index) in explanation.candidate_trace" :key="`${trace.source}-${trace.strategy}-${index}`">
          <span :class="['trace-status', `is-${trace.status}`]">{{ traceStatusLabel(trace.status) }}</span>
          <div>
            <strong>{{ trace.strategy_label }} · {{ sourceLabel(trace.source) }}</strong>
            <p>{{ trace.reason }}</p>
            <small v-if="traceMetricSummary(trace.metrics)">{{ traceMetricSummary(trace.metrics) }}</small>
          </div>
          <b v-if="trace.selected_rank">第 {{ trace.selected_rank }} 名</b>
        </li>
      </ol>
    </section>

    <el-collapse class="explanation-technical">
      <el-collapse-item title="查看输入与版本信息" name="technical">
        <dl class="technical-details">
          <div>
            <dt>输入摘要</dt>
            <dd>{{ inputSummary }}</dd>
          </div>
          <div>
            <dt>规则版本</dt>
            <dd>{{ explanation.versions?.ruleset || '-' }}</dd>
          </div>
          <div>
            <dt>难度模型</dt>
            <dd>{{ explanation.versions?.grade_model || '-' }}</dd>
          </div>
          <div>
            <dt>解释结构</dt>
            <dd>{{ explanation.versions?.explanation_schema || explanation.schema_version }}</dd>
          </div>
          <div class="technical-fingerprint">
            <dt>输入指纹</dt>
            <dd><code>{{ explanation.input_fingerprint }}</code></dd>
          </div>
        </dl>
        <p v-if="explanation.reference_note" class="reference-note">{{ explanation.reference_note }}</p>
      </el-collapse-item>
    </el-collapse>
  </section>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  explanation: { type: Object, required: true },
})

const scoreTotal = computed(() => number((props.explanation.score_breakdown || [])
  .reduce((total, item) => total + Number(item.score || 0), 0)))

const inputSummary = computed(() => {
  const input = props.explanation.input_summary || {}
  const scope = input.mode === 'review_route' ? input.review_focus : input.generation_goal
  return `${input.board_name || '未命名岩板'}，目标 ${input.target_grade || '-'}，${input.hold_count || 0} 个岩点，${input.beta_count || 0} 个 Beta，${scope || '-'}`
})

function number(value) {
  const numeric = Number(value || 0)
  return Number.isInteger(numeric) ? numeric : numeric.toFixed(2).replace(/0+$/, '').replace(/\.$/, '')
}

function scoreRatio(item) {
  const max = Number(item.max_score || 0)
  const ratio = max > 0 ? Math.max(0, Math.min(100, Number(item.score || 0) / max * 100)) : 0
  return `${ratio}%`
}

function signedPoints(value) {
  const numeric = Number(value || 0)
  return `${numeric > 0 ? '+' : ''}${number(numeric)} 分`
}

function checkStatusLabel(status) {
  return { pass: '通过', warning: '需关注', fail: '未通过', not_run: '未检查' }[status] || status
}

function traceStatusLabel(status) {
  return {
    selected: '已选中',
    rejected: '未入选',
    duplicate: '重复',
    failed_validation: '未通过',
  }[status] || status
}

function sourceLabel(source) {
  return { a_star: '动作顺序搜索', local_strategy: '本地组合策略' }[source] || source
}

function traceMetricSummary(metrics = {}) {
  const items = []
  if (metrics.quality_score !== undefined) items.push(`质量 ${metrics.quality_score}`)
  if (metrics.predicted_grade) items.push(`等效难度 ${metrics.predicted_grade}`)
  if (metrics.grade_delta !== undefined) items.push(`难度偏差 ${metrics.grade_delta} 级`)
  if (metrics.risk_score !== undefined) items.push(`结构风险 ${metrics.risk_score}`)
  if (metrics.reuse_rate !== undefined) items.push(`复用率 ${Math.round(Number(metrics.reuse_rate) * 100)}%`)
  return items.join('，')
}
</script>
