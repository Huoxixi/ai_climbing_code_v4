<template>
  <div class="app-shell workspace-boulder">
    <header class="app-header">
      <div class="app-header-main">
        <button class="brand-block" type="button" aria-label="返回抱石项目" @click="$emit('update:active', 'photo-routes')">
          <span class="brand-mark"><Grid /></span>
          <span><strong>抱石项目</strong><small>攀岩助手</small></span>
        </button>
        <nav class="desktop-nav" aria-label="主导航">
          <button v-for="item in desktopItems" :key="item.key" :class="{ active: active === item.key }" :aria-current="active === item.key ? 'page' : undefined" @click="$emit('update:active', item.key)">{{ item.label }}</button>
        </nav>
        <div class="header-actions">
          <span v-if="showSync" class="sync-state" :class="{ dirty }"><i /><span class="sync-label-full">{{ saveLabel || (dirty ? '未保存' : '已同步') }}</span><span class="sync-label-mobile">{{ dirty ? '未保存' : '已同步' }}</span></span>
          <button v-if="active !== 'settings'" class="settings-trigger" type="button" aria-label="设置" title="设置" @click="$emit('update:active', 'settings')"><Setting /></button>
          <button v-else class="settings-done" type="button" @click="$emit('close-settings')">完成</button>
        </div>
      </div>
      <div class="mobile-context-row">
        <div><h1>{{ title }}</h1><span v-if="active !== 'settings'">{{ contextLabel || `${boardLabel} · ${holdCount} 岩点` }}</span></div>
        <span v-if="showSync" class="sync-state" :class="{ dirty }"><i /><span class="sync-label-full">{{ saveLabel || (dirty ? '未保存' : '已同步') }}</span><span class="sync-label-mobile">{{ dirty ? '未保存' : '已同步' }}</span></span>
      </div>
    </header>

    <main class="shell-main">
      <slot />
    </main>

    <nav v-if="active !== 'settings' && mobileItems.length > 1" class="mobile-tabs" aria-label="移动端导航" :style="{ '--mobile-tab-count': mobileItems.length }">
      <button v-for="item in mobileItems" :key="item.key" :class="{ active: active === item.key }" :aria-current="active === item.key ? 'page' : undefined" @click="$emit('update:active', item.key)">
        <component :is="item.icon" /><span>{{ item.short }}</span>
      </button>
    </nav>
  </div>
</template>

<script setup>
import { Camera, Collection, Grid, Setting, VideoCamera } from '@element-plus/icons-vue'
defineProps({active:String,title:String,holdCount:Number,dirty:Boolean,saveLabel:String,showSync:Boolean,contextLabel:{type:String,default:'个人抱石记录'},boardLabel:{type:String,default:'个人抱石记录'}})
defineEmits(['update:active','close-settings'])
const desktopItems=[{key:'photo-routes',label:'拍照定线',short:'拍照定线',icon:Camera},{key:'my-records',label:'我的记录',short:'我的记录',icon:Collection},{key:'climb-replay',label:'AI 复盘',short:'AI 复盘',icon:VideoCamera}]
const mobileItems=desktopItems
</script>
<style scoped>
.settings-trigger{display:inline-flex;align-items:center;justify-content:center;flex:none;width:44px;height:44px;border:1px solid transparent;border-radius:8px;background:transparent;color:var(--ink);cursor:pointer}
.settings-trigger svg{width:23px;height:23px}.settings-trigger:hover,.settings-trigger[aria-current=page]{background:var(--brand-soft);border-color:var(--line)}.settings-trigger:focus-visible{outline:3px solid var(--brand);outline-offset:2px}
.settings-done{min-height:40px;padding:0 4px;border:0;background:transparent;color:var(--ui-ink);font:inherit;font-weight:600;white-space:nowrap;cursor:pointer}
@media(min-width:861px){.settings-done{display:none}}
@media(max-width:860px){.workspace-boulder .shell-main{padding-bottom:0}}
</style>
