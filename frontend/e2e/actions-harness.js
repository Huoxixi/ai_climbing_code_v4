import { createApp, h, ref } from 'vue'
import UnifiedReplayPlayer from '../src/components/UnifiedReplayPlayer.vue'
const job = ref({ id: 'actions-a', status: 'succeeded', media: { source_video: { status: 'available' } }, result: { video: { duration_seconds: 14.266667 } } })
window.actionsHarness = { setJob: value => { job.value = value } }
createApp({ setup: () => () => h('main', { style: 'max-width:800px;margin:16px auto' }, [
  h(UnifiedReplayPlayer, { job: job.value, legacyUrl: '/api/climb-replay/jobs/actions-a/overlay-video' }),
]) }).mount('#app')
document.body.style.cssText = 'margin:0;background:#eef1ee;font-family:sans-serif'
