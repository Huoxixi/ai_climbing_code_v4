<template>
  <svg v-if="paths.length && frame" class="torso-route-end" :viewBox="`0 0 ${frame.width} ${frame.height}`" role="img" aria-label="线路图中的躯干中心移动路线">
    <title>躯干中心移动路线</title>
    <defs><clipPath :id="clipId"><rect :x="frame.mapClip[0]" :y="frame.mapClip[1]" :width="frame.mapClip[2]" :height="frame.mapClip[3]" /></clipPath></defs>
    <g :clip-path="`url(#${clipId})`">
      <polyline v-for="(path, index) in paths" :key="index" :points="path.map(p => p.join(',')).join(' ')" />
      <circle :cx="paths[0][0][0]" :cy="paths[0][0][1]" r="4" class="route-start" />
      <circle :cx="paths.at(-1).at(-1)[0]" :cy="paths.at(-1).at(-1)[1]" r="4" class="route-end" />
    </g>
  </svg>
</template>
<script setup>
import { computed, useId } from 'vue'
import { projectPoint } from '../services/replayFrameGeometry.js'
const props = defineProps({ trajectory: Object, frame: Object })
const clipId = `torso-route-${useId()}`
const paths = computed(() => props.frame ? (props.trajectory?.segments || []).filter(run => run.length >= 2)
  .map(run => run.filter(p => p.xy?.length === 2 && p.xy.every(Number.isFinite)).map(p => projectPoint(p.xy, props.frame.map))).filter(run => run.length >= 2) : [])
</script>
<style scoped>
.torso-route-end { position:absolute;inset:0;width:100%;height:100%;pointer-events:none;overflow:hidden }
polyline { fill:none;stroke:#75e7ee;stroke-width:3;stroke-linecap:round;stroke-linejoin:round;vector-effect:non-scaling-stroke }
circle { stroke:#172328;stroke-width:2;vector-effect:non-scaling-stroke }.route-start{fill:#f6fbfc}.route-end{fill:#ffd166}
</style>
