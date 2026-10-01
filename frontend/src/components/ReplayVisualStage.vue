<template>
  <div class="replay-cinema" :class="{ 'showing-summary': summary }">
    <video ref="video" :src="src" controls playsinline preload="metadata" aria-label="攀爬复盘视频"
      @timeupdate="$emit('timeupdate')" @seeking="$emit('seeking')" @seeked="$emit('seeked')"
      @ended="$emit('ended')" @loadedmetadata="$emit('loadedmetadata')" @play="$emit('play')"
      @pause="$emit('pause')" @error="$emit('error')" />
    <slot />
  </div>
</template>

<script setup>
import { ref } from 'vue'
defineProps({ src: String, summary: Boolean })
defineEmits(['timeupdate', 'seeking', 'seeked', 'ended', 'loadedmetadata', 'play', 'pause', 'error'])
const video = ref(null)
defineExpose({ video })
</script>

<style scoped>
.replay-cinema { position: relative; background: #070b0e; }
video { display: block; width: 100%; max-height: 74vh; object-fit: contain; transition: filter .35s ease-out; }
.showing-summary video { filter: blur(12px) brightness(.35); }
@media(max-width:650px) { video { max-height: 61vh; } }
@media(prefers-reduced-motion:reduce) { video { transition: none; } }
</style>
