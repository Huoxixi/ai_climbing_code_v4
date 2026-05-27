<template>
  <main v-if="!currentUser" class="auth-page">
    <section class="auth-layout" aria-label="Climbing Board Studio 登录">
      <div class="auth-brand">
        <span class="auth-kicker">Climbing Board Studio</span>
        <h1>专业攀岩定线工作台</h1>
        <p>统一管理岩板资产、岩点资源与 AI 线路实验，为教学、研发和商业定线团队提供清晰可靠的创作入口。</p>
        <dl class="auth-summary">
          <div>
            <dt>Board</dt>
            <dd>结构化岩板资产</dd>
          </div>
          <div>
            <dt>Holds</dt>
            <dd>可追踪岩点资源库</dd>
          </div>
          <div>
            <dt>AI Lab</dt>
            <dd>可查询生成任务</dd>
          </div>
        </dl>
      </div>

      <section class="auth-panel">
        <div class="auth-panel-heading">
          <p class="eyebrow">Secure Access</p>
          <h2>{{ authMode === 'login' ? '登录账号' : '创建账号' }}</h2>
          <span>{{ authMode === 'login' ? '进入你的工作台，继续管理线路资产。' : '注册后即可保存和同步你的定线数据。' }}</span>
        </div>
        <el-form class="auth-form" @submit.prevent>
          <el-input v-model="authForm.email" type="email" placeholder="邮箱" autocomplete="email" :prefix-icon="Message" />
          <el-input
            v-model="authForm.password"
            type="password"
            show-password
            placeholder="密码"
            autocomplete="current-password"
            :prefix-icon="Lock"
            @keyup.enter="submitAuth"
          />
          <el-input v-if="authMode === 'register'" v-model="authForm.name" placeholder="显示名" autocomplete="name" :prefix-icon="User" />
          <el-alert v-if="authSuccess" type="success" :closable="false" :title="authSuccess" />
          <el-alert v-if="authError" type="error" :closable="false" :title="authError" />
          <div class="auth-actions">
            <el-button type="primary" :loading="authLoading" :icon="Right" @click="submitAuth">
              {{ authMode === 'login' ? '登录' : '注册' }}
            </el-button>
            <el-button text @click="toggleAuthMode">
              {{ authMode === 'login' ? '创建账号' : '返回登录' }}
            </el-button>
          </div>
        </el-form>
        <p class="auth-footnote">数据访问由 Supabase Auth 保护。前端仅使用 publishable key。</p>
      </section>
    </section>
  </main>

  <AppShell
    v-else
    v-model:active="activePage"
    :title="pageTitle"
    :board-label="studio.currentBoardSpec.label"
    :hold-count="studio.placedHolds.length"
    :dirty="studio.unsavedChanges"
    :user-email="currentUser.email"
    @logout="handleLogout"
  >
    <section v-if="activePage === 'dashboard'" class="page dashboard-page">
      <div class="workbench-hero">
        <div>
          <p class="eyebrow">Operations Dashboard</p>
          <h2>定线工作台总览</h2>
          <p>集中查看当前岩板、资源库和 AI 实验状态，快速进入高频工作流。</p>
        </div>
        <div class="command-row">
          <el-button type="primary" :icon="Plus" @click="startBlankStudio">新建岩板</el-button>
          <el-button :icon="Collection" @click="activePage = 'library'">管理岩点库</el-button>
          <el-button :icon="Histogram" @click="activePage = 'ai-lab'">进入 AI Lab</el-button>
        </div>
      </div>

      <div class="metric-grid">
        <div><strong>{{ studio.placedHolds.length }}</strong><span>当前岩点</span></div>
        <div><strong>{{ studio.routeSteps.length }}</strong><span>Beta 动作</span></div>
        <div><strong>{{ boards.savedBoards.length }}</strong><span>岩板资产</span></div>
        <div><strong>{{ library.managedHolds.length }}</strong><span>岩点资源</span></div>
      </div>

      <section class="section-block">
        <div class="section-heading">
          <div>
            <p class="eyebrow">Board Templates</p>
            <h3>选择岩板模板</h3>
          </div>
          <el-button type="primary" plain :icon="DocumentChecked" @click="createFromTemplate(selectedDashboardTemplateId)">使用当前模板</el-button>
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
        <div class="template-detail-panel">
          <div>
            <h3>{{ selectedDashboardTemplate.label }}</h3>
            <p>{{ selectedDashboardTemplate.description }}</p>
          </div>
          <div class="template-detail-meta">
            <span>{{ selectedDashboardTemplate.cellLabel }}</span>
            <span>{{ selectedDashboardTemplate.angleLabel }}</span>
            <span>{{ selectedDashboardTemplate.total_holes }} 孔位</span>
            <span>{{ selectedDashboardTemplate.material }}</span>
          </div>
        </div>
      </section>

      <div class="dashboard-grid">
        <section class="section-block">
          <div class="section-heading">
            <div>
              <p class="eyebrow">Recent Boards</p>
              <h3>最近岩板</h3>
            </div>
            <el-button text @click="activePage = 'boards'">查看全部</el-button>
          </div>
          <div v-if="!boards.savedBoards.length" class="empty-state">
            <strong>暂无已保存岩板</strong>
            <span>从 Studio 新建并保存第一块岩板后，它会显示在这里。</span>
          </div>
          <button v-for="board in boards.savedBoards.slice(0, 5)" :key="board.saved_id || board.route_name" class="asset-row" @click="loadBoardIntoStudio(board)">
            <span>{{ board.route_name || '未命名岩板' }}</span>
            <small>{{ board.beta_sequence?.length || 0 }} Beta / {{ board.placed_holds?.length || 0 }} 岩点</small>
          </button>
        </section>

        <section class="section-block">
          <div class="section-heading">
            <div>
              <p class="eyebrow">Current State</p>
              <h3>工作状态</h3>
            </div>
            <span class="state-badge" :class="{ dirty: studio.unsavedChanges }">{{ studio.unsavedChanges ? '有未保存修改' : '已同步' }}</span>
          </div>
          <div class="state-list">
            <span>岩板：{{ studio.currentBoardSpec.cellLabel }}</span>
            <span>规格：{{ studio.currentBoardSpec.physicalLabel }}</span>
            <span>孔距：{{ studio.currentBoardSpec.spacingLabel }}</span>
            <span>材质：{{ studio.currentBoardSpec.material }}</span>
            <span>模式：手动定线 + AI 实验</span>
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
              <div v-if="!library.filteredHolds.length" class="empty-text">暂无匹配岩点。请刷新资源库或上传新岩点。</div>
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
          <h2>岩点资源库</h2>
        </div>
        <el-button :icon="Refresh" :loading="library.loading" @click="library.fetchAllHoldData">刷新资源库</el-button>
      </div>
      <div class="library-grid">
        <section class="section-block upload-panel">
          <div>
            <p class="eyebrow">Upload</p>
            <h3>上传岩点</h3>
          </div>
          <el-select v-model="library.uploadInfo.hold_type">
            <el-option v-for="type in library.holdTypes" :key="type" :label="type" :value="type" />
          </el-select>
          <el-input v-model="library.uploadInfo.variant" placeholder="变体名称，例如 large_crimp_01" />
          <el-upload :auto-upload="false" :show-file-list="true" :limit="1" :on-change="onUploadFile" :on-remove="removeUploadFile">
            <el-button :icon="Upload">选择图片</el-button>
          </el-upload>
          <el-button type="primary" :loading="library.loading" @click="library.uploadImage">上传</el-button>
        </section>

        <section class="section-block">
          <div class="section-heading">
            <div>
              <p class="eyebrow">Inventory</p>
              <h3>已录入岩点</h3>
            </div>
            <span class="state-badge">{{ library.filteredHolds.length }} / {{ library.managedHolds.length }}</span>
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
          <div v-if="!library.filteredHolds.length" class="empty-state">
            <strong>暂无岩点资源</strong>
            <span>上传岩点或导入系统资源后，可在 Studio 中选择使用。</span>
          </div>
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
        <div v-if="!boards.savedBoards.length" class="empty-state">
          <strong>暂无保存的岩板资产</strong>
          <span>完成一次保存后，岩板会在这里形成可追踪资产。</span>
        </div>
      </div>
    </section>

    <section v-else class="page ai-page">
      <div class="lab-panel" :class="{ locked: !aiLabUnlocked }">
        <p class="eyebrow">AI Lab</p>
        <template v-if="!aiLabUnlocked">
          <h2 class="lab-title">实验室入口</h2>
          <p class="lab-copy">AI Lab 用于提交当前岩板给生成或审查任务。进入前请输入访问密码。</p>
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
        <h2>实验任务</h2>
        <div class="experiment-controls">
          <el-segmented
            v-model="aiExperiment.mode"
            :options="[
              { label: '重新组合路线', value: 'compose_route' },
              { label: '提出修改建议', value: 'review_route' },
            ]"
          />
          <el-input
            v-model="aiExperiment.user_requirements"
            type="textarea"
            :rows="3"
            placeholder="输入本次实验要求，例如：增加动态动作，或检查脚点是否过高"
          />
        </div>
        <div class="command-row">
          <el-button type="primary" :loading="routeGen.loading" @click="runAiExperiment">提交当前岩板</el-button>
          <el-button v-if="routeGen.loading" @click="routeGen.cancelGeneration">取消任务</el-button>
          <el-button @click="activePage = 'studio'">返回 Studio</el-button>
        </div>
        <el-alert v-if="routeGen.taskId" type="info" :closable="false" :title="`任务 ID：${routeGen.taskId}`" />
        <el-alert v-if="routeGen.error" type="error" :closable="false" :title="routeGen.error" />
        <section v-if="routeGen.result" class="experiment-result">
          <template v-if="routeGen.result.mode === 'compose_route'">
            <article v-for="route in routeGen.result.selected_routes" :key="route.route_name" class="result-card">
              <strong>{{ route.route_name }}</strong>
              <p>{{ route.setter_commentary }}</p>
              <span>{{ route.placed_holds?.length || 0 }} 岩点 / {{ route.beta_sequence?.length || 0 }} Beta</span>
              <el-button @click="loadBoardIntoStudio(route)">载入 Studio</el-button>
            </article>
          </template>
          <template v-else>
            <strong>{{ routeGen.result.review_summary }}</strong>
            <p>风险等级：{{ routeGen.result.risk_level }}</p>
            <article v-for="suggestion in routeGen.result.suggestions" :key="suggestion.title" class="result-card">
              <strong>{{ suggestion.title }}</strong>
              <p>{{ suggestion.detail }}</p>
              <span v-if="suggestion.hold_ids?.length">相关岩点：{{ suggestion.hold_ids.join(', ') }}</span>
            </article>
          </template>
        </section>
      </div>
    </section>
  </AppShell>
</template>

<script setup>
import { computed, defineComponent, h, onMounted, reactive, ref } from 'vue'
import { Collection, Delete, DocumentChecked, Edit, EditPen, Histogram, Lock, Message, Plus, Refresh, Right, Search, Upload, User } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import AppShell from './components/AppShell.vue'
import { useAuth } from './composables/useAuth'
import BoardCanvas from './components/BoardCanvas.vue'
import InspectorPanel from './components/InspectorPanel.vue'
import { useBoardPersistence } from './composables/useBoardPersistence'
import { useHoldLibrary } from './composables/useHoldLibrary'
import { useRouteGeneration } from './composables/useRouteGeneration'
import { useStudioEditor } from './composables/useStudioEditor'

const activePage = ref('dashboard')
const { currentUser, login, register, logout } = useAuth()
const authMode = ref('login')
const authLoading = ref(false)
const authError = ref('')
const authSuccess = ref('')
const authForm = reactive({
  email: '',
  password: '',
  name: '',
})
const library = reactive(useHoldLibrary())
const boards = reactive(useBoardPersistence())
const studio = reactive(useStudioEditor())
const routeGen = reactive(useRouteGeneration())
const selectedDashboardTemplateId = ref(studio.activeBoardPresetId)
const aiLabPassword = ref('')
const aiLabUnlocked = ref(false)
const aiExperiment = reactive({
  mode: 'compose_route',
  user_requirements: '',
})

async function submitAuth() {
  authError.value = ''
  authSuccess.value = ''
  authLoading.value = true
  try {
    if (authMode.value === 'register') {
      const user = await register(authForm)
      if (!user) {
        authSuccess.value = '注册已提交。请先打开邮箱完成确认，然后返回登录。'
        authForm.password = ''
        return
      }
    } else {
      await login(authForm)
    }
    await Promise.all([library.fetchAllHoldData(), boards.fetchMyBoards()])
  } catch (error) {
    authError.value = normalizeAuthError(error)
  } finally {
    authLoading.value = false
  }
}

function toggleAuthMode() {
  authMode.value = authMode.value === 'login' ? 'register' : 'login'
  authError.value = ''
  authSuccess.value = ''
}

function normalizeAuthError(error) {
  const message = error?.message || ''
  if (message.toLowerCase().includes('email not confirmed')) {
    return '邮箱尚未确认。请先点击 Supabase 发送的确认邮件，再返回登录。'
  }
  return message || '登录失败'
}

async function handleLogout() {
  await logout()
  activePage.value = 'dashboard'
}

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
      const color = { Jug: '#24876b', Crimp: '#d94b52', Sloper: '#c8912f', Pinch: '#7457d8', Pocket: '#2f72c8', Foot: '#718096' }[props.hold.hold_type] || '#24876b'
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
  if (currentUser.value) await Promise.all([library.fetchAllHoldData(), boards.fetchMyBoards()])
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
  ElMessage.info('已提交当前岩板数据，AI Lab 将返回可查询任务结果。')
  routeGen.generateRoute({
    mode: aiExperiment.mode,
    board: studio.currentBoard,
    user_requirements: aiExperiment.user_requirements,
    target_difficulty: studio.currentBoard.difficulty || 'V3',
  })
}
</script>
