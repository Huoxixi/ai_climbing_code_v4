<template>
  <section class="settings-card desktop-storage" aria-labelledby="desktop-settings-title">
    <h2 id="desktop-settings-title">文件存储</h2>
    <p v-if="status" class="storage-path">{{ status.data_directory }}</p>
    <p>选择空文件夹保存照片、视频和复盘记录。</p>
    <button type="button" class="storage-button" :disabled="busy || !status" @click="chooseFolder">{{ busy ? '正在选择…' : '选择文件夹' }}</button>
    <p v-if="status?.pending_data_directory">新位置：{{ status.pending_data_directory }}。重开 App 后自动复制已有资料，原文件保留。</p>
    <p v-if="notice" role="status">{{ notice }}</p>
    <p v-if="status?.update_label" class="app-update">{{ status.update_label }}</p>
  </section>
</template>
<script setup>
import { onMounted, ref } from 'vue'
import apiClient from '../services/apiClient'
const status = ref(null)
const notice = ref('')
const busy = ref(false)
async function chooseFolder() {
  busy.value = true
  notice.value = ''
  try {
    const { data } = await apiClient.post('/desktop/storage/choose', null, { timeout: 0 })
    if (!data.cancelled) {
      status.value.pending_data_directory = data.restart_required ? data.directory : null
      notice.value = data.restart_required ? '' : '已保持当前存储位置。'
    }
  } catch (error) {
    notice.value = error.response?.data?.detail || '存储位置未更改，请重试。'
  } finally { busy.value = false }
}
onMounted(async () => {
  if (!window.__AI_CLIMBING_DESKTOP__) return
  try { status.value = (await apiClient.get('/desktop/status')).data } catch { notice.value = '桌面设置暂不可用。' }
})
</script>
<style scoped>
.desktop-storage { grid-column: 1 / -1; min-width: 0; }
h2 { margin: 0 0 8px; }
p { margin: 0; line-height: 1.6; overflow-wrap: anywhere; color: var(--ui-ink-muted); }
.storage-button { margin: 12px 0; padding: 10px 18px; border: 1px solid var(--ui-border, #d8d8d8); border-radius: 10px; background: var(--ui-surface, #fff); color: inherit; font: inherit; cursor: pointer; }
.storage-button:disabled { opacity: .6; cursor: default; }
.app-update { margin-top: 16px; font-size: 12px; }
</style>
