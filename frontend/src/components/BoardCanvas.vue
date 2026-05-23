<template>
  <div class="canvas-wrap">
    <div class="board-frame" :style="frameStyle">
      <div class="axis axis-x">
        <span v-for="column in columns" :key="column">{{ column }}</span>
      </div>
      <div class="axis axis-y">
        <span v-for="row in rows" :key="row">{{ row }}</span>
      </div>

      <button
        v-for="row in rows"
        :key="`row-${row}`"
        v-show="false"
      />
      <button
        v-for="coord in coords"
        :key="coord"
        class="board-hole"
        :style="getCoordStyle(coord)"
        :title="coord"
        @click="$emit('place', coord)"
      />

      <button
        v-for="hold in holds"
        :key="hold.id"
        class="placed-hold"
        :class="{ selected: selectedHold?.id === hold.id, start: hold.is_start, top: isTop(hold.id) }"
        :style="{ ...getCoordStyle(hold.id), transform: `translate(-50%, 50%) rotate(${hold.rotation || 0}deg) scale(${hold.scale || 1})` }"
        @click.stop="$emit('select', hold)"
      >
        <svg v-if="resolveHoldVisual(hold).svgPath" viewBox="0 0 100 100" aria-hidden="true">
          <path :d="resolveHoldVisual(hold).svgPath" :fill="shapeColor(hold.hold_type || hold.type)" />
        </svg>
        <img v-else-if="resolveHoldVisual(hold).imageUrl" :src="resolveHoldVisual(hold).imageUrl" alt="" />
        <span v-else :class="['hold-shape', (hold.hold_type || hold.type || 'Jug').toLowerCase()]" />
      </button>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  columns: { type: Array, required: true },
  rows: { type: Array, required: true },
  holds: { type: Array, default: () => [] },
  routeSteps: { type: Array, default: () => [] },
  selectedHold: { type: Object, default: null },
  frameStyle: { type: Object, default: () => ({}) },
  getCoordStyle: { type: Function, required: true },
  resolveHoldVisual: { type: Function, required: true },
})

defineEmits(['place', 'select'])

const coords = computed(() => props.rows.flatMap((row) => props.columns.map((column) => `${column}${row}`)))

function isTop(id) {
  return props.routeSteps.some((step) => step.hold_id === id && step.is_top)
}

function shapeColor(type) {
  return { Jug: '#43b284', Crimp: '#e45c5c', Sloper: '#d7a84f', Pinch: '#9a7ae6', Pocket: '#4b8fd9', Foot: '#8ea2b5' }[type] || '#43b284'
}
</script>
