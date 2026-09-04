<template>
  <div class="app-shell">
    <aside class="nav-rail" aria-label="主导航">
      <div class="brand-block">
        <div class="brand-mark">
          <Grid class="brand-icon" />
        </div>
        <span>定线助手</span>
      </div>
      <button
        v-for="item in items"
        :key="item.key"
        class="rail-item"
        :class="{ active: active === item.key }"
        :aria-current="active === item.key ? 'page' : undefined"
        :title="item.label"
        @click="$emit('update:active', item.key)"
      >
        <component :is="item.icon" />
        <span>{{ item.label }}</span>
      </button>
    </aside>

    <div class="shell-main">
      <header class="topbar">
        <div class="topbar-title">
          <p class="eyebrow">{{ pilotAccess.session.authEnabled ? '小范围线上试用' : '本地单机版' }}</p>
          <h1>{{ title }}</h1>
        </div>
        <div class="topbar-status">
          <span class="status-pill">{{ boardLabel }}</span>
          <span class="status-pill">{{ holdCount }} 岩点</span>
          <span class="status-pill" :class="{ dirty: dirty }">{{ saveLabel || (dirty ? '未保存' : '已同步') }}</span>
          <span
            class="status-pill access-status"
            :class="{ editing: pilotAccess.lease.ownedByMe, waiting: pilotAccess.lease.active && !pilotAccess.lease.ownedByMe }"
          >
            {{ editStatusLabel }}
          </span>
          <el-button
            v-if="!pilotAccess.lease.ownedByMe"
            size="small"
            type="primary"
            :loading="pilotAccess.lease.loading"
            @click="pilotAccess.acquireLease"
          >
            开始编辑
          </el-button>
          <el-button
            v-else
            size="small"
            :loading="pilotAccess.lease.loading"
            @click="pilotAccess.releaseLease"
          >
            释放编辑权
          </el-button>
          <div class="pilot-user-menu">
            <span>{{ pilotAccess.session.displayName }}</span>
            <button v-if="pilotAccess.session.authEnabled" type="button" @click="pilotAccess.logout">退出</button>
          </div>
        </div>
      </header>
      <slot />
    </div>

    <nav class="mobile-tabs" aria-label="移动端导航">
      <button
        v-for="item in items"
        :key="item.key"
        :class="{ active: active === item.key }"
        :aria-current="active === item.key ? 'page' : undefined"
        @click="$emit('update:active', item.key)"
      >
        <component :is="item.icon" />
        <span>{{ item.short }}</span>
      </button>
    </nav>
  </div>
</template>

<script setup>
import { computed, inject } from 'vue'
import { Collection, DataBoard, Grid, Histogram, Picture, Platform } from '@element-plus/icons-vue'

const props = defineProps({
  active: { type: String, required: true },
  title: { type: String, required: true },
  boardLabel: { type: String, default: '未选择岩板' },
  holdCount: { type: Number, default: 0 },
  dirty: { type: Boolean, default: false },
  saveLabel: { type: String, default: '' },
  simulationEnabled: { type: Boolean, default: false },
})

defineEmits(['update:active'])

const pilotAccess = inject('pilotAccess')

const baseItems = [
  { key: 'dashboard', label: '总览', short: '总览', icon: DataBoard },
  { key: 'studio', label: '定线工作台', short: '定线', icon: Platform },
  { key: 'photo-routes', label: '照片线路', short: '照片', icon: Picture },
  { key: 'library', label: '岩点库', short: '岩点', icon: Collection },
  { key: 'boards', label: '岩板资产', short: '资产', icon: Grid },
  { key: 'standard-board', label: '标准板库', short: '板库', icon: Grid },
  { key: 'simulation', label: '仿真审核', short: '仿真', icon: Histogram },
  { key: 'ai-lab', label: 'AI 实验室', short: 'AI', icon: Histogram },
]

const items = computed(() => (
  baseItems.filter((item) => item.key !== 'simulation' || props.simulationEnabled)
))

const editStatusLabel = computed(() => {
  if (pilotAccess.lease.ownedByMe) return '我正在编辑'
  if (pilotAccess.lease.active) return `${pilotAccess.lease.holderDisplayName}正在编辑`
  return '浏览模式'
})
</script>
