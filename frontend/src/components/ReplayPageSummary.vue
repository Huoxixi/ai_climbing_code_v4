<template>
  <section :id="id" ref="panel" class="cinema-summary summary-overlay" :class="{ pinned: staticView }" aria-label="复盘总结"
    tabindex="-1" @keydown.esc.prevent.stop="$emit('collapse')">
    <button ref="closeButton" class="collapse-data" type="button" aria-label="收起总结" @click="$emit('collapse')">收起总结</button>
    <section v-if="routeRows.length && (staticView || chapter === 'route')" class="summary-route" aria-label="线路岩点使用">
      <h2>线路岩点使用</h2>
      <dl class="summary-rows"><div v-for="(metric, index) in routeRows" v-show="rowVisible(index, 0)" :key="metric.key" class="summary-row"><dt>{{ metric.label }}</dt><dd>{{ metricValue(metric) }} <span>{{ metric.unit }}</span></dd></div></dl>
      <p class="summary-note">同一岩点只计一次</p>
    </section>
    <section v-if="displayedMetrics.length && (staticView || chapter === 'basics')" class="summary-basics" aria-label="本次攀爬数据">
      <h2>本次攀爬</h2>
      <dl class="summary-rows"><div v-for="(metric, index) in displayedMetrics" v-show="rowVisible(index, routeEnd)" :key="metric.key" class="summary-row"><dt>{{ metric.label }}</dt><dd><button v-if="metric.key === 'longest_still' && Number.isFinite(metric.start_seconds)" type="button" @click="$emit('locate', metric)">{{ metricValue(metric) }} <span>{{ metric.unit }}</span><small>回看</small></button><template v-else>{{ metricValue(metric) }} <span>{{ metric.unit }}</span></template></dd></div></dl>
    </section>
    <section v-if="motionSummary && (staticView || chapter === 'rhythm')" class="summary-rhythm" aria-label="整体攀爬节奏">
      <h2>整体攀爬节奏</h2>
      <div class="rhythm-clock"><span>0 秒</span><span>{{ number(motionSummary.duration_seconds) }} 秒</span></div>
      <div class="rhythm-track" aria-label="移动、姿态停留和未观测区间"><span v-for="(segment, index) in motionSummary.segments || []" :key="index" :class="segment.kind" :style="{ width: `${width(segment)}%` }" :title="`${rhythmLabels[segment.kind] || '未观测'} ${number(segment.start_seconds)}–${number(segment.end_seconds)} 秒`" /></div>
      <dl class="rhythm-totals"><div v-for="row in motionSummary.totals || []" :key="row.kind" class="rhythm-row"><dt><i :class="row.kind" />{{ row.label }}</dt><dd>{{ number(row.percent) }}% <span>约 {{ number(row.seconds) }} 秒</span></dd></div></dl>
      <p class="summary-note">按原片时间统计 · 未观测不计作停留</p>
    </section>
  </section>
</template>

<script setup>
import { computed, ref } from 'vue'
import { metricValue, summaryMetrics, routeMetrics, routeSeconds, rhythmStart, SUMMARY_INTRO, SUMMARY_STEP } from '../services/replayPresentation.js'
const props = defineProps({ id: String, metrics: { type: Array, default: () => [] }, motionSummary: Object,
  elapsed: { type: Number, default: 0 }, manual: Boolean, reducedMotion: Boolean })
defineEmits(['collapse', 'locate'])
const panel = ref(null), closeButton = ref(null)
const staticView = computed(() => props.manual || props.reducedMotion)
const routeRows = computed(() => routeMetrics(props.metrics))
const displayedMetrics = computed(() => summaryMetrics(props.metrics, props.motionSummary))
const routeEnd = computed(() => routeSeconds(props.metrics))
const chapter = computed(() => routeRows.value.length && props.elapsed < routeEnd.value ? 'route'
  : props.motionSummary && props.elapsed >= rhythmStart(props.metrics, props.motionSummary) ? 'rhythm' : 'basics')
const rowVisible = (index, chapterStart) => staticView.value || props.elapsed >= chapterStart + SUMMARY_INTRO + index * SUMMARY_STEP
const rhythmLabels = { moving: '移动', relative_still: '姿态停留', unknown: '未观测' }
const number = value => Number.isFinite(Number(value)) ? Number(value).toFixed(1) : '尚未确认'
const width = segment => props.motionSummary?.duration_seconds > 0 ? Math.max(0, (segment.end_seconds - segment.start_seconds) / props.motionSummary.duration_seconds * 100) : 0
defineExpose({ focusClose: () => closeButton.value?.focus(), containsFocus: () => panel.value?.contains(document.activeElement) })
</script>

<style scoped>
.cinema-summary { position: absolute; inset: 0; display: flex; flex-direction: column; justify-content: safe center; padding: 8% 11% 15%; color: #f7fafb; outline: none; overflow-y: auto; }
.cinema-summary > section { width: 100%; max-width: 660px; margin: 0 auto; flex-shrink: 0; }
h2 { margin: 0 0 16px; font-size: clamp(22px, 3vw, 38px); font-weight: 700; letter-spacing: -.025em; text-align: center; }
.summary-rows, .rhythm-totals { margin: 0; }
.summary-row, .rhythm-row { display: flex; align-items: baseline; justify-content: space-between; gap: 16px; padding: 8px 0; animation: reveal-data .4s cubic-bezier(.16,1,.3,1) both; }
dt { color: #e0e5e8; line-height: 1.6; }
dd { margin: 0; text-align: right; font-size: clamp(18px, 2.3vw, 28px); font-weight: 600; font-variant-numeric: tabular-nums; }
dd span { font-size: 13px; font-weight: 400; color: #c1c7cb; }
button { font: inherit; color: inherit; cursor: pointer; }
.collapse-data { position: absolute; right: 16px; top: 12px; min-height: 44px; padding: 6px 12px; background: #303c42; border: 0; border-radius: 6px; }
button:hover { background: #465057; }
button:focus-visible { outline: 2px solid #7cdee5; outline-offset: 3px; }
dd button { background: transparent; padding: 0; border: 0; text-decoration: underline; text-underline-offset: 4px; text-align: right; }
dd small { font-size: 12px; margin-left: 10px; font-weight: 400; }
.summary-note { margin: 8px 0 0; color: #c1c7cb; font-size: 13px; line-height: 1.6; text-align: center; }
.rhythm-clock { display: flex; justify-content: space-between; color: #c1c7cb; font-size: 13px; margin-bottom: 8px; font-variant-numeric: tabular-nums; }
.rhythm-track { display: flex; height: 18px; overflow: hidden; border-radius: 4px; margin-bottom: 20px; }
.moving { background: #7cdee5; }.relative_still { background: #e7c88d; }.unknown { background: #66777e; }
.rhythm-row dt { display: flex; align-items: center; gap: 8px; }
.rhythm-row i { width: 10px; height: 10px; border-radius: 50%; flex-shrink: 0; }
.pinned { justify-content: flex-start; padding-top: 64px; padding-bottom: 24px; }
.pinned > section + section { margin-top: 32px; }
.pinned .summary-row, .pinned .rhythm-row { animation: none; }
@keyframes reveal-data { from { opacity: 0; transform: translateY(8px); } to { opacity: 1; transform: translateY(0); } }
@media(max-width:480px) { .cinema-summary { padding: 56px 7% 10%; } .summary-row, .rhythm-row { gap: 12px; } .rhythm-row dd span { display: block; } .pinned { padding-bottom: 24px; } }
@media(prefers-reduced-motion:reduce) { .summary-row, .rhythm-row { animation: none; } }
</style>
