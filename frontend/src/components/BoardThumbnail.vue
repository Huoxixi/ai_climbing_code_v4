<template>
  <div class="board-thumbnail" :style="frameStyle" role="img" :aria-label="`${label}，${holds.length} 个岩点`">
    <span
      v-for="coord in coords"
      :key="`hole-${coord}`"
      class="board-thumbnail-hole"
      :style="getCoordStyle(coord)"
    />
    <span
      v-for="hold in holds"
      :key="hold.id"
      class="board-thumbnail-hold"
      :style="{ ...getCoordStyle(hold.id), transform: `translate(-50%, 50%) rotate(${hold.rotation || 0}deg) scale(${hold.scale || 1})` }"
    >
      <img v-if="visualFor(hold).imageUrl" :src="visualFor(hold).imageUrl" alt="" />
      <svg v-else-if="visualFor(hold).svgPath" viewBox="0 0 100 100" aria-hidden="true">
        <path :d="visualFor(hold).svgPath" :fill="shapeColor(hold.hold_type || hold.type)" />
      </svg>
      <i v-else :style="{ background: shapeColor(hold.hold_type || hold.type) }" />
    </span>
    <span class="board-thumbnail-caption">{{ label }}</span>
  </div>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  label: { type: String, default: '当前岩板' },
  columns: { type: Array, default: () => Array.from({ length: 11 }, (_, index) => String.fromCharCode(65 + index)) },
  rows: { type: Array, default: () => Array.from({ length: 18 }, (_, index) => index + 1) },
  holds: { type: Array, default: () => [] },
  frameStyle: { type: Object, default: () => ({}) },
  getCoordStyle: { type: Function, required: true },
  resolveHoldVisual: { type: Function, required: true },
})

const coords = computed(() => props.rows.flatMap((row) => props.columns.map((column) => `${column}${row}`)))

function visualFor(hold) {
  const resolved = props.resolveHoldVisual(hold) || {}
  return { imageUrl: resolved.imageUrl || hold.imageUrl, svgPath: resolved.svgPath || hold.svgPath }
}

function shapeColor(type) {
  return { Jug: '#287a5b', Crimp: '#c94b4b', Sloper: '#c69027', Pinch: '#7053bf', Pocket: '#326ca8', Foot: '#70757d' }[type] || '#287a5b'
}
</script>
