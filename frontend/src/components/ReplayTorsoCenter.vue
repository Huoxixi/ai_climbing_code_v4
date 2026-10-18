<template>
  <svg v-if="point && frame" class="torso-center-overlay" :viewBox="`0 0 ${frame.width} ${frame.height}`" preserveAspectRatio="xMidYMid meet" role="img" aria-label="估算重心">
    <title>估算重心（二维投影）</title>
    <circle :cx="frame.rect[0] + point[0] * frame.rect[2]" :cy="frame.rect[1] + point[1] * frame.rect[3]"
      :r="Math.max(4, Math.round(Math.min(frame.width, frame.height) * .009))" fill="white" stroke="#0d1012" stroke-width="2" />
  </svg>
</template>

<script setup>
defineProps({ point: Array, frame: Object })
</script>

<style scoped>
.torso-center-overlay { position: absolute; inset: 0; width: 100%; height: 100%; pointer-events: none; }
</style>
