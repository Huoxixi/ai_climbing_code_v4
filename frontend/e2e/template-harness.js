import { createApp, h, ref } from 'vue'
import ReplayCoachingPanel from '../src/components/ReplayCoachingPanel.vue'
import '../src/styles/tokens.css'

const job = ref({ id: 'template-a', status: 'succeeded', video: { duration_seconds: 30 }, result: {}, media: { source_video: { status: 'available' } } })
window.templateHarness = { setJob: value => { job.value = value } }
createApp({ setup: () => () => h('main', { style: 'max-width:900px;margin:24px auto;background:var(--ui-surface)' }, [
  h('p', { style: 'padding:16px 24px 0;color:var(--ui-ink-muted);font-size:13px' }, '构造资料 · 仅检查交互，不代表真实分析或视觉验收'),
  h(ReplayCoachingPanel, { job: job.value, mediaAvailable: true }),
]) }).mount('#app')
document.body.style.cssText = 'margin:0;background:var(--ui-ground)'
