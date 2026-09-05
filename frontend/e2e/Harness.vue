<template>
  <AppShell :active="active" :title="active === 'photo-routes' ? '抱石线路' : '岩板'" :board-label="active === 'photo-routes' ? '6.2 × 4.1 m · 30×20' : '2440 × 3660 mm'" @update:active="changePage">
    <PhotoRoutesV2Page v-if="active === 'photo-routes'" ref="photoPage" />
    <section v-else-if="active === 'studio'" class="studio-page">
      <div class="command-bar">定线 · 标准训练板</div>
      <div class="studio-layout"><aside class="tool-panel desktop-studio-tool">岩点工具</aside><div class="studio-canvas-wrap"><div class="canvas-heading">岩板</div><BoardCanvas v-bind="canvasProps" /></div><aside class="inspector desktop-studio-inspector">线路信息</aside></div>
    </section>
    <section v-else-if="active === 'standard-board'" class="page standard-board-page">
      <h1>板库</h1><div class="standard-board-layout"><aside>标准训练板</aside><div class="standard-preview-canvas"><BoardCanvas v-bind="canvasProps" readonly /></div></div>
    </section>
    <section v-else class="page">资产与其他模块</section>
  </AppShell>
</template>

<script setup>
import { provide, reactive, ref } from 'vue'
import AppShell from '../src/components/AppShell.vue'
import PhotoRoutesV2Page from '../src/components/PhotoRoutesV2Page.vue'
import BoardCanvas from '../src/components/BoardCanvas.vue'
import { boardViewModel } from '../src/utils/boardComparison.js'

const active = ref('photo-routes'), photoPage = ref(null)
const readOnly = new URLSearchParams(location.search).has('readonly')
provide('pilotAccess', { session:reactive({ authEnabled:readOnly, displayName:'本地验收' }), lease:reactive({ ownedByMe:!readOnly }), acquireLease:() => {}, releaseLease:() => {} })
const model = boardViewModel({})
const canvasProps = { boardSpec:model.spec, columns:model.columns, rows:model.rows, frameStyle:model.frameStyle, getCoordStyle:model.getCoordStyle, resolveHoldVisual:() => ({}) }
async function changePage(value) {
  if (active.value === 'photo-routes' && !(await photoPage.value.beforeLeave())) return
  active.value = value
}
</script>
