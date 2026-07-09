<template>
  <div class="app-shell">
    <aside class="nav-rail" aria-label="主导航">
      <div class="brand-block">
        <div class="brand-mark">
          <Grid class="brand-icon" />
        </div>
        <span>Climb OS</span>
      </div>
      <button
        v-for="item in items"
        :key="item.key"
        class="rail-item"
        :class="{ active: active === item.key }"
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
          <p class="eyebrow">Climbing Board Studio</p>
          <h1>{{ title }}</h1>
        </div>
        <div class="topbar-status">
          <span class="status-pill">{{ boardLabel }}</span>
          <span class="status-pill">{{ holdCount }} 岩点</span>
          <span class="status-pill" :class="{ dirty: dirty }">{{ dirty ? '未保存' : '已同步' }}</span>
          <span v-if="userEmail" class="status-pill user-pill">{{ userEmail }}</span>
          <el-button v-if="userEmail" size="small" @click="$emit('logout')">退出</el-button>
        </div>
      </header>
      <slot />
    </div>

    <nav class="mobile-tabs" aria-label="移动端导航">
      <button
        v-for="item in items"
        :key="item.key"
        :class="{ active: active === item.key }"
        @click="$emit('update:active', item.key)"
      >
        <component :is="item.icon" />
        <span>{{ item.short }}</span>
      </button>
    </nav>
  </div>
</template>

<script setup>
import { Collection, DataBoard, Grid, Histogram, Platform } from '@element-plus/icons-vue'

defineProps({
  active: { type: String, required: true },
  title: { type: String, required: true },
  boardLabel: { type: String, default: '未选择岩板' },
  holdCount: { type: Number, default: 0 },
  dirty: { type: Boolean, default: false },
  userEmail: { type: String, default: '' },
})

defineEmits(['update:active', 'logout'])

const items = [
  { key: 'dashboard', label: '总览', short: '总览', icon: DataBoard },
  { key: 'studio', label: 'Studio', short: '创作', icon: Platform },
  { key: 'library', label: '岩点库', short: '岩点', icon: Collection },
  { key: 'boards', label: '岩板资产', short: '资产', icon: Grid },
  { key: 'standard-board', label: '标准板库', short: '板库', icon: Grid },
  { key: 'ai-lab', label: 'AI Lab', short: 'AI', icon: Histogram },
]
</script>
