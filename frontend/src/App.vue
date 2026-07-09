<template>
  <main v-if="!currentUser" class="auth-page">
    <section class="auth-layout" aria-label="Climbing Board Studio 登录">
      <div class="auth-brand">
        <span class="auth-kicker">Climbing Board Studio</span>
        <h1>攀岩定线工作台</h1>
        <p>管理岩板、岩点资产、Beta 序列与实验任务。</p>
        <dl class="auth-summary">
          <div><dt>Board</dt><dd>岩板规格与线路资产</dd></div>
          <div><dt>Holds</dt><dd>岩点库存与放置</dd></div>
          <div><dt>AI Lab</dt><dd>实验任务入口</dd></div>
        </dl>
      </div>

      <section class="auth-panel">
        <div class="auth-panel-heading">
          <p class="eyebrow">Secure Access</p>
          <h2>{{ authMode === 'login' ? '登录账号' : '创建账号' }}</h2>
          <span>{{ authMode === 'login' ? '进入工作台继续管理线路资产。' : '注册后即可保存和同步定线数据。' }}</span>
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
            <el-button :loading="authLoading" :icon="Right" @click="skipAuth">
              跳过登录
            </el-button>
            <el-button text @click="toggleAuthMode">
              {{ authMode === 'login' ? '创建账号' : '返回登录' }}
            </el-button>
          </div>
        </el-form>
        <p class="auth-footnote">跳过登录会进入本地体验模式，数据保存在本机 fallback 存储中。</p>
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
          <h2>工作台总览</h2>
          <p>选择岩板规格、查看资产状态，并进入 Studio 或 AI Lab。</p>
        </div>
        <div class="command-row">
          <el-button type="primary" :icon="Plus" @click="startBlankStudio">新建岩板</el-button>
          <el-button :icon="Collection" @click="activePage = 'library'">管理岩点</el-button>
          <el-button :icon="Grid" @click="activePage = 'standard-board'">标准板库</el-button>
          <el-button :icon="Histogram" @click="activePage = 'ai-lab'">进入 AI Lab</el-button>
        </div>
      </div>

      <div class="metric-grid">
        <div><strong>{{ studio.placedHolds.length }}</strong><span>当前岩点</span></div>
        <div><strong>{{ studio.routeSteps.length }}</strong><span>Beta 动作</span></div>
        <div><strong>{{ boards.savedBoards.length }}</strong><span>岩板资产</span></div>
        <div><strong>{{ library.managedHolds.length }}</strong><span>岩点资产</span></div>
      </div>

      <section class="section-block">
        <div class="section-heading">
          <div>
            <p class="eyebrow">Board Templates</p>
            <h3>选择岩板规格</h3>
          </div>
          <el-button type="primary" plain :icon="DocumentChecked" @click="createFromTemplate(selectedDashboardTemplateId)">确认使用</el-button>
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
            <small>{{ template.physicalLabel || template.angleLabel }}</small>
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
            <strong>暂无保存的岩板资产</strong>
            <span>保存岩板后会在这里显示。</span>
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
              <h3>当前状态</h3>
            </div>
            <span class="state-badge">{{ studio.unsavedChanges ? '未保存' : '已同步' }}</span>
          </div>
          <div class="state-list">
            <span>岩板：{{ studio.currentBoardSpec.cellLabel }}</span>
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
          <section class="section-block">
            <div class="section-heading">
              <div>
                <p class="eyebrow">Hold Palette</p>
                <h3>岩点选择</h3>
              </div>
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
            <span>上传岩点后可在 Studio 中使用。</span>
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
          <span>完成保存后会在这里显示。</span>
        </div>
      </div>
    </section>

    <section v-else-if="activePage === 'standard-board'" class="page standard-board-page">
      <div class="page-header">
        <div>
          <p class="eyebrow">Standard Board Dataset</p>
          <h2>标准训练板线路库</h2>
        </div>
        <div class="command-row">
          <el-button :icon="Refresh" :loading="standardBoard.loading" @click="fetchStandardRoutes">刷新</el-button>
          <el-button type="primary" :loading="standardBoard.generating" @click="generateStandardRoute">生成验证线路</el-button>
        </div>
      </div>

      <section class="section-block standard-filters">
        <el-select v-model="standardBoard.filters.difficulty" placeholder="难度">
          <el-option v-for="grade in standardBoard.difficulties" :key="grade" :label="grade" :value="grade" />
        </el-select>
        <el-select v-model="standardBoard.filters.sort" placeholder="排序">
          <el-option label="综合评分优先" value="score_desc" />
          <el-option label="重复次数优先" value="repeats_desc" />
          <el-option label="横向跨度优先" value="span_desc" />
          <el-option label="岩点更少优先" value="holds_asc" />
        </el-select>
        <el-checkbox v-model="standardBoard.filters.benchmark_only">只看标杆线</el-checkbox>
        <el-button type="primary" plain :loading="standardBoard.loading" @click="fetchStandardRoutes">应用筛选</el-button>
      </section>

      <el-alert v-if="standardBoard.error" type="error" :closable="false" :title="standardBoard.error" />
      <el-alert
        v-if="standardBoard.generatedMeta"
        type="success"
        :closable="false"
        :title="`已生成标准板线路：重用率 ${(standardBoard.generatedMeta.reuse_rate * 100).toFixed(1)}%，${standardBoard.generatedMeta.reuse_quality}`"
      />

      <div class="standard-board-layout">
        <section class="section-block route-list-panel">
          <div class="section-heading">
            <div>
              <p class="eyebrow">Routes</p>
              <h3>{{ standardBoard.total }} 条匹配线路</h3>
            </div>
            <span class="state-badge">虚拟点亮</span>
          </div>
          <div v-if="!standardBoard.routes.length" class="empty-state">
            <strong>暂无匹配线路</strong>
            <span>调整难度或标杆线条件后再试。</span>
          </div>
          <button
            v-for="route in standardBoard.routes"
            :key="route.source_id"
            class="standard-route-row"
            :class="{ active: standardBoard.selected?.source_id === route.source_id }"
            @click="loadStandardRoute(route.source_id)"
          >
            <span>
              <strong>{{ route.display_name }}</strong>
              <small>{{ route.v_grade }} / Font {{ route.grade }} / {{ route.features.hold_count }} 点 / {{ tierLabel(route.quality_tier) }}</small>
            </span>
            <span>
              <em>{{ route.quality_score ?? Math.round(route.score) }}</em>
              <small class="quality-tier">{{ tierLabel(route.quality_tier) }}</small>
              <small>{{ route.repeats }} repeats</small>
            </span>
          </button>
        </section>

        <section class="standard-preview-column">
          <div class="standard-preview-canvas">
            <BoardCanvas
              :columns="studio.coordinateColumns"
              :rows="studio.coordinateRows"
              :base-holds="standardBoard.selected?.board_setup || []"
              :route-overlay="standardBoard.selected?.route_overlay || standardBoard.selected?.virtual_led || []"
              :holds="standardBoard.selected?.board_asset?.placed_holds || []"
              :route-steps="standardBoard.selected?.board_asset?.beta_sequence || []"
              :selected-hold="null"
              :board-spec="standardBoard.selected?.board_asset?.board_spec || studio.currentBoardSpec"
              :frame-style="studio.boardFrameStyle"
              :get-coord-style="studio.getCoordStyle"
              :resolve-hold-visual="library.resolveHoldVisual"
              @place="() => {}"
              @select="() => {}"
            />
          </div>

          <section class="section-block standard-detail-panel">
            <template v-if="standardBoard.selected">
              <div class="section-heading">
                <div>
                  <p class="eyebrow">Selected Route</p>
                  <h3>{{ standardBoard.selected.display_name }}</h3>
                </div>
                <el-button type="primary" plain @click="loadStandardIntoStudio">载入 Studio</el-button>
              </div>
              <div class="standard-stats">
                <span>{{ standardBoard.selected.v_grade }}</span>
                <span>{{ standardBoard.selected.quality_score ?? 0 }} 分</span>
                <span>{{ tierLabel(standardBoard.selected.quality_tier) }}</span>
                <span>{{ standardBoard.selected.features.x_span }} 列跨度</span>
                <span>{{ standardBoard.selected.features.y_span }} 行高度</span>
                <span>{{ standardBoard.selected.validation?.valid_for_climb ? '可攀路线' : '需复核' }}</span>
              </div>
              <div class="score-breakdown">
                <span v-for="item in scoreBreakdownItems(standardBoard.selected.score_breakdown)" :key="item.key">
                  {{ item.label }} {{ item.value }}
                </span>
              </div>
              <div class="marker-legend">
                <span>手起点 {{ standardBoard.selected.marker_summary?.counts?.start_hands || 0 }}</span>
                <span>脚起点 {{ standardBoard.selected.marker_summary?.counts?.start_feet || 0 }}</span>
                <span>中间点 {{ standardBoard.selected.features.mid_count }}</span>
                <span>终点 {{ standardBoard.selected.features.end_count }}</span>
              </div>
              <div v-if="standardBoard.selected.review_reasons?.length" class="review-reasons">
                <span v-for="reason in standardBoard.selected.review_reasons" :key="reason">{{ reason }}</span>
              </div>
              <div class="virtual-led-list">
                <span v-for="point in standardBoard.selected.route_overlay || standardBoard.selected.virtual_led" :key="point.coord_id">
                  {{ point.coord_id }} {{ markerLabel(point.role) }} -> LED {{ point.led_index }}
                </span>
              </div>
            </template>
            <div v-else class="empty-state">
              <strong>选择一条线路</strong>
              <span>系统会在网页画布中进行虚拟点亮，不连接任何真实控制器。</span>
            </div>
          </section>
        </section>
      </div>
    </section>

    <section v-else class="page ai-page">
      <div class="lab-panel">
        <p class="eyebrow">AI Lab</p>
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
import { Collection, Delete, DocumentChecked, Edit, EditPen, Grid, Histogram, Lock, Message, Plus, Refresh, Right, Search, Upload, User } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import AppShell from './components/AppShell.vue'
import BoardCanvas from './components/BoardCanvas.vue'
import InspectorPanel from './components/InspectorPanel.vue'
import { useAuth } from './composables/useAuth'
import { useBoardPersistence } from './composables/useBoardPersistence'
import { useHoldLibrary } from './composables/useHoldLibrary'
import { useRouteGeneration } from './composables/useRouteGeneration'
import { useStudioEditor } from './composables/useStudioEditor'
import standardBoardService from './services/standardBoardService'

const activePage = ref('dashboard')
const { currentUser, login, register, skipLogin, logout } = useAuth()
const authMode = ref('login')
const authLoading = ref(false)
const authError = ref('')
const authSuccess = ref('')
const authForm = reactive({ email: '', password: '', name: '' })
const library = reactive(useHoldLibrary())
const boards = reactive(useBoardPersistence())
const studio = reactive(useStudioEditor())
const routeGen = reactive(useRouteGeneration())
const selectedDashboardTemplateId = ref(studio.activeBoardPresetId)
const aiExperiment = reactive({ mode: 'compose_route', user_requirements: '' })
const standardBoard = reactive({
  loading: false,
  generating: false,
  error: '',
  routes: [],
  selected: null,
  generatedMeta: null,
  total: 0,
  difficulties: ['V0', 'V1', 'V2', 'V3', 'V4', 'V5'],
  filters: {
    difficulty: 'V3',
    benchmark_only: false,
    sort: 'score_desc',
    limit: 24,
    offset: 0,
  },
})

const pageTitle = computed(() => ({
  dashboard: '总览',
  studio: 'Studio 工作台',
  library: '岩点库',
  boards: '岩板资产',
  'standard-board': '标准板库',
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
  if (currentUser.value) await Promise.all([library.fetchAllHoldData(), boards.fetchMyBoards(), fetchStandardRoutes()])
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
    await Promise.all([library.fetchAllHoldData(), boards.fetchMyBoards(), fetchStandardRoutes()])
  } catch (error) {
    authError.value = normalizeAuthError(error)
  } finally {
    authLoading.value = false
  }
}

async function skipAuth() {
  authError.value = ''
  authSuccess.value = ''
  authLoading.value = true
  try {
    await skipLogin()
    await Promise.all([library.fetchAllHoldData(), boards.fetchMyBoards(), fetchStandardRoutes()])
    ElMessage.success('已进入本地体验模式')
  } catch (error) {
    authError.value = error?.message || '跳过登录失败'
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

async function fetchStandardRoutes() {
  standardBoard.loading = true
  standardBoard.error = ''
  try {
    const response = await standardBoardService.listRoutes(standardBoard.filters)
    standardBoard.routes = response.data?.routes || []
    standardBoard.total = response.data?.total || 0
    const selectedStillVisible = standardBoard.routes.some((route) => route.source_id === standardBoard.selected?.source_id)
    if ((!standardBoard.selected || !selectedStillVisible) && standardBoard.routes.length) {
      await loadStandardRoute(standardBoard.routes[0].source_id)
    }
  } catch (error) {
    standardBoard.error = error.response?.data?.detail || error.message || '标准板线路加载失败'
  } finally {
    standardBoard.loading = false
  }
}

async function loadStandardRoute(sourceId) {
  standardBoard.error = ''
  try {
    const response = await standardBoardService.getRoute(sourceId)
    standardBoard.selected = response.data
  } catch (error) {
    standardBoard.error = error.response?.data?.detail || error.message || '标准板线路详情加载失败'
  }
}

async function generateStandardRoute() {
  standardBoard.generating = true
  standardBoard.error = ''
  standardBoard.generatedMeta = null
  try {
    const response = await standardBoardService.generateRoute({
      target_difficulty: standardBoard.filters.difficulty,
      benchmark_only: standardBoard.filters.benchmark_only,
      variation: true,
    })
    standardBoard.selected = response.data?.route || null
    standardBoard.generatedMeta = {
      reuse_rate: response.data?.reuse_rate || 0,
      reuse_quality: response.data?.reuse_quality || 'below_pass',
    }
    ElMessage.success('标准板线路已生成并完成虚拟点亮')
  } catch (error) {
    standardBoard.error = error.response?.data?.detail || error.message || '标准板线路生成失败'
  } finally {
    standardBoard.generating = false
  }
}

function loadStandardIntoStudio() {
  if (!standardBoard.selected?.board_asset) return
  studio.loadBoard(standardBoard.selected.board_asset)
  activePage.value = 'studio'
}

function tierLabel(tier) {
  return {
    excellent: '优质',
    good: '好线',
    climbable: '可爬',
    review: '需复核',
    rejected: '已淘汰',
  }[tier] || '需复核'
}

function markerLabel(role) {
  return {
    start: '起点',
    start_hand: '手起点',
    start_foot: '脚起点',
    mid: '中间点',
    end: '终点',
  }[role] || role
}

function scoreBreakdownItems(breakdown = {}) {
  const labels = {
    movement_quality: '动作质量',
    climbable_structure: '可攀结构',
    grade_confidence: '难度可信',
    aesthetics: '线路变化',
    data_support: '数据辅助',
  }
  return Object.entries(labels)
    .filter(([key]) => breakdown[key] !== undefined)
    .map(([key, label]) => ({ key, label, value: Number(breakdown[key]).toFixed(1) }))
}

function onUploadFile(uploadFile) {
  library.uploadInfo.file = uploadFile.raw
}

function removeUploadFile() {
  library.uploadInfo.file = null
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
