<template>
  <div class="canvas-wrap">
    <div class="board-frame" :style="frameStyle">
      <div class="dimension-label dimension-label-top">宽 {{ boardSpec.board_width_mm }}mm</div>
      <div class="dimension-label dimension-label-side">高 {{ boardSpec.board_height_mm }}mm</div>
      <div class="dimension-label dimension-label-spacing">孔距 {{ boardSpec.hole_spacing_x_mm }}mm</div>
      <div class="axis axis-x">
        <span v-for="column in columns" :key="column">{{ column }}</span>
      </div>
      <div class="axis axis-y">
        <span v-for="row in rows" :key="row">{{ row }}</span>
      </div>

      <button
        v-for="coord in coords"
        :key="coord"
        class="board-hole"
        :style="getCoordStyle(coord)"
        :title="coord"
        @click="$emit('place', coord)"
      />

      <button
        v-for="hold in baseHolds"
        :key="`setup-${hold.id}`"
        class="placed-hold setup-hold"
        :class="setupClass(hold)"
        :style="{ ...getCoordStyle(hold.id), transform: `translate(-50%, 50%) rotate(${hold.rotation || 0}deg) scale(${hold.scale || 1})` }"
        :title="setupTitle(hold)"
        @click.stop="$emit('select', hold)"
      >
        <img v-if="visualFor(hold).imageUrl" :src="visualFor(hold).imageUrl" alt="" />
        <svg v-else-if="visualFor(hold).svgPath" viewBox="0 0 100 100" aria-hidden="true">
          <path :d="visualFor(hold).svgPath" :fill="shapeColor(hold.hold_type || hold.type)" />
        </svg>
        <span v-else :class="['hold-shape', (hold.hold_type || hold.type || 'Jug').toLowerCase()]" />
        <span v-if="overlayFor(hold)" class="hold-marker-badge">{{ overlayLabel(overlayFor(hold)) }}</span>
      </button>

      <button
        v-if="!baseHolds.length"
        v-for="hold in holds"
        :key="hold.id"
        class="placed-hold"
        :class="{ selected: selectedHold?.id === hold.id, start: hold.is_start, top: isTop(hold.id) }"
        :style="{ ...getCoordStyle(hold.id), transform: `translate(-50%, 50%) rotate(${hold.rotation || 0}deg) scale(${hold.scale || 1})` }"
        :title="hold.id"
        @click.stop="$emit('select', hold)"
      >
        <img v-if="visualFor(hold).imageUrl" :src="visualFor(hold).imageUrl" alt="" />
        <svg v-else-if="visualFor(hold).svgPath" viewBox="0 0 100 100" aria-hidden="true">
          <path :d="visualFor(hold).svgPath" :fill="shapeColor(hold.hold_type || hold.type)" />
        </svg>
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
  baseHolds: { type: Array, default: () => [] },
  routeOverlay: { type: Array, default: () => [] },
  holds: { type: Array, default: () => [] },
  routeSteps: { type: Array, default: () => [] },
  selectedHold: { type: Object, default: null },
  boardSpec: { type: Object, required: true },
  frameStyle: { type: Object, default: () => ({}) },
  getCoordStyle: { type: Function, required: true },
  resolveHoldVisual: { type: Function, required: true },
})

defineEmits(['place', 'select'])

const coords = computed(() => props.rows.flatMap((row) => props.columns.map((column) => `${column}${row}`)))
const overlayByCoord = computed(() => {
  const map = new Map()
  props.routeOverlay.forEach((point) => map.set(point.coord_id, point))
  return map
})

function isTop(id) {
  return props.routeSteps.some((step) => step.hold_id === id && step.is_top)
}

function setupClass(hold) {
  const overlay = overlayFor(hold)
  return {
    lit: Boolean(overlay),
    start: overlay?.role === 'start',
    startHand: overlay?.role === 'start_hand',
    startFoot: overlay?.role === 'start_foot',
    mid: overlay?.role === 'mid',
    top: overlay?.role === 'end',
  }
}

function setupTitle(hold) {
  const overlay = overlayFor(hold)
  const label = {
    start: '起点',
    start_hand: '起点手点',
    start_foot: '起点脚点',
    mid: '中间点',
    end: '终点',
  }[overlay?.role] || overlay?.role
  return overlay ? `${hold.id} ${label} LED ${overlay.led_index}` : hold.id
}

function overlayFor(hold) {
  return overlayByCoord.value.get(hold.id)
}

function overlayLabel(overlay) {
  return {
    start: '起',
    start_hand: '手',
    start_foot: '脚',
    mid: '线',
    end: '顶',
  }[overlay?.role] || '点'
}

function visualFor(hold) {
  const resolved = props.resolveHoldVisual(hold)
  return {
    svgPath: hold.svgPath || resolved.svgPath,
    imageUrl: hold.imageUrl || resolved.imageUrl,
  }
}

function shapeColor(type) {
  return { Jug: '#24876b', Crimp: '#d94b52', Sloper: '#c8912f', Pinch: '#7457d8', Pocket: '#2f72c8', Foot: '#718096' }[type] || '#24876b'
}
</script>
