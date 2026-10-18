<template>
  <Teleport to="body">
    <dialog ref="dialog" class="workspace-sheet workspace-boulder" :aria-label="title" @cancel.prevent="$emit('close')">
      <header><h2>{{ title }}</h2><button type="button" aria-label="关闭面板" @click="$emit('close')"><Close aria-hidden="true" /></button></header>
      <TaskPanel :title="title"><slot /><template v-if="$slots.footer" #footer><slot name="footer" /></template></TaskPanel>
    </dialog>
  </Teleport>
</template>
<script setup>
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { Close } from '@element-plus/icons-vue'
import TaskPanel from './TaskPanel.vue'
defineProps({ title: { type: String, required: true } })
defineEmits(['close'])
const dialog = ref(null)
let previous
onMounted(() => { previous = document.activeElement; dialog.value.showModal() })
onBeforeUnmount(() => { dialog.value?.close(); if (previous?.isConnected) previous.focus({ preventScroll: true }) })
</script>
<style scoped>
.workspace-sheet{position:fixed;inset:0 20px 0 auto;margin:auto 0;width:min(560px,calc(100vw - 40px));height:min(720px,calc(100dvh - 40px));max-height:calc(100dvh - 40px);padding:0;border:0;border-radius:12px;background:var(--ui-surface);color:var(--ui-ink);box-shadow:0 18px 56px #10191040;overflow:visible}
.workspace-sheet[open]{display:flex;flex-direction:column}.workspace-sheet::backdrop{background:#10191450}
.workspace-sheet>header{flex:none;display:flex;align-items:center;justify-content:space-between;gap:16px;padding:12px 16px;border-bottom:1px solid var(--ui-line)}
.workspace-sheet h2{margin:0;font-size:18px}.workspace-sheet>header button{width:44px;height:44px;display:grid;place-items:center;border:1px solid var(--ui-line);border-radius:8px;background:var(--ui-surface)}.workspace-sheet>header svg{width:20px;height:20px}
.workspace-sheet>.task-panel{flex:1;border:0;min-height:0}.workspace-sheet :deep(.task-panel__heading){display:none}
@media(max-width:1099px){.workspace-sheet{overflow:auto}.workspace-sheet>.task-panel{flex:none}}
</style>
