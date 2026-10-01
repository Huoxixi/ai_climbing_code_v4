<template>
  <section class="action-detail" aria-label="动作详情与修正">
    <label v-if="events.length > 1" class="event-choice">选择动作
      <select v-model="eventIndex" aria-label="选择动作"><option v-for="(event, i) in events" :key="event.id" :value="i">{{ limbs[event.limb] }} · {{ shortActionLabel(event) }}</option><option :value="-1">补充新动作</option></select>
    </label>
    <button v-else-if="events.length" type="button" class="new-action" @click="eventIndex = current ? -1 : 0">{{ current ? '补充新动作' : '返回当前动作' }}</button>
    <template v-if="current">
      <details v-if="sourceEvidence.length || current.facts?.length || current.technique_tags?.length || current.relations?.length" class="contact-evidence">
        <summary>查看接触与技术证据</summary>
        <div class="evidence-links" aria-label="动作证据"><button v-for="frame in sourceEvidence" :key="frame.frame_id" type="button" @click="$emit('locate', frame.time_seconds)">回看 {{ frame.time_seconds.toFixed(2) }} 秒</button></div>
        <p v-for="relation in current.relations || []" :key="relation.id">{{ relation.name }}{{ relation.status === 'candidate' ? '（候选）' : '（接触或时序关系）' }}</p>
        <div v-for="fact in current.facts || []" :key="`${fact.kind}-${fact.hold_id}`">
          <p>{{ factNames[fact.kind] }}{{ fact.hold_id ? ` · 岩点 ${fact.hold_id}` : '' }} · {{ fact.status === 'human_confirmed' ? '人工确认' : '局部画面核对' }}</p>
          <div class="evidence-links"><button v-for="frame in fact.evidence || []" :key="frame.frame_id" type="button" @click="$emit('locate', frame.time_seconds)">回看 {{ frame.time_seconds.toFixed(2) }} 秒</button></div>
        </div>
        <div v-for="tag in current.technique_tags || []" :key="tag.code">
          <p>{{ tag.name }} · {{ tag.status === 'human_confirmed' ? '人工确认' : '候选' }}</p>
          <div class="evidence-links"><button v-for="frame in tag.evidence || []" :key="frame.frame_id" type="button" @click="$emit('locate', frame.time_seconds)">回看 {{ frame.time_seconds.toFixed(2) }} 秒</button></div>
        </div>
      </details>
    </template>
      <form @submit.prevent="save">
        <div class="fields">
          <label>肢体<select v-model="form.limb" aria-label="修正肢体"><option v-for="(name, code) in limbs" :key="code" :value="code">{{ name }}</option></select></label>
          <label>动作<select v-model="form.action" aria-label="修正动作"><option v-for="(name, code) in actions" :key="code" :value="code">{{ name }}</option></select></label>
          <label>开始秒数<input v-model.number="form.start_seconds" aria-label="动作开始秒数" type="number" step="any" :min="group.start_seconds" :max="group.end_seconds" required /></label>
          <label>结束秒数<input v-model.number="form.end_seconds" aria-label="动作结束秒数" type="number" step="any" :min="group.start_seconds" :max="group.end_seconds" required /></label>
          <label>原岩点<select v-model="form.source_hold_id" aria-label="原岩点"><option value="">未确认</option><option v-for="hold in holds" :key="hold.id" :value="String(hold.id)">{{ hold.id }}</option></select></label>
          <label>目标岩点<select v-model="form.target_hold_id" aria-label="目标岩点"><option value="">未确认</option><option v-for="hold in holds" :key="hold.id" :value="String(hold.id)">{{ hold.id }}</option></select></label>
          <label>接触或离点秒数<input v-model.number="form.contact_seconds" aria-label="接触或离点秒数" type="number" step="any" :min="form.start_seconds" :max="form.end_seconds" /></label>
          <label>方向<select v-model="form.direction" aria-label="动作方向"><option value="">未确认</option><option value="up">向上</option><option value="down">向下</option><option value="left">向左</option><option value="right">向右</option></select></label>
        </div>
        <p class="hint">时间按原片计算；岩点选“未确认”会清除该接触判断。</p>
        <details class="technique-editor"><summary>技术标签</summary><fieldset><legend>人工确认</legend><label v-for="tag in vocabulary.techniques || []" :key="tag.code"><input v-model="form.technique_codes" type="checkbox" :value="tag.code" />{{ tag.name }}</label></fieldset></details>
        <label class="confirmation"><input v-model="confirmed" type="checkbox" />我已观看这段原片，确认填写的动作及接触</label>
        <button type="submit" :disabled="disabled || !confirmed">保存动作修正</button>
      </form>
    <button type="button" :disabled="disabled || !revisionCount" @click="$emit('undo')">撤销上一次动作修正</button>
  </section>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { shortActionLabel } from '../services/replayPresentation.js'
const props = defineProps({ group: { type: Object, required: true }, holds: { type: Array, default: () => [] }, vocabulary: { type: Object, default: () => ({}) }, disabled: Boolean, revisionCount: Number })
const emit = defineEmits(['save', 'undo', 'locate'])
const eventIndex = ref(0), form = ref({}), confirmed = ref(false)
const events = computed(() => props.group.events || [])
const current = computed(() => events.value[eventIndex.value] || null)
const sourceEvidence = computed(() => current.value?.evidence_status === 'trajectory_observed' ? [] : current.value?.evidence || [])
const limbs = { left_hand: '左手', right_hand: '右手', left_foot: '左脚', right_foot: '右脚' }
const factNames = { source_contact: '开始时接触', target_contact: '接到目标', release: '接触结束', readjust: '原点调整', attempt: '触及后未保留接触', wall_contact: '接触墙面' }
const actions = computed(() => ({ move_up: form.value.limb?.endsWith('hand') ? '向上伸手' : '抬脚', move: '换点过程', adjust: '位置调整', reach: '靠近目标', lift: '抬起肢体', contact: '建立目标接触', release: '离点', readjust: '原点重新抓握或踩放', attempt: '触点后未保留接触', wall_contact: '接触墙面' }))
function reset() {
  const event = current.value
  form.value = { limb: event?.limb || 'left_hand', action: event?.action || 'reach',
    start_seconds: event?.start_seconds ?? props.group.start_seconds, end_seconds: event?.end_seconds ?? props.group.end_seconds,
    source_hold_id: event?.source_hold_id || event?.facts?.find(f => f.kind === 'source_contact')?.hold_id || '',
    target_hold_id: event?.target_hold_id || '', contact_seconds: event?.facts?.find(f => f.kind === 'target_contact')?.start_seconds ?? event?.end_seconds ?? props.group.end_seconds,
    direction: event?.direction || '', technique_codes: (event?.technique_tags || []).filter(t => t.status === 'human_confirmed').map(t => t.code) }
  confirmed.value = false
}
watch(() => props.group.id, () => { eventIndex.value = events.value.length ? 0 : -1; reset() }, { immediate: true })
watch(current, reset)
watch(form, () => { confirmed.value = false }, { deep: true })
function save() {
  if (!confirmed.value || props.disabled) return
  emit('save', { ...form.value, group_id: props.group.id, event_id: current.value?.id || null,
    source_hold_id: form.value.source_hold_id || null, target_hold_id: form.value.target_hold_id || null,
    contact_seconds: form.value.contact_seconds === '' ? null : form.value.contact_seconds, direction: form.value.direction || null })
}
</script>

<style scoped>
.action-detail { padding: 0 0 18px; line-height: 1.6; }
p { margin: 8px 0; }
.hint { color: #c1c7cb; }
.event-choice { display: flex; flex-direction: column; gap: 4px; margin-bottom: 16px; }
.new-action { margin-bottom: 16px; }
.fields { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }
.fields label { display: flex; flex-direction: column; gap: 4px; }
input, select, button { font: inherit; color: inherit; background: #30363a; border: 1px solid #59646b; border-radius: 5px; }
input, select { min-width: 0; padding: 8px; min-height: 44px; box-sizing: border-box; }
input[type=checkbox] { min-height: 20px; }
button { min-height: 44px; padding: 8px 12px; cursor: pointer; margin: 8px 6px 0 0; }
button:disabled { opacity: .45; cursor: default; }
button:focus-visible, input:focus-visible, select:focus-visible, summary:focus-visible { outline: 2px solid #7cdee5; outline-offset: 3px; }
fieldset { display: flex; flex-wrap: wrap; gap: 10px 16px; margin: 16px 0; border: 1px solid #59646b; }
fieldset label, .confirmation { display: flex; align-items: center; gap: 8px; min-height: 44px; }
summary { cursor: pointer; padding: 12px 0; }
.evidence-links { display: flex; flex-wrap: wrap; }
@media(max-width:480px) { .fields { grid-template-columns: 1fr; } }
</style>
