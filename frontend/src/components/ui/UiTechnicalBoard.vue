<template>
  <div
    class="ui-technical-board"
    :class="{ compact }"
    role="img"
    :aria-label="`${label}，${boardWidthMm} × ${boardHeightMm} 毫米，中性技术画布骨架`"
  >
    <span class="ui-board-dimension ui-board-dimension-top">宽 {{ boardWidthMm }} mm</span>
    <span class="ui-board-dimension ui-board-dimension-side">高 {{ boardHeightMm }} mm</span>
    <div class="ui-technical-board-face" :style="boardStyle">
      <span v-for="index in holeCount" :key="index" class="ui-technical-hole" />
    </div>
    <span class="ui-board-caption">{{ label }}</span>
  </div>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  columns: { type: Number, default: 11 },
  rows: { type: Number, default: 18 },
  boardWidthMm: { type: Number, default: 2440 },
  boardHeightMm: { type: Number, default: 3660 },
  label: { type: String, default: '11 × 18 技术画布' },
  compact: { type: Boolean, default: false },
})

const holeCount = computed(() => props.columns * props.rows)
const boardStyle = computed(() => ({
  '--ui-board-columns': props.columns,
  '--ui-board-rows': props.rows,
  '--ui-board-ratio': `${props.boardWidthMm} / ${props.boardHeightMm}`,
}))
</script>
