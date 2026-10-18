<template>
  <section class="summary-trajectory" aria-label="躯干中心轨迹">
    <h2>躯干中心轨迹</h2>
    <template v-if="plot">
      <p class="trajectory-shift">{{ horizontalShiftLabel(trajectory.metrics) }}</p>
      <svg class="trajectory-plot" viewBox="0 0 480 240" role="img" aria-label="二维躯干中心移动路线，缺测处断开">
        <title>二维躯干中心移动路线</title>
        <line :x1="plot.start.x" :x2="plot.start.x" y1="16" y2="208" class="origin-line" />
        <polyline v-for="(path, index) in plot.paths" :key="index" :points="path" class="trajectory-path" />
        <circle :cx="plot.start.x" :cy="plot.start.y" r="5" class="trajectory-start" />
        <circle :cx="plot.end.x" :cy="plot.end.y" r="5" class="trajectory-end" />
        <text x="12" y="232">画面左</text><text x="468" y="232" text-anchor="end">画面右</text>
      </svg>
      <div class="trajectory-legend"><span><i class="start" />首个观测 {{ clock(trajectory.start_seconds) }}</span><span><i class="end" />末个观测 {{ clock(trajectory.end_seconds) }}</span></div>
      <dl v-if="trajectory.metrics" class="trajectory-extents"><div><dt>相对起点最左</dt><dd>{{ trajectory.metrics.left_extent_percent.toFixed(1) }}<span>%</span></dd></div><div><dt>相对起点最右</dt><dd>{{ trajectory.metrics.right_extent_percent.toFixed(1) }}<span>%</span></dd></div></dl>
      <p class="trajectory-note">{{ trajectory.metrics ? '偏移按参考画面宽度计算' : '肩髋参考变化或轨迹突跳，暂不比较左右偏移' }} · 有效连续观测 {{ Math.round(trajectory.coverage * 100) }}%</p>
      <p v-if="trajectory.status === 'partial'" class="trajectory-note">仅展示可靠片段，缺测处断开</p>
    </template>
    <p v-else class="trajectory-empty">可靠的连续肩髋观测不足，暂不能生成轨迹</p>
    <p class="trajectory-note">二维躯干位置参考，不代表真实重心或左右承重</p>
  </section>
</template>

<script setup>
import { computed } from 'vue'
import { torsoTrajectoryPlot, horizontalShiftLabel } from '../services/replayTorsoTrajectory.js'
const props = defineProps({ trajectory: { type: Object, required: true } })
const plot = computed(() => torsoTrajectoryPlot(props.trajectory))
const clock = value => `${Math.floor(value / 60)}:${(value % 60).toFixed(1).padStart(4, '0')}`
</script>

<style scoped>
.summary-trajectory { color: #f7fafb; }
h2 { margin: 0 0 12px; font-size: clamp(22px, 3vw, 38px); font-weight: 700; letter-spacing: -.025em; text-align: center; }
.trajectory-shift { margin: 0; font-size: clamp(16px, 2vw, 22px); text-align: center; font-variant-numeric: tabular-nums; }
.trajectory-plot { display: block; width: 100%; height: clamp(130px, 26vh, 230px); margin: 12px 0 8px; }
.trajectory-path { fill: none; stroke: #f7fafb; stroke-width: 2; stroke-linejoin: round; stroke-linecap: round; }
.origin-line { stroke: #94a5ad; stroke-width: 1; stroke-dasharray: 4 6; }
.trajectory-start { fill: #171c1f; stroke: #f7fafb; stroke-width: 2; }
.trajectory-end { fill: #edcb52; stroke: #171c1f; stroke-width: 2; }
text { fill: #c1c7cb; font-family: inherit; font-size: 13px; }
.trajectory-legend { display: flex; justify-content: center; flex-wrap: wrap; gap: 8px 20px; font-size: 13px; color: #e0e5e8; font-variant-numeric: tabular-nums; }
.trajectory-legend span { display: flex; align-items: center; gap: 6px; }
i { width: 8px; height: 8px; border-radius: 50%; box-sizing: border-box; }
i.start { border: 1px solid #f7fafb; } i.end { background: #edcb52; }
.trajectory-extents { display: flex; justify-content: space-evenly; gap: 16px; margin: 20px 0 12px; }
dt { font-size: 13px; color: #e0e5e8; }
dd { margin: 4px 0 0; text-align: center; font-size: 22px; font-weight: 600; font-variant-numeric: tabular-nums; }
dd span { font-size: 13px; font-weight: 400; margin-left: 4px; }
.trajectory-note { margin: 6px 0 0; color: #c1c7cb; font-size: 13px; line-height: 1.6; text-align: center; }
.trajectory-empty { text-align: center; line-height: 1.8; padding: 28px 0; }
@media(max-width:480px) { .trajectory-extents { margin-top: 16px; } .trajectory-plot { height: 160px; } }
</style>
