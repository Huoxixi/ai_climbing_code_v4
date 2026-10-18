import { createApp, h } from 'vue'
import ReplayVisionSettings from '../src/components/ReplayVisionSettings.vue'
import '../src/styles/tokens.css'
createApp({render:()=>h('main',{style:'max-width:850px;margin:20px auto'},h(ReplayVisionSettings))}).mount('#app')
