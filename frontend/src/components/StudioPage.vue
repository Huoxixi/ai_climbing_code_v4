<template>
  <section class="studio-page">
    <div class="command-bar">
      <div class="studio-board-context"><strong>{{ studio.currentBoard.route_name || '未命名岩板' }}</strong><span>{{ studio.currentBoardSpec.cellLabel }} · {{ studio.placedHolds.length }} 岩点</span></div>
      <el-select v-model="studio.activeBoardPresetId" class="preset-select" aria-label="岩板规格" @change="studio.applyBoardPreset">
        <el-option v-for="template in studio.boardPresets" :key="template.id" :label="`${template.label} (${template.cellLabel})`" :value="template.id" />
      </el-select>
      <div class="command-bar-actions"><el-button :icon="Plus" @click="$emit('new-board')">新建</el-button><el-button :icon="Delete" @click="studio.clearBoard">清空</el-button><el-button type="primary" :loading="boards.loading" :icon="DocumentChecked" @click="$emit('save-board')">保存岩板</el-button></div>
    </div>

    <div class="studio-layout">
      <aside class="tool-panel desktop-studio-tool"><HoldPalette :studio="studio" :library="library" /></aside>
      <div class="studio-canvas-wrap">
        <div class="canvas-heading"><span>当前画布</span><small>选择岩点后点击孔位放置</small></div>
        <BoardCanvas :columns="studio.coordinateColumns" :rows="studio.coordinateRows" :holds="studio.placedHolds" :route-steps="studio.routeSteps" :selected-hold="studio.selectedHold" :board-spec="studio.currentBoardSpec" :frame-style="studio.boardFrameStyle" :get-coord-style="studio.getCoordStyle" :resolve-hold-visual="library.resolveHoldVisual" @place="studio.placeHold" @select="$emit('select-hold', $event)" />
      </div>
      <InspectorPanel class="desktop-studio-inspector" active-section="all" :board="studio.currentBoard" :selected-hold="studio.selectedHold" :route-steps="studio.routeSteps" :beta-form="studio.betaForm" :hold-types="library.holdTypes" @update-hold="studio.updateSelectedHold" @delete-hold="studio.deleteSelectedHold" @add-beta="studio.addBetaStep" @delete-beta="studio.deleteBetaStep" @dirty="studio.markUnsaved" />
    </div>

    <div class="studio-mobile-dock" aria-label="定线工具">
      <button type="button" @click="openDrawer('holds')"><Collection /><span>岩点</span></button>
      <button type="button" @click="openDrawer('hold')"><Operation /><span>属性</span></button>
      <button type="button" @click="openDrawer('beta')"><List /><span>Beta</span></button>
      <button type="button" class="save" @click="$emit('save-board')"><DocumentChecked /><span>保存</span></button>
    </div>

    <el-drawer v-model="drawerOpen" direction="btt" size="72%" :title="drawerTitle" append-to-body class="studio-tool-drawer">
      <HoldPalette v-if="drawerSection === 'holds'" :studio="studio" :library="library" />
      <InspectorPanel v-else :active-section="drawerSection" :board="studio.currentBoard" :selected-hold="studio.selectedHold" :route-steps="studio.routeSteps" :beta-form="studio.betaForm" :hold-types="library.holdTypes" @update-hold="studio.updateSelectedHold" @delete-hold="studio.deleteSelectedHold" @add-beta="studio.addBetaStep" @delete-beta="studio.deleteBetaStep" @dirty="studio.markUnsaved" />
    </el-drawer>
  </section>
</template>

<script setup>
import { computed, defineComponent, h, ref, resolveComponent } from 'vue'
import { Collection, Delete, DocumentChecked, List, Operation, Plus, Search } from '@element-plus/icons-vue'
import BoardCanvas from './BoardCanvas.vue'
import HoldPreview from './HoldPreview.vue'
import InspectorPanel from './InspectorPanel.vue'

const props = defineProps({ studio: { type: Object, required: true }, boards: { type: Object, required: true }, library: { type: Object, required: true } })
defineEmits(['new-board', 'save-board', 'select-hold'])
const drawerOpen = ref(false)
const drawerSection = ref('holds')
const drawerTitle = computed(() => ({ holds: '岩点样品', hold: '岩点属性', beta: 'Beta 序列' }[drawerSection.value]))
function openDrawer(section) { drawerSection.value = section; drawerOpen.value = true }

const HoldPalette = defineComponent({
  props: { studio: { type: Object, required: true }, library: { type: Object, required: true } },
  setup(localProps) {
    return () => h('section', { class: 'section-block hold-palette-panel' }, [
      h('div', { class: 'section-heading' }, [h('div', [h('h3', '岩点选择'), h('p', '从样品架选择，再放到岩板孔位')])]),
      h('div', { class: 'hold-filter-row' }, [
        h(resolveComponent('ElInput'), { modelValue: localProps.library.search, 'onUpdate:modelValue': (value) => { localProps.library.search = value }, placeholder: '搜索类型或变体', clearable: true, prefixIcon: Search }),
        h(resolveComponent('ElSelect'), { modelValue: localProps.library.typeFilter, 'onUpdate:modelValue': (value) => { localProps.library.typeFilter = value }, 'aria-label': '岩点类型' }, () => [
          h(resolveComponent('ElOption'), { label: '全部类型', value: 'All' }), ...localProps.library.holdTypes.map((type) => h(resolveComponent('ElOption'), { key: type, label: type, value: type })),
        ]),
      ]),
      h('div', { class: 'hold-palette' }, localProps.library.filteredHolds.length ? localProps.library.filteredHolds.map((hold) => h('button', { key: hold.key, type: 'button', class: ['hold-chip', { active: localProps.studio.selectedPoolHold?.key === hold.key }], onClick: () => localProps.studio.selectPoolHold(hold) }, [h(HoldPreview, { hold, mode: 'image' }), h('span', hold.hold_type), h('small', hold.variant)])) : [h('div', { class: 'empty-text' }, '没有匹配的岩点资源。')]),
    ])
  },
})
</script>
