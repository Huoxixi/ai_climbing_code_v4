<template>
  <div class="hold-preview">
    <img v-if="mode === 'image' && hold.imageUrl" :src="hold.imageUrl" alt="" />
    <svg v-else-if="hold.svgPath" viewBox="0 0 100 100" aria-hidden="true">
      <path :d="hold.svgPath" :fill="color" />
    </svg>
    <span v-else :class="['hold-shape', hold.hold_type?.toLowerCase() || 'jug']" />
  </div>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  hold: { type: Object, required: true },
  mode: { type: String, default: 'vector' },
})

const color = computed(() => ({
  Jug: '#24876b',
  Crimp: '#d94b52',
  Sloper: '#c8912f',
  Pinch: '#7457d8',
  Pocket: '#2f72c8',
  Foot: '#718096',
}[props.hold.hold_type] || '#24876b'))
</script>
