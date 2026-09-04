<template>
  <div class="app-shell">
    <header class="app-header">
      <div class="app-header-main">
        <button class="brand-block" type="button" aria-label="返回总览" @click="$emit('update:active', 'dashboard')">
          <span class="brand-mark"><Grid /></span>
          <span><strong>定线助手</strong><small>CLIMB SETTER</small></span>
        </button>
        <nav class="desktop-nav" aria-label="主导航">
          <button v-for="item in desktopItems" :key="item.key" :class="{ active: active === item.key }" :aria-current="active === item.key ? 'page' : undefined" @click="$emit('update:active', item.key)">{{ item.label }}</button>
        </nav>
        <div class="header-actions">
          <span class="sync-state" :class="{ dirty }"><i />{{ saveLabel || (dirty ? '未保存' : '已同步') }}</span>
          <el-button v-if="!pilotAccess.lease.ownedByMe" size="small" type="primary" :loading="pilotAccess.lease.loading" @click="pilotAccess.acquireLease">开始编辑</el-button>
          <el-button v-else size="small" :loading="pilotAccess.lease.loading" @click="pilotAccess.releaseLease">释放编辑权</el-button>
          <div class="pilot-user-menu"><span>{{ pilotAccess.session.displayName }}</span><button v-if="pilotAccess.session.authEnabled" type="button" @click="pilotAccess.logout">退出</button></div>
        </div>
      </div>
      <div class="mobile-context-row">
        <div><h1>{{ title }}</h1><span>{{ boardLabel }} · {{ holdCount }} 岩点</span></div>
        <span class="sync-state" :class="{ dirty }"><i />{{ saveLabel || (dirty ? '未保存' : '已同步') }}</span>
      </div>
    </header>

    <main class="shell-main">
      <div v-if="['boards', 'library', 'photo-routes'].includes(active)" class="mobile-asset-switch" aria-label="资产分类">
        <button :class="{ active: active === 'boards' }" @click="$emit('update:active', 'boards')">岩板</button>
        <button :class="{ active: active === 'library' }" @click="$emit('update:active', 'library')">岩点</button>
        <button :class="{ active: active === 'photo-routes' }" @click="$emit('update:active', 'photo-routes')">照片线路</button>
      </div>
      <slot />
    </main>

    <nav class="mobile-tabs" aria-label="移动端导航">
      <button v-for="item in mobileItems" :key="item.key" :class="{ active: mobileActive === item.key }" :aria-current="mobileActive === item.key ? 'page' : undefined" @click="$emit('update:active', item.key)">
        <component :is="item.icon" /><span>{{ item.short }}</span>
      </button>
    </nav>
  </div>
</template>

<script setup>
import { computed, inject } from 'vue'
import { Collection, DataBoard, Grid, Histogram, Platform } from '@element-plus/icons-vue'

const props = defineProps({
  active: { type: String, required: true }, title: { type: String, required: true }, boardLabel: { type: String, default: '未选择岩板' },
  holdCount: { type: Number, default: 0 }, dirty: { type: Boolean, default: false }, saveLabel: { type: String, default: '' }, simulationEnabled: { type: Boolean, default: false },
})
defineEmits(['update:active'])
const pilotAccess = inject('pilotAccess')
const desktopItems = computed(() => ([
  { key: 'dashboard', label: '总览' }, { key: 'studio', label: '定线' },
  { key: 'photo-routes', label: '照片线路' }, { key: 'standard-board', label: '板库' }, { key: 'boards', label: '资产' },
  { key: 'simulation', label: '仿真审核' }, { key: 'ai-lab', label: 'AI 实验室' },
]).filter((item) => item.key !== 'simulation' || props.simulationEnabled))
const mobileItems = [
  { key: 'dashboard', short: '首页', icon: DataBoard }, { key: 'studio', short: '定线', icon: Platform },
  { key: 'standard-board', short: '板库', icon: Grid }, { key: 'boards', short: '资产', icon: Collection }, { key: 'ai-lab', short: 'AI', icon: Histogram },
]
const mobileActive = computed(() => (['boards', 'library', 'photo-routes'].includes(props.active) ? 'boards' : props.active))
</script>
