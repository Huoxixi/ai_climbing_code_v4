<template>
  <section class="action-notes" aria-label="当前动作解析">
    <h2>动作解析</h2>
    <template v-if="explanation">
      <article v-for="entry in explanation.entries" :key="entry.key" class="caption-event">
        <div class="event-heading"><h3 class="limb-name">{{ entry.limb }}</h3><span class="source-clock">{{ seconds(entry.start_seconds) }}–{{ seconds(entry.end_seconds) }} 秒</span></div>
        <p class="motion-name">{{ shortActionLabel(entry, time) }}</p>
      </article>
    </template>
    <p v-else class="no-current-action">播放到动作时显示解析。</p>
  </section>
</template>

<script setup>
import { computed } from 'vue'
import { currentExplanation, shortActionLabel } from '../services/replayPresentation.js'
const props = defineProps({ groups: { type: Array, default: () => [] }, time: { type: Number, default: 0 } })
const explanation = computed(() => currentExplanation(props.groups, props.time))
const seconds = value => Number(value || 0).toFixed(1)
</script>

<style scoped>
.action-notes { margin: 20px 16px; padding: 0 0 20px; border-bottom: 1px solid #465057; }
.event-heading { display: flex; align-items: baseline; justify-content: space-between; gap: 12px; }
h2 { margin: 0; font-size: 18px; font-weight: 650; }
.source-clock, .no-current-action { color: #c1c7cb; font-size: 13px; }
.source-clock { font-variant-numeric: tabular-nums; }
.caption-event { margin-top: 16px; }
.caption-event + .caption-event { padding-top: 16px; border-top: 1px solid #30363a; }
.limb-name { margin: 0; font-size: 20px; font-weight: 650; }
.motion-name { margin: 6px 0 0; font-size: 22px; font-weight: 600; line-height: 1.5; overflow-wrap: anywhere; }
.no-current-action { margin: 10px 0 0; line-height: 1.6; }
@media(max-width:480px) { .event-heading { flex-wrap: wrap; gap: 4px 12px; } }
</style>
