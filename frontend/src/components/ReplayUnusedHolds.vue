<template>
  <svg v-if="frame && holds.length" class="unused-holds" :viewBox="`0 0 ${frame.width} ${frame.height}`" role="img" aria-label="真人画面与线路图同步标亮未使用岩点">
    <defs><clipPath :id="`${clipId}-map`"><rect :x="frame.mapClip[0]" :y="frame.mapClip[1]" :width="frame.mapClip[2]" :height="frame.mapClip[3]" /></clipPath>
      <clipPath :id="`${clipId}-video`"><rect :x="frame.video[0]" :y="frame.video[1]" :width="frame.video[2]" :height="frame.video[3]" /></clipPath></defs>
    <g class="unused-pair">
      <g :clip-path="`url(#${clipId}-map)`"><polygon v-for="hold in polygons" :key="hold.id" :points="hold.map" /></g>
      <g :clip-path="`url(#${clipId}-video)`"><polygon v-for="hold in polygons.filter(h => h.video)" :key="hold.id" :points="hold.video" /></g>
    </g>
  </svg>
</template>
<script setup>
import { computed, useId } from 'vue'
import { projectPoint, referenceToFrame } from '../services/replayFrameGeometry.js'
const props = defineProps({ holds: Array, frame: Object, transform: Array })
const clipId = `unused-${useId()}`
const polygons = computed(() => (props.holds || []).filter(h => h.polygon?.length >= 3).map(h => {
  const actual = h.polygon.map(p => referenceToFrame(p, props.transform, props.frame.source))
  return { id: h.id, map: h.polygon.map(p => projectPoint(p, props.frame.map).join(',')).join(' '),
    video: actual.every(p => p?.every(Number.isFinite)) ? actual.map(p => projectPoint(p, props.frame.video).join(',')).join(' ') : null }
}))
</script>
<style scoped>
.unused-holds{position:absolute;inset:0;width:100%;height:100%;overflow:hidden;pointer-events:none}
.unused-pair{animation:unused-pulse .6s ease-in-out 3}polygon{fill:#edcb5266;stroke:#ffe181;stroke-width:3;vector-effect:non-scaling-stroke}
@keyframes unused-pulse{0%,100%{opacity:1}50%{opacity:.15}}
@media(prefers-reduced-motion:reduce){.unused-pair{animation:none}}
</style>
