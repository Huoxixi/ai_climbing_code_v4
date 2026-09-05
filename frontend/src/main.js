import { createApp } from 'vue'
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
import './style.css'
import './styles/tokens.css'
import './styles/base.css'
import './styles/redesign.css'
import RootApp from './RootApp.vue'

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
