<template>
  <AppShell
    v-model:active="activePage"
    :title="pageTitle"
    :board-label="studio.currentBoardSpec.label"
    :hold-count="studio.placedHolds.length"
    :dirty="studio.unsavedChanges"
  >
    <section v-if="activePage === 'dashboard'" class="page dashboard-page">
      <div class="dashboard-hero">
        <div>
          <p class="eyebrow">专业深色工作台</p>
          <h2>工作台总览</h2>
          <div class="command-row">
            <el-button type="primary" :icon="Plus" @click="startBlankStudio">新建岩板</el-button>
            <el-button :icon="Collection" @click="activePage = 'library'">管理岩点库</el-button>
          </div>
        </div>
        <div class="metric-grid">
          <div><strong>{{ studio.placedHolds.length }}</strong><span>当前岩点</span></div>
          <div><strong>{{ studio.routeSteps.length }}</strong><span>Beta 动作</span></div>
          <div><strong>{{ boards.savedBoards.length }}</strong><span>岩板资产</span></div>
          <div><strong>{{ library.managedHolds.length }}</strong><span>岩点资源</span></div>
        </div>
      </div>

      <div class="template-grid">
        <button
          v-for="template in studio.boardPresets"
          :key="template.id"
          class="template-card"
          :class="{ active: selectedDashboardTemplateId === template.id }"
          @click="selectedDashboardTemplateId = template.id"
        >
          <span>{{ template.cellLabel }}</span>
          <strong>{{ template.label }}</strong>
          <small>{{ template.physicalLabel }} / {{ template.spacingLabel }}</small>
        </button>
      </div>

      <section class="panel template-detail-panel">
        <div>
          <p class="eyebrow">岩板规格</p>
          <h3>{{ selectedDashboardTemplate.label }}</h3>
          <p>{{ selectedDashboardTemplate.description }}</p>
        </div>
        <div class="template-detail-meta">
          <span>{{ selectedDashboardTemplate.cellLabel }}</span>
          <span>{{ selectedDashboardTemplate.physicalLabel }}</span>
          <span>孔距 {{ selectedDashboardTemplate.spacingLabel }}</span>
          <span>{{ selectedDashboardTemplate.angleLabel }}</span>
          <span>{{ selectedDashboardTemplate.total_holes }} 孔</span>
          <span>{{ selectedDashboardTemplate.material }}</span>
        </div>
        <el-button type="primary" :icon="DocumentChecked" @click="createFromTemplate(selectedDashboardTemplateId)">
          确认使用
        </el-button>
      </section>

      <div class="two-column">
        <section class="panel">
          <div class="panel-heading">
            <h3>最近岩板</h3>
            <el-button text @click="activePage = 'boards'">查看全部</el-button>
          </div>
          <div v-if="!boards.savedBoards.length" class="empty-text">暂无已保存岩板。</div>
          <button v-for="board in boards.savedBoards.slice(0, 5)" :key="board.saved_id || board.route_name" class="asset-row" @click="loadBoardIntoStudio(board)">
            <span>{{ board.route_name || '未命名岩板' }}</span>
            <small>{{ board.beta_sequence?.length || 0 }} Beta / {{ board.placed_holds?.length || 0 }} 岩点</small>
          </button>
        </section>
        <section class="panel">
          <div class="panel-heading">
            <h3>工作状态</h3>
            <span>{{ studio.unsavedChanges ? '有未保存修改' : '已同步' }}</span>
          </div>
          <div class="state-list">
            <span>岩板：{{ studio.currentBoardSpec.cellLabel }}</span>
            <span>规格：{{ studio.currentBoardSpec.physicalLabel }}</span>
            <span>孔距：{{ studio.currentBoardSpec.spacingLabel }}</span>
            <span>材质：{{ studio.currentBoardSpec.material }}</span>
            <span>模式：手动模拟建板</span>
          </div>
        </section>
      </div>
    </section>

    <section v-else-if="activePage === 'studio'" class="studio-page">
      <div class="command-bar">
        <el-select v-model="studio.activeBoardPresetId" class="preset-select" @change="studio.applyBoardPreset">
          <el-option v-for="template in studio.boardPresets" :key="template.id" :label="`${template.label} (${template.cellLabel})`" :value="template.id" />
        </el-select>
        <el-button :icon="Plus" @click="startBlankStudio">新建</el-button>
        <el-button :icon="Delete" @click="studio.clearBoard">清空</el-button>
        <el-button type="primary" :loading="boards.loading" :icon="DocumentChecked" @click="saveCurrentBoard">保存岩板</el-button>
      </div>

      <div class="studio-layout">
        <aside class="tool-panel">
          <section class="panel">
            <div class="panel-heading">
              <h3>岩点选择</h3>
              <el-segmented v-model="library.previewMode" :options="['vector', 'image']" />
            </div>
            <el-input v-model="library.search" placeholder="搜索类型或变体" clearable :prefix-icon="Search" />
            <el-select v-model="library.typeFilter">
              <el-option label="全部类型" value="All" />
              <el-option v-for="type in library.holdTypes" :key="type" :label="type" :value="type" />
            </el-select>
            <div class="hold-palette">
              <button
                v-for="hold in library.filteredHolds"
                :key="hold.key"
                class="hold-chip"
                :class="{ active: studio.selectedPoolHold?.key === hold.key }"
                @click="studio.selectPoolHold(hold)"
              >
                <HoldPreview :hold="hold" :mode="library.previewMode" />
                <span>{{ hold.hold_type }}</span>
                <small>{{ hold.variant }}</small>
              </button>
              <div v-if="!library.filteredHolds.length" class="empty-text">没有匹配的岩点资源。</div>
            </div>
          </section>
        </aside>

        <BoardCanvas
          :columns="studio.coordinateColumns"
          :rows="studio.coordinateRows"
          :holds="studio.placedHolds"
          :route-steps="studio.routeSteps"
          :selected-hold="studio.selectedHold"
          :board-spec="studio.currentBoardSpec"
          :frame-style="studio.boardFrameStyle"
          :get-coord-style="studio.getCoordStyle"
          :resolve-hold-visual="library.resolveHoldVisual"
          @place="studio.placeHold"
          @select="selectPlacedHold"
        />

        <InspectorPanel
          :board="studio.currentBoard"
          :selected-hold="studio.selectedHold"
          :route-steps="studio.routeSteps"
          :beta-form="studio.betaForm"
          :hold-types="library.holdTypes"
          @update-hold="studio.updateSelectedHold"
          @delete-hold="studio.deleteSelectedHold"
          @add-beta="studio.addBetaStep"
          @delete-beta="studio.deleteBetaStep"
          @dirty="studio.markUnsaved"
        />
      </div>
    </section>

    <section v-else-if="activePage === 'library'" class="page">
      <div class="page-header">
        <div>
          <p class="eyebrow">Hold Library</p>
          <h2>岩点库</h2>
        </div>
        <el-button :icon="Refresh" :loading="library.loading" @click="library.fetchAllHoldData">刷新岩点库</el-button>
      </div>
      <div class="library-grid">
        <section class="panel upload-panel">
          <h3>上传岩点</h3>
          <el-select v-model="library.uploadInfo.hold_type">
            <el-option v-for="type in library.holdTypes" :key="type" :label="type" :value="type" />
          </el-select>
          <el-input v-model="library.uploadInfo.variant" placeholder="变体名称，例如 large_crimp_01" />
          <el-upload :auto-upload="false" :show-file-list="true" :limit="1" :on-change="onUploadFile" :on-remove="removeUploadFile">
            <el-button :icon="Upload">选择图片</el-button>
          </el-upload>
          <el-button type="primary" :loading="library.loading" @click="library.uploadImage">上传</el-button>
        </section>

        <section class="panel">
          <div class="panel-heading">
            <h3>已录入岩点</h3>
            <span>{{ library.filteredHolds.length }} / {{ library.managedHolds.length }}</span>
          </div>
          <div class="filter-row">
            <el-input v-model="library.search" placeholder="搜索岩点" clearable :prefix-icon="Search" />
            <el-select v-model="library.typeFilter">
              <el-option label="全部类型" value="All" />
              <el-option v-for="type in library.holdTypes" :key="type" :label="type" :value="type" />
            </el-select>
            <el-segmented v-model="library.previewMode" :options="['vector', 'image']" />
          </div>
          <div class="asset-grid">
            <article v-for="hold in library.filteredHolds" :key="hold.key" class="hold-card">
              <HoldPreview :hold="hold" :mode="library.previewMode" />
              <strong>{{ hold.hold_type }}</strong>
              <span>{{ hold.variant }}</span>
              <el-button text type="danger" :icon="Delete" @click="library.deleteHold(hold.hold_type, hold.variant)">删除</el-button>
            </article>
          </div>
          <div v-if="!library.filteredHolds.length" class="empty-state">暂无岩点资源。上传后可在 Studio 中使用。</div>
        </section>
      </div>
    </section>

    <section v-else-if="activePage === 'boards'" class="page">
      <div class="page-header">
        <div>
          <p class="eyebrow">Board Assets</p>
          <h2>岩板资产</h2>
        </div>
        <div class="command-row">
          <el-button :icon="Refresh" :loading="boards.loading" @click="boards.fetchMyBoards">刷新</el-button>
          <el-button type="primary" :icon="Plus" @click="startBlankStudio">新建岩板</el-button>
        </div>
      </div>
      <div class="board-assets">
        <article v-for="board in boards.savedBoards" :key="board.saved_id || board.route_name" class="board-card">
          <div>
            <strong>{{ board.route_name || '未命名岩板' }}</strong>
            <span>{{ board.board_spec?.label || '岩板' }} / {{ board.placed_holds?.length || 0 }} 岩点 / {{ board.beta_sequence?.length || 0 }} Beta</span>
          </div>
          <div class="card-actions">
            <el-button :icon="Edit" @click="loadBoardIntoStudio(board)">载入编辑</el-button>
            <el-button :icon="EditPen" @click="renameBoard(board)">重命名</el-button>
            <el-button type="danger" plain :icon="Delete" @click="deleteBoard(board)">删除</el-button>
          </div>
        </article>
        <div v-if="!boards.savedBoards.length" class="empty-state">暂无保存的岩板资产。</div>
      </div>
    </section>

    <section v-else class="page ai-page">
      <div class="lab-panel" :class="{ locked: !aiLabUnlocked }">
        <p class="eyebrow">AI Lab</p>
        <template v-if="!aiLabUnlocked">
          <h2 class="lab-title">实验室入口</h2>
          <p class="lab-copy">这里用于提交当前岩板给 AI 生成实验。进入前需要输入访问密码。</p>
          <div class="lab-login">
            <el-input
              v-model="aiLabPassword"
              type="password"
              show-password
              placeholder="请输入实验室密码"
              @keyup.enter="unlockAiLab"
            />
            <el-button type="primary" @click="unlockAiLab">进入实验室</el-button>
            <el-button @click="activePage = 'studio'">返回 Studio</el-button>
          </div>
        </template>
        <h2>实验室入口</h2>
        <div class="command-row">
          <el-button type="primary" :loading="routeGen.loading" @click="runAiExperiment">用当前岩板试验生成</el-button>
          <el-button v-if="routeGen.loading" @click="routeGen.cancelGeneration">取消任务</el-button>
          <el-button @click="activePage = 'studio'">返回 Studio</el-button>
        </div>
        <el-alert v-if="routeGen.taskId" type="info" :closable="false" :title="`任务 ID：${routeGen.taskId}`" />
        <el-alert v-if="routeGen.error" type="error" :closable="false" :title="routeGen.error" />
      </div>
    </section>
  </AppShell>
</template>

<script setup>
import { computed, defineComponent, h, onMounted, reactive, ref } from 'vue'
import { Collection, Delete, DocumentChecked, Edit, EditPen, Plus, Refresh, Search, Upload } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import AppShell from './components/AppShell.vue'
import BoardCanvas from './components/BoardCanvas.vue'
import InspectorPanel from './components/InspectorPanel.vue'
import { useBoardPersistence } from './composables/useBoardPersistence'
import { useHoldLibrary } from './composables/useHoldLibrary'
import { useRouteGeneration } from './composables/useRouteGeneration'
import { useStudioEditor } from './composables/useStudioEditor'

const activePage = ref('dashboard')
const library = reactive(useHoldLibrary())
const boards = reactive(useBoardPersistence())
const studio = reactive(useStudioEditor())
const routeGen = reactive(useRouteGeneration())
const selectedDashboardTemplateId = ref(studio.activeBoardPresetId)
const aiLabPassword = ref('')
const aiLabUnlocked = ref(false)

const pageTitle = computed(() => ({
  dashboard: '总览',
  studio: 'Studio 工作台',
  library: '岩点库',
  boards: '岩板资产',
  'ai-lab': 'AI Lab',
}[activePage.value] || 'Climbing Board Studio'))

const selectedDashboardTemplate = computed(() => (
  studio.boardPresets.find((template) => template.id === selectedDashboardTemplateId.value) || studio.boardPresets[0]
))

const HoldPreview = defineComponent({
  props: {
    hold: { type: Object, required: true },
    mode: { type: String, default: 'vector' },
  },
  setup(props) {
    return () => {
      const color = { Jug: '#43b284', Crimp: '#e45c5c', Sloper: '#d7a84f', Pinch: '#9a7ae6', Pocket: '#4b8fd9', Foot: '#8ea2b5' }[props.hold.hold_type] || '#43b284'
      if (props.mode === 'image' && props.hold.imageUrl) {
        return h('div', { class: 'hold-preview' }, [h('img', { src: props.hold.imageUrl, alt: '' })])
      }
      if (props.hold.svgPath) {
        return h('div', { class: 'hold-preview' }, [
          h('svg', { viewBox: '0 0 100 100', 'aria-hidden': 'true' }, [h('path', { d: props.hold.svgPath, fill: color })]),
        ])
      }
      return h('div', { class: 'hold-preview' }, [h('span', { class: ['hold-shape', props.hold.hold_type?.toLowerCase() || 'jug'] })])
    }
  },
})

onMounted(async () => {
  await Promise.all([library.fetchAllHoldData(), boards.fetchMyBoards()])
})

function startBlankStudio() {
  studio.newBlankBoard().then((created) => {
    if (created) activePage.value = 'studio'
  })
}

function createFromTemplate(templateId) {
  studio.newBlankBoard(templateId).then((created) => {
    if (created) activePage.value = 'studio'
  })
}

function selectPlacedHold(hold) {
  studio.selectedHold = hold
  studio.betaForm.hold_id = hold.id
}

async function saveCurrentBoard() {
  const saved = await boards.saveBoard(studio.currentBoard)
  if (!saved) return
  studio.loadBoard({ ...studio.currentBoard, ...saved })
}

function loadBoardIntoStudio(board) {
  studio.loadBoard(board)
  activePage.value = 'studio'
}

async function renameBoard(board) {
  const renamed = await boards.renameSavedBoard(board)
  if (renamed && studio.currentBoard.saved_id === renamed.saved_id) studio.loadBoard(renamed)
}

async function deleteBoard(board) {
  const deleted = await boards.deleteSavedBoard(board)
  if (deleted && studio.currentBoard.saved_id === board.saved_id) await studio.newBlankBoard()
}

function onUploadFile(uploadFile) {
  library.uploadInfo.file = uploadFile.raw
}

function removeUploadFile() {
  library.uploadInfo.file = null
}

function unlockAiLab() {
  if (aiLabPassword.value === 'DXY666') {
    aiLabUnlocked.value = true
    aiLabPassword.value = ''
    ElMessage.success('实验室已解锁')
    return
  }
  ElMessage.error('实验室密码不正确')
}

function runAiExperiment() {
  ElMessage.info('AI Lab 为实验入口，任务会使用当前岩板数据提交。')
  routeGen.generateRoute(studio.currentBoard)
}
</script>
