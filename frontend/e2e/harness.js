import { createApp } from 'vue'
import { ElButton } from 'element-plus'
import 'element-plus/dist/index.css'
import '../src/style.css'
import '../src/styles/tokens.css'
import '../src/styles/base.css'
import '../src/styles/redesign.css'
import Harness from './Harness.vue'

createApp(Harness).use(ElButton).mount('#app')
