<template>
  <div class="app-shell" :class="`workspace-${workspace}`">
    <header class="app-header">
      <div class="app-header-main">
        <button class="brand-block" type="button" :aria-label="`返回${workspaceTitle}`" @click="$emit('update:active', workspaceHome)">
          <span class="brand-mark"><Grid /></span>
          <span><strong>{{ workspaceTitle }}</strong><small>攀岩助手</small></span>
        </button>
        <nav class="desktop-nav" aria-label="主导航">
          <button v-for="item in desktopItems" :key="item.key" :class="{ active: active === item.key }" :aria-current="active === item.key ? 'page' : undefined" @click="$emit('update:active', item.key)">{{ item.label }}</button>
        </nav>
        <div class="header-actions">
          <a class="workspace-back-link" href="#/projects" aria-label="返回项目选择" @click.prevent="$emit('change-workspace')"><ArrowLeft /><span class="desktop-switch-label">返回项目选择</span><span class="mobile-switch-label">项目</span></a>
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
      <div v-if="['boards', 'library'].includes(active)" class="mobile-asset-switch" aria-label="资产分类">
        <button :class="{ active: active === 'boards' }" @click="$emit('update:active', 'boards')">岩板</button>
        <button :class="{ active: active === 'library' }" @click="$emit('update:active', 'library')">岩点</button>
      </div>
      <slot />
    </main>

    <nav v-if="active !== 'settings' && mobileItems.length > 1" class="mobile-tabs" aria-label="移动端导航">
      <button v-for="item in mobileItems" :key="item.key" :class="{ active: mobileActive === item.key }" :aria-current="mobileActive === item.key ? 'page' : undefined" @click="$emit('update:active', item.key)">
        <component :is="item.icon" /><span>{{ item.short }}</span>
      </button>
    </nav>
  </div>
</template>

<script setup>
import { computed, inject } from 'vue'
import { ArrowLeft, Collection, DataBoard, Grid, Histogram, Platform, Setting } from '@element-plus/icons-vue'

const props = defineProps({
  active: { type: String, required: true }, title: { type: String, required: true }, boardLabel: { type: String, default: '未选择岩板' },
  holdCount: { type: Number, default: 0 }, dirty: { type: Boolean, default: false }, saveLabel: { type: String, default: '' }, simulationEnabled: { type: Boolean, default: false },
  workspace: { type: String, required: true },
  photoSection: { type: String, default: 'routes' },
})
defineEmits(['update:active', 'close-settings', 'change-workspace'])
const pilotAccess = inject('pilotAccess')
const workspaceTitle = computed(() => props.workspace === 'boulder' ? '抱石项目' : '定线项目')
const workspaceHome = computed(() => props.workspace === 'boulder' ? 'photo-routes' : 'dashboard')
const setterDesktopItems = [
  { key: 'dashboard', label: '总览' }, { key: 'studio', label: '定线' },
  { key: 'standard-board', label: '板库' }, { key: 'boards', label: '资产' },
  { key: 'simulation', label: '仿真审核' }, { key: 'ai-lab', label: 'AI 实验室' },
]
const desktopItems = computed(() => (props.workspace === 'boulder'
  ? [{ key: 'photo-routes', label: '照片线路' }]
  : setterDesktopItems.filter((item) => item.key !== 'simulation' || props.simulationEnabled)))
const setterMobileItems = [
  { key: 'dashboard', short: '首页', icon: DataBoard }, { key: 'studio', short: '定线', icon: Platform },
  { key: 'standard-board', short: '板库', icon: Grid }, { key: 'boards', short: '资产', icon: Collection }, { key: 'ai-lab', short: 'AI', icon: Histogram },
]
const mobileItems = computed(() => props.workspace === 'boulder'
  ? [
      { key: 'photo-routes', short: '添加线路', icon: Grid },
      { key: 'photo-library', short: '线路库', icon: Collection },
    ]
  : setterMobileItems)
const mobileActive = computed(() => {
  if (props.workspace === 'boulder') return props.photoSection === 'library' ? 'photo-library' : 'photo-routes'
  if (props.active === 'studio') return 'studio'
  if (['boards', 'library'].includes(props.active)) return 'boards'
  return props.active
})
</script>

<style scoped>
.settings-trigger{display:inline-flex;align-items:center;justify-content:center;flex:none;width:44px;height:44px;border:1px solid transparent;border-radius:8px;background:transparent;color:var(--ink);cursor:pointer}
.settings-trigger svg{width:23px;height:23px}.settings-trigger:hover,.settings-trigger[aria-current=page]{background:var(--brand-soft);border-color:var(--line)}.settings-trigger:focus-visible{outline:3px solid var(--brand);outline-offset:2px}
.settings-done{min-height:40px;padding:0 4px;border:0;background:transparent;color:var(--ui-ink);font:inherit;font-weight:600;white-space:nowrap;cursor:pointer}
.workspace-back-link{min-height:36px;padding:0 11px;border:1px solid var(--ui-line);border-radius:var(--ui-radius-small);background:var(--ui-surface);color:var(--ui-ink-muted);display:inline-flex;align-items:center;gap:6px;font-size:12px;font-weight:500;text-decoration:none;white-space:nowrap;cursor:pointer}.workspace-back-link svg{width:15px;height:15px}.workspace-back-link:hover{border-color:var(--ui-line-strong);background:var(--ui-brand-soft);color:var(--ui-ink)}.mobile-switch-label{display:none}
@media(min-width:861px){.settings-done{display:none}}
@media(max-width:860px){.desktop-switch-label{display:none}.mobile-switch-label{display:inline}.workspace-back-link{min-width:58px;padding-inline:8px}.workspace-boulder .shell-main{padding-bottom:0}}
</style>
