<template>
  <section :id="id" ref="panel" class="cinema-summary summary-overlay" :class="{ 'visual-card': visualChapter }" aria-label="复盘总结"
    tabindex="-1" @keydown.esc.prevent.stop="$emit('collapse')" @keydown.left.prevent="change(-1)" @keydown.right.prevent="change(1)">
    <div class="summary-window" @pointerenter="hovered = true" @pointerleave="hovered = false" @focusin="focused = true" @focusout="focused = $event.currentTarget.contains($event.relatedTarget)">
    <header class="summary-tools">
      <button ref="closeButton" class="collapse-data" type="button" aria-label="收起总结" title="收起总结" @click="$emit('collapse')"><Minus aria-hidden="true" /></button>
      <button class="skip-summary" type="button" aria-label="跳过总结" @click="$emit('collapse')">跳过</button>
    </header>
    <button class="card-arrow previous" type="button" aria-label="上一张总结" :title="`上一张：${neighbor(-1).label}`" @click="change(-1)"><ArrowLeft aria-hidden="true" /></button>
    <div class="summary-card" aria-live="polite">
    <Transition name="recap-page" mode="out-in" appear>
    <div :key="chapter" class="summary-page" :style="{ '--page-direction': direction }">
    <section v-if="routeRows.length && (chapter === 'route')" class="summary-route" aria-label="线路岩点使用">
      <h2>线路岩点使用</h2>
      <dl class="summary-rows"><div v-for="(metric, index) in routeRows" :key="metric.key" class="summary-row"><dt>{{ metric.label }}</dt><dd>{{ metricValue(metric) }} <span>{{ metric.unit }}</span></dd></div></dl>
      <p class="summary-note">同一岩点只计一次</p>
    </section>
    <section v-if="displayedMetrics.length && (chapter === 'basics')" class="summary-basics" aria-label="本次攀爬数据">
      <h2>本次攀爬</h2>
      <dl class="summary-rows"><div v-for="(metric, index) in displayedMetrics" :key="metric.key" class="summary-row"><dt>{{ metric.label }}</dt><dd><button v-if="metric.key === 'longest_still' && Number.isFinite(metric.start_seconds)" type="button" @click="$emit('locate', metric)">{{ metricValue(metric) }} <span>{{ metric.unit }}</span><small>回看</small></button><template v-else>{{ metricValue(metric) }} <span>{{ metric.unit }}</span></template></dd></div></dl>
    </section>
    <section v-if="motionSummary && (chapter === 'rhythm')" class="summary-rhythm" aria-label="整体攀爬节奏">
      <h2>整体攀爬节奏</h2>
      <div class="rhythm-clock"><span>0 秒</span><span>{{ number(motionSummary.duration_seconds) }} 秒</span></div>
      <div class="rhythm-track" aria-label="移动、姿态停留和未观测区间"><span v-for="(segment, index) in motionSummary.segments || []" :key="index" :class="segment.kind" :style="{ width: `${width(segment)}%` }" :title="`${rhythmLabels[segment.kind] || '未观测'} ${number(segment.start_seconds)}–${number(segment.end_seconds)} 秒`" /></div>
      <dl class="rhythm-totals"><div v-for="row in motionSummary.totals || []" :key="row.kind" class="rhythm-row"><dt><i :class="row.kind" />{{ row.label }}</dt><dd v-if="hasMotionObservation || row.kind === 'unknown'">{{ number(row.percent) }}% <span>约 {{ number(row.seconds) }} 秒</span></dd><dd v-else>尚未确认</dd></div></dl>
      <p class="summary-note">{{ hasMotionObservation ? '按原片时间统计 · 未观测不计作停留' : '暂无连续姿态观测，移动与停留时长尚未确认' }}</p>
    </section>
    <section v-if="priorityFocus && (chapter === 'focus')" class="summary-focus" aria-label="本次复盘重点">
      <h2>{{ priorityFocus.title }}</h2>
      <p>{{ priorityFocus.text }}</p>
      <button type="button" @click="$emit('locate', priorityFocus)">回看 {{ number(priorityFocus.start_seconds) }}–{{ number(priorityFocus.end_seconds) }} 秒</button>
      <p v-if="priorityFocus.next_check">{{ priorityFocus.next_check }}</p>
    </section>
    <section v-if="chapter === 'unused'" class="summary-unused" aria-label="未使用岩点">
      <h2>未使用岩点</h2><p v-if="unusedCount !== null">本次有 {{ unusedCount }} 个岩点未使用</p><p v-else>岩点使用情况尚未确认</p>
      <p class="summary-note">{{ unusedCount ? '画面与线路图同步闪烁后保持标亮' : unusedCount === 0 ? '本次使用了全部线路岩点' : '缺少有效用点记录' }}</p>
    </section>
    <section v-if="chapter === 'trajectory'" class="summary-trajectory" aria-label="躯干中心移动路线">
      <h2>躯干中心移动路线</h2><p>从四肢同时在点上，到双手到达完攀点</p>
      <p class="summary-note">{{ torsoTrajectory?.climbing_window?.status === 'finish_unconfirmed' ? '未确认双手完攀，显示至最后在点区间' : torsoTrajectory?.segments?.length ? '路线显示在右侧线路图，缺测处断开' : '起攀或连续姿态尚未确认，暂无路线' }}</p>
    </section>
    </div>
    </Transition>
    </div>
    <button class="card-arrow next" type="button" aria-label="下一张总结" :title="`下一张：${neighbor(1).label}`" @click="change(1)"><ArrowRight aria-hidden="true" /></button>
    </div>
  </section>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { Minus, ArrowLeft, ArrowRight } from '@element-plus/icons-vue'
import { metricValue, summaryMetrics, routeMetrics } from '../services/replayPresentation.js'
import { createReplayCardAutoplay } from '../services/replayCardAutoplay.js'
const props = defineProps({ id: String, metrics: { type: Array, default: () => [] }, motionSummary: Object, torsoTrajectory: Object, priorityFocus: Object,
  unusedCount: { default: null }, elapsed: Number, manual: Boolean, reducedMotion: Boolean })
const emit = defineEmits(['collapse', 'locate', 'chapter', 'interact'])
const routeReady = computed(() => props.torsoTrajectory?.segments?.some(run => run.length >= 2))
const panel = ref(null), closeButton = ref(null), chapter = ref(routeReady.value ? 'trajectory' : 'route')
const routeRows = computed(() => routeMetrics(props.metrics))
const displayedMetrics = computed(() => summaryMetrics(props.metrics, props.motionSummary))
const chapters = computed(() => [
  ...(routeReady.value ? [{ key: 'trajectory', label: '中心路线' }] : []),
  { key: 'route', label: '岩点使用' }, { key: 'unused', label: '未使用岩点' },
  { key: 'basics', label: '基础数据' }, ...(props.motionSummary ? [{ key: 'rhythm', label: '整体节奏' }] : []),
  ...(props.torsoTrajectory && !routeReady.value ? [{ key: 'trajectory', label: '中心路线' }] : []),
  ...(props.priorityFocus ? [{ key: 'focus', label: '回看重点' }] : []),
])
const chapterIndex = computed(() => chapters.value.findIndex(c => c.key === chapter.value))
const visualChapter = computed(() => ['unused', 'trajectory'].includes(chapter.value))
const direction = ref(1), hovered = ref(false), focused = ref(false), hidden = ref(false)
const neighbor = delta => chapters.value[(chapterIndex.value + delta + chapters.value.length) % chapters.value.length]
function change(delta, manual = true) {
  if (manual) { autoplay.stop(); emit('interact') }
  direction.value = delta
  chapter.value = neighbor(delta).key
}
const autoplay = createReplayCardAutoplay({
  current: () => ({ index: chapterIndex.value, count: chapters.value.length }),
  advance: () => change(1, false), finish: () => emit('collapse'),
})
watch(chapter, value => { emit('chapter', value); autoplay.reset() }, { immediate: true })
watch(() => props.manual, value => {
  if (value) autoplay.stop()
  else { chapter.value = routeReady.value ? 'trajectory' : 'route'; autoplay.start() }
}, { immediate: true })
watch(() => hovered.value || focused.value || hidden.value, value => autoplay.pause(value))
function visibility() { hidden.value = document.hidden }
onMounted(() => { visibility(); document.addEventListener('visibilitychange', visibility) })
onBeforeUnmount(() => { autoplay.dispose(); document.removeEventListener('visibilitychange', visibility) })
const rhythmLabels = { moving: '移动', relative_still: '姿态停留', unknown: '未观测' }
const hasMotionObservation = computed(() => props.motionSummary?.segments?.some(s => ['moving', 'relative_still'].includes(s.kind) && s.end_seconds > s.start_seconds))
const number = value => Number.isFinite(Number(value)) ? Number(value).toFixed(1) : '尚未确认'
const width = segment => props.motionSummary?.duration_seconds > 0 ? Math.max(0, (segment.end_seconds - segment.start_seconds) / props.motionSummary.duration_seconds * 100) : 0
defineExpose({ focusClose: () => closeButton.value?.focus(), containsFocus: () => panel.value?.contains(document.activeElement) })
</script>

<style scoped>
.cinema-summary{position:absolute;inset:0;z-index:4;display:grid;grid-template-rows:minmax(0,1fr);grid-template-columns:minmax(0,1fr);place-items:center;padding:16px;box-sizing:border-box;color:#f7fafb;outline:none;pointer-events:none}
.summary-window{position:relative;display:flex;flex-direction:column;width:min(100%,440px);height:320px;max-height:100%;min-height:0;box-sizing:border-box;background:#20282b;border-radius:14px;box-shadow:0 12px 36px #0008;pointer-events:auto;overflow:hidden;animation:recap-arrive .48s cubic-bezier(.16,1,.3,1)}
.summary-tools{display:flex;align-items:center;justify-content:space-between;padding:4px 8px;flex:none}
.summary-card{flex:1;box-sizing:border-box;padding:12px 48px 24px;overflow:auto;min-height:0;scrollbar-color:#839093 #20282b;scrollbar-width:thin}
h2{margin:0 0 16px;font-size:20px;font-weight:600;text-align:center;text-wrap:balance}p{line-height:1.6;text-align:center;margin:8px 0}
.summary-rows,.rhythm-totals{margin:0}.summary-row,.rhythm-row{display:flex;align-items:baseline;justify-content:space-between;gap:16px;padding:8px 0}dt{color:#e0e5e8;line-height:1.6}dd{margin:0;text-align:right;font-size:22px;font-weight:600;font-variant-numeric:tabular-nums}dd span{font-size:13px;font-weight:400;color:#c1c7cb}
button{font:inherit;color:inherit;cursor:pointer;min-height:44px;min-width:44px;border:0;border-radius:6px;background:transparent;padding:6px 12px;pointer-events:auto}button:hover:not(:disabled){background:#465057}button:disabled{opacity:.35;cursor:default}button:focus-visible{outline:2px solid #edcb52;outline-offset:-3px}
button svg{width:20px;height:20px;display:block}.collapse-data{display:grid;place-items:center}.skip-summary{font-size:13px}.card-arrow{position:absolute;top:50%;transform:translateY(-50%);z-index:1;display:grid;place-items:center;padding:0;transition:background-color .14s,color .14s}.card-arrow svg{transition:transform .14s cubic-bezier(.16,1,.3,1)}.card-arrow:hover{color:#ffe181}.card-arrow:active:not(:disabled){background:#edcb52;color:#20282b;transition:none}.card-arrow:active svg{transform:scale(.82)}.previous{left:0}.next{right:0}
dd button{padding:0;text-decoration:underline;text-underline-offset:4px;text-align:right}dd small{font-size:12px;margin-left:10px;font-weight:400}
.summary-note{margin:8px 0 0;color:#c1c7cb;font-size:13px;line-height:1.6;text-align:center}.summary-focus button{display:block;margin:12px auto}.summary-focus p{font-size:14px}
.rhythm-clock{display:flex;justify-content:space-between;color:#c1c7cb;font-size:13px;margin-bottom:8px}.rhythm-track{display:flex;height:16px;overflow:hidden;border-radius:4px;margin-bottom:16px}.moving{background:#7cdee5}.relative_still{background:#e7c88d}.unknown{background:#66777e}.rhythm-row dt{display:flex;align-items:center;gap:8px}.rhythm-row i{width:10px;height:10px;border-radius:50%;flex:none}
.recap-page-enter-active{transition:transform .3s cubic-bezier(.16,1,.3,1),opacity .3s,filter .3s}.recap-page-leave-active{transition:transform .12s ease-in,opacity .12s}.recap-page-enter-from{opacity:0;transform:translateX(calc(var(--page-direction,1) * 14px));filter:blur(2px)}.recap-page-leave-to{opacity:0;transform:translateX(calc(var(--page-direction,1) * -8px))}.recap-page-enter-active h2{animation:recap-ink .4s cubic-bezier(.16,1,.3,1)}.recap-page-enter-active :is(p,dl,.rhythm-clock,.rhythm-track){animation:recap-ink .4s .08s cubic-bezier(.16,1,.3,1) both}
@keyframes recap-arrive{from{opacity:0;transform:scale(.96);clip-path:inset(4% 0 round 14px);box-shadow:0 2px 8px #0000}to{opacity:1;transform:scale(1);clip-path:inset(0 round 14px);box-shadow:0 12px 36px #0008}}
@keyframes recap-ink{from{opacity:0;filter:blur(2px)}to{opacity:1;filter:blur(0)}}
::selection{background:#edcb52;color:#20282b}
@media(max-width:600px){.cinema-summary{padding:8px}.summary-tools{padding:0 4px}.summary-card{padding:8px 44px 20px}h2{font-size:17px;margin-bottom:10px}p{font-size:13px}.summary-row,.rhythm-row{gap:8px;padding:4px 0;font-size:12px}dd{font-size:18px}.rhythm-row dd span{display:block}.summary-note{font-size:12px}}
@media(prefers-reduced-motion:reduce){.summary-window{animation:recap-ink .14s linear}.recap-page-enter-active,.recap-page-leave-active{transition:opacity .12s}.recap-page-enter-from,.recap-page-leave-to{transform:none;filter:none}.recap-page-enter-active :is(h2,p,dl,.rhythm-clock,.rhythm-track){animation:none}.card-arrow svg{transition:none}.card-arrow:active svg{transform:none}}
</style>
