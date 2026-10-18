import {createApp,h} from 'vue'
import LocalClimbReplayPage from '../src/components/LocalClimbReplayPage.vue'
import LocalSettingsPage from '../src/components/LocalSettingsPage.vue'
createApp({setup:()=>()=>h('main',[h(LocalClimbReplayPage),h(LocalSettingsPage)])}).provide('pilotAccess',{session:{username:'test',authEnabled:false},logout:async()=>{}}).mount('#app')
