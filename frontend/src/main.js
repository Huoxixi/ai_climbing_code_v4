import { createApp, defineAsyncComponent } from 'vue'
import {
  ElAlert,
  ElButton,
  ElCheckbox,
  ElCheckboxGroup,
  ElCollapse,
  ElCollapseItem,
  ElDrawer,
  ElForm,
  ElFormItem,
  ElInput,
  ElInputNumber,
  ElOption,
  ElOptionGroup,
  ElPagination,
  ElRate,
  ElSegmented,
  ElSelect,
  ElSkeleton,
  ElSlider,
  ElTable,
  ElTableColumn,
  ElTabPane,
  ElTabs,
  ElUpload,
} from 'element-plus'
import 'element-plus/dist/index.css'
if (import.meta.env.VITE_LOCAL_BOULDER_ONLY === 'true') {
  await import('./styles/local-app.css')
} else {
  await import('./styles/full-app.css')
}
import LocalRoot from './LocalRoot.vue'
import { isLocalWorkspace } from './utils/localWorkspace.js'
const RootApp = import.meta.env.VITE_LOCAL_BOULDER_ONLY === 'true' ? LocalRoot : (isLocalWorkspace(window) ? LocalRoot : defineAsyncComponent(() => import('./RootApp.vue')))

const app = createApp(RootApp)
const elementComponents = [
  ElAlert,
  ElButton,
  ElCheckbox,
  ElCheckboxGroup,
  ElCollapse,
  ElCollapseItem,
  ElDrawer,
  ElForm,
  ElFormItem,
  ElInput,
  ElInputNumber,
  ElOption,
  ElOptionGroup,
  ElPagination,
  ElRate,
  ElSegmented,
  ElSelect,
  ElSkeleton,
  ElSlider,
  ElTable,
  ElTableColumn,
  ElTabPane,
  ElTabs,
  ElUpload,
]

elementComponents.forEach((component) => app.use(component))
app.mount('#app')
