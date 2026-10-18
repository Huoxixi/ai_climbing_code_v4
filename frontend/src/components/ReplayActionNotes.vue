<template>
  <section class="action-notes" aria-label="AI 复盘分析">
    <div class="notes-heading"><h2>AI 复盘分析</h2><span>点击动作回看</span></div>
    <p v-if="analysis?.overview">{{analysis.overview}}</p>
    <ol v-if="rows.length" class="commentary-list">
      <li v-for="(row,index) in rows" :key="row.id">
        <button type="button" class="commentary-segment" :class="{current:row.start_seconds<=time && time<row.end_seconds}"
          :aria-current="row.start_seconds<=time && time<row.end_seconds ? 'true' : undefined" @click="$emit('select',row)">
          <span class="action-order">{{ index+1 }}</span>
          <span class="commentary-content"><span class="event-heading"><strong>动作 {{ index+1 }}｜{{ row.title }}</strong><time>{{ seconds(row.start_seconds) }}–{{ seconds(row.end_seconds) }} 秒</time></span>
          <span v-for="(part,partIndex) in row.components" :key="partIndex" class="motion-name">{{ part.text }}</span></span>
          <VideoPlay class="segment-play" aria-hidden="true" />
        </button>
      </li>
    </ol>
    <p v-if="analysis?.priority_focus">{{analysis.priority_focus}}</p>
    <p v-for="(limitation,index) in analysis?.limitations || []" :key="index" class="no-current-action">{{limitation}}</p>
  </section>
</template>

<script setup>
import { computed } from 'vue'
import { VideoPlay } from '@element-plus/icons-vue'
import { actionEventRows } from '../services/replayActionEvents.js'
const props = defineProps({ groups: { type: Array, default: () => [] }, time: { type: Number, default: 0 }, validation: { type: Object, default: null }, analysis:{type:Object,default:null} })
defineEmits(['select'])
const rows = computed(() => props.analysis ? props.analysis.actions.map(row=>({...row,segment_id:row.id,ai:true,components:[row.observation,row.evaluation,row.next_check].filter(Boolean).map(text=>({text}))})) : actionEventRows(props.groups))
const seconds = value => Number(value || 0).toFixed(1)
</script>

<style scoped>
.action-notes{margin:0;padding:20px 24px;background:#1b1e20;color:#f7f8f8}
.notes-heading{display:flex;align-items:baseline;justify-content:space-between;gap:12px;margin-bottom:12px}
h2{margin:0;font-size:15px;font-weight:600}.notes-heading>span,.event-heading time,.event-heading small,.no-current-action{color:#c1c7cb;font-size:13px}
.commentary-list{list-style:none;margin:0;padding:0;max-height:360px;overflow-y:auto;scrollbar-color:#687176 #1b1e20;scrollbar-width:thin}
li+li{border-top:1px solid #3b4246}
.commentary-segment{display:flex;align-items:center;gap:14px;width:100%;min-height:76px;padding:14px 8px;border:0;border-radius:0;background:transparent;color:inherit;text-align:left;cursor:pointer;font:inherit;transition:background-color .16s ease-out}
.commentary-segment:hover{background:#303639}.commentary-segment:active{background:#3b4246}.commentary-segment:focus-visible{outline:2px solid #edcb52;outline-offset:-2px}.commentary-segment.current{background:#303639}
.action-order{min-width:24px;color:#c1c7cb;font-size:13px;font-variant-numeric:tabular-nums}.commentary-content{flex:1;min-width:0}.event-heading{display:flex;align-items:baseline;gap:12px;flex-wrap:wrap}.event-heading strong{font-size:14px}.event-heading time{font-variant-numeric:tabular-nums}.event-heading small{margin-left:auto}
.motion-name{display:block;margin-top:6px;font-size:16px;line-height:1.6;overflow-wrap:anywhere}.segment-play{width:18px;height:18px;flex:none;color:#e3e8eb}.no-current-action{margin:0;line-height:1.6}
.commentary-segment::selection{background:#edcb52;color:#28230e}
@media(max-width:600px){.action-notes{padding:18px 16px}.notes-heading{align-items:flex-start;flex-direction:column;gap:4px}.commentary-segment{gap:8px;padding-inline:4px}.event-heading{gap:4px 10px}.event-heading small{margin-left:0}.commentary-list{max-height:380px}}
@media(prefers-reduced-motion:reduce){.commentary-segment{transition:none}}
</style>
