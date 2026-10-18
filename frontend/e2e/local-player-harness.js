import {createApp,h,ref} from 'vue'
import '../src/styles/local-app.css'
import LocalReplayPlayer from '../src/components/LocalReplayPlayer.vue'
const job=ref(null)
window.localPlayerHarness={setJob:value=>{job.value=value}}
createApp({setup:()=>()=>job.value?h(LocalReplayPlayer,{job:job.value}):null}).mount('#app')
