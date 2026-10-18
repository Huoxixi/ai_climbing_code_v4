import { createApp, h, ref } from 'vue'
import ReplayHoldEditor from '../src/components/ReplayHoldEditor.vue'
import '../src/styles/tokens.css'
const job=ref({id:'editor-fixture',video:{duration_seconds:8,fps:24},hold_draft:{holds:[],hold_evidence:{reference_frame:0}}})
window.holdEditorHarness={saved:[],closed:0}
createApp({setup:()=>()=>h(ReplayHoldEditor,{job:job.value,onSaved:value=>{window.holdEditorHarness.saved.push(value);job.value=value},onClose:()=>window.holdEditorHarness.closed++})}).mount('#app')
document.body.style.cssText='margin:0;padding:16px;background:var(--ui-surface);font-family:var(--ui-font-body,sans-serif)'
document.querySelector('main').style.cssText='max-width:980px;margin:auto'
