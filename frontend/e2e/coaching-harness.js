import { createApp, h, ref } from 'vue'
import ReplayCoachingPanel from '../src/components/ReplayCoachingPanel.vue'
import ClimbReplayPage from '../src/components/ClimbReplayPage.vue'
import '../src/styles/tokens.css'

const job = ref({ id: 'fixture-a', status: 'succeeded', video: { duration_seconds: 30 }, result: {} })
const mediaAvailable = ref(true)
const lastSeek = ref(null)
const visible = ref(true)
const parentMode = new URLSearchParams(location.search).has('parent')
window.coachingHarness = { setJob: value => { job.value = value }, setMedia: value => { mediaAvailable.value = value }, hide: () => { visible.value = false } }
createApp({ setup: () => () => h('main', { style: 'max-width:900px;margin:0 auto;background:var(--ui-surface)' }, [
  parentMode ? h(ClimbReplayPage) : visible.value ? h(ReplayCoachingPanel, { job: job.value, mediaAvailable: mediaAvailable.value, onSeek: value => { lastSeek.value = value } }) : null,
  h('output', { id: 'last-seek', style: 'display:none' }, JSON.stringify(lastSeek.value)),
]) }).mount('#app')
document.body.style.cssText = 'margin:0;background:var(--ui-ground)'
