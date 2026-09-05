<template>
  <section class="page">
    <div class="page-header">
      <div>
        <p class="eyebrow">本地岩点资产</p>
        <h2>岩点资源库</h2>
      </div>
      <el-button :icon="Refresh" :loading="library.loading" @click="library.fetchAllHoldData">刷新资源库</el-button>
    </div>
    <div class="library-grid">
      <section class="section-block upload-panel">
        <div class="upload-panel-heading">
          <div>
          <p class="eyebrow">录入新岩点</p>
          <h3>上传岩点</h3>
          </div>
          <button type="button" class="mobile-upload-toggle" :aria-expanded="uploadExpanded" @click="uploadExpanded = !uploadExpanded">
            {{ uploadExpanded ? '收起' : '展开' }}
          </button>
        </div>
        <div class="upload-form" :class="{ expanded: uploadExpanded }">
        <el-select v-model="library.uploadInfo.hold_type" aria-label="岩点类型">
          <el-option v-for="type in library.holdTypes" :key="type" :label="type" :value="type" />
        </el-select>
        <el-input v-model="library.uploadInfo.variant" aria-label="岩点变体名称" placeholder="变体名称，例如 large_crimp_01" />
        <small class="upload-help">支持 PNG、JPEG、WebP；白底图片上传后会自动去除背景。</small>
        <el-upload accept="image/png,image/jpeg,image/webp" :auto-upload="false" :show-file-list="true" :limit="1" :on-change="onUploadFile" :on-remove="removeUploadFile">
          <el-button :icon="Upload">选择图片</el-button>
        </el-upload>
        <el-button type="primary" :loading="library.loading" @click="library.uploadImage">上传</el-button>
        </div>
      </section>

      <section class="section-block">
        <div class="section-heading">
          <div>
            <p class="eyebrow">岩点清单</p>
            <h3>{{ library.showArchived ? '归档箱' : '已启用岩点' }}</h3>
          </div>
          <el-segmented
            v-model="library.showArchived"
            :options="[{ label: '已启用', value: false }, { label: '归档箱', value: true }]"
          />
        </div>
        <div class="filter-row">
          <el-input v-model="library.search" placeholder="搜索岩点" clearable :prefix-icon="Search" />
          <el-select v-model="library.typeFilter" aria-label="按岩点类型筛选">
            <el-option label="全部类型" value="All" />
            <el-option v-for="type in library.holdTypes" :key="type" :label="type" :value="type" />
          </el-select>
          <el-segmented
            v-model="library.previewMode"
            :options="[{ label: '轮廓', value: 'vector' }, { label: '图片', value: 'image' }]"
          />
        </div>
        <div class="asset-grid">
          <article v-for="hold in library.filteredHolds" :key="hold.key" class="hold-card">
            <HoldPreview :hold="hold" :mode="library.previewMode" />
            <strong>{{ hold.hold_type }}</strong>
            <span>{{ hold.variant }}</span>
            <small>{{ hold.visibility === 'public' ? '公共资源' : '我的岩点' }}</small>
            <el-button
              v-if="!library.showArchived && hold.visibility !== 'public'"
              text
              type="danger"
              :icon="Delete"
              @click="library.archiveHold(hold.hold_type, hold.variant)"
            >
              归档
            </el-button>
            <el-button v-else-if="library.showArchived && hold.visibility !== 'public'" text type="primary" @click="library.restoreHold(hold.hold_type, hold.variant)">恢复使用</el-button>
          </article>
        </div>
        <div v-if="!library.filteredHolds.length" class="empty-state">
          <strong>{{ library.showArchived ? '归档箱为空' : '暂无岩点资源' }}</strong>
          <span>{{ library.showArchived ? '归档后的岩点会显示在这里。' : '上传岩点后可在定线工作台中使用。' }}</span>
        </div>
      </section>
    </div>
  </section>
</template>

<script setup>
import { ref } from 'vue'
import { Delete, Refresh, Search, Upload } from '@element-plus/icons-vue'
import HoldPreview from './HoldPreview.vue'

const props = defineProps({
  library: { type: Object, required: true },
})
const uploadExpanded = ref(false)

function onUploadFile(uploadFile) {
  props.library.uploadInfo.file = uploadFile.raw
}

function removeUploadFile() {
  props.library.uploadInfo.file = null
}
</script>
