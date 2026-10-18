<template>
  <Teleport to="body">
    <dialog ref="dialog" class="boulder-editor workspace-boulder" aria-label="单帧精修" @keydown="keepFocus" @cancel.prevent="$emit('cancel')"><slot /></dialog>
  </Teleport>
</template>
<script setup>
import { onBeforeUnmount, onMounted, ref } from 'vue'
defineEmits(['cancel'])
const dialog = ref(null)
let opener
function keepFocus(event) {
  if (event.key !== 'Tab') return
  const controls = [...dialog.value.querySelectorAll('button:not(:disabled),input:not(:disabled),select:not(:disabled),textarea:not(:disabled),a[href],[tabindex]:not([tabindex="-1"])')].filter(el => el.getClientRects().length && !el.closest('[inert]'))
  const index = controls.indexOf(document.activeElement)
  if (!controls.length) { event.preventDefault(); dialog.value.focus(); return }
  if (index < 0 || (event.shiftKey ? index === 0 : index === controls.length - 1)) {
    event.preventDefault()
    controls[event.shiftKey ? controls.length - 1 : 0].focus({ preventScroll: true })
  }
}
onMounted(() => { opener = document.activeElement; dialog.value.showModal() })
onBeforeUnmount(() => { dialog.value?.close(); if (opener?.isConnected) opener.focus({ preventScroll: true }) })
</script>
<style scoped>
dialog{margin:0;border:0;width:100vw;max-width:none;height:calc(100dvh - 56px);max-height:none;color:inherit}
dialog::backdrop{background:transparent}
</style>
