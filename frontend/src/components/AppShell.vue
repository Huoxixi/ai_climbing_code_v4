<template>
  <div class="app-shell">
    <header class="app-header">
      <div class="app-header-main">
        <button class="brand-block" type="button" aria-label="返回总览" @click="$emit('update:active', 'dashboard')">
          <span class="brand-mark"><Grid /></span>
          <span><strong>攀岩助手</strong><small>CLIMB SETTER</small></span>
        </button>
        <nav class="desktop-nav" aria-label="主导航">
          <button v-for="item in desktopItems" :key="item.key" :class="{ active: active === item.key }" :aria-current="active === item.key ? 'page' : undefined" @click="$emit('update:active', item.key)">{{ item.label }}</button>
        </nav>
        <div class="header-actions">
          <span class="sync-state" :class="{ dirty }"><i /><span class="sync-label-full">{{ saveLabel || (dirty ? '未保存' : '已同步') }}</span><span class="sync-label-mobile">{{ dirty ? '未保存' : '已同步' }}</span></span>
          <el-button v-if="active !== 'settings' && !pilotAccess.lease.ownedByMe" size="small" type="primary" :loading="pilotAccess.lease.loading" @click="pilotAccess.acquireLease">开始编辑</el-button>
          <el-button v-else-if="active !== 'settings'" size="small" :loading="pilotAccess.lease.loading" @click="pilotAccess.releaseLease">释放编辑权</el-button>
          <button v-if="active !== 'settings'" class="settings-trigger" type="button" aria-label="设置" title="设置" @click="$emit('update:active', 'settings')"><Setting /></button>
          <button v-else class="settings-done" type="button" @click="$emit('close-settings')">完成</button>
        </div>
      </div>
      <div class="mobile-context-row">
        <div><h1>{{ title }}</h1><span v-if="active !== 'settings'">{{ boardLabel }} · {{ holdCount }} 岩点</span></div>
        <span class="sync-state" :class="{ dirty }"><i /><span class="sync-label-full">{{ saveLabel || (dirty ? '未保存' : '已同步') }}</span><span class="sync-label-mobile">{{ dirty ? '未保存' : '已同步' }}</span></span>
      </div>
    </header>

    <main class="shell-main">
      <div v-if="['studio', 'photo-routes'].includes(active)" class="mobile-route-switch" aria-label="定线方式">
        <button :class="{ active: active === 'studio' }" @click="$emit('update:active', 'studio')">岩板定线</button>
        <button :class="{ active: active === 'photo-routes' }" @click="$emit('update:active', 'photo-routes')">照片线路</button>
      </div>
      <div v-if="['boards', 'library'].includes(active)" class="mobile-asset-switch" aria-label="资产分类">
        <button :class="{ active: active === 'boards' }" @click="$emit('update:active', 'boards')">岩板</button>
        <button :class="{ active: active === 'library' }" @click="$emit('update:active', 'library')">岩点</button>
      </div>
      <slot />
    </main>

    <nav v-if="active !== 'settings'" class="mobile-tabs" aria-label="移动端导航">
      <button v-for="item in mobileItems" :key="item.key" :class="{ active: mobileActive === item.key }" :aria-current="mobileActive === item.key ? 'page' : undefined" @click="$emit('update:active', item.key)">
        <component :is="item.icon" /><span>{{ item.short }}</span>
      </button>
    </nav>
  </div>
</template>

<script setup>
import { computed, inject } from 'vue'
import { Collection, DataBoard, Grid, Histogram, Platform, Setting } from '@element-plus/icons-vue'

const props = defineProps({
  active: { type: String, required: true }, title: { type: String, required: true }, boardLabel: { type: String, default: '未选择岩板' },
  holdCount: { type: Number, default: 0 }, dirty: { type: Boolean, default: false }, saveLabel: { type: String, default: '' }, simulationEnabled: { type: Boolean, default: false },
})
defineEmits(['update:active', 'close-settings'])
const pilotAccess = inject('pilotAccess')
const desktopItems = computed(() => ([
  { key: 'dashboard', label: '总览' }, { key: 'studio', label: '定线' },
  { key: 'photo-routes', label: '抱石线路' }, { key: 'standard-board', label: '板库' }, { key: 'boards', label: '资产' },
  { key: 'simulation', label: '仿真审核' }, { key: 'ai-lab', label: 'AI 实验室' },
]).filter((item) => item.key !== 'simulation' || props.simulationEnabled))
const mobileItems = [
  { key: 'dashboard', short: '首页', icon: DataBoard }, { key: 'studio', short: '定线', icon: Platform },
  { key: 'standard-board', short: '板库', icon: Grid }, { key: 'boards', short: '资产', icon: Collection }, { key: 'ai-lab', short: 'AI', icon: Histogram },
]
const mobileActive = computed(() => {
  if (['studio', 'photo-routes'].includes(props.active)) return 'studio'
  if (['boards', 'library'].includes(props.active)) return 'boards'
  return props.active
})
</script>

<style scoped>
.settings-trigger{display:inline-flex;align-items:center;justify-content:center;flex:none;width:44px;height:44px;border:1px solid transparent;border-radius:8px;background:transparent;color:var(--ink);cursor:pointer}
.settings-trigger svg{width:23px;height:23px}.settings-trigger:hover,.settings-trigger[aria-current=page]{background:var(--brand-soft);border-color:var(--line)}.settings-trigger:focus-visible{outline:3px solid var(--brand);outline-offset:2px}
.settings-done{min-height:40px;padding:0 4px;border:0;background:transparent;color:var(--ui-ink);font:inherit;font-weight:600;white-space:nowrap;cursor:pointer}
@media(min-width:861px){.settings-done{display:none}}
</style>
