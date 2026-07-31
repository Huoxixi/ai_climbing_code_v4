<template>
  <AppShell
    :active="activePage"
    @update:active="changePage"
    :title="pageTitle"
    :board-label="studio.currentBoardSpec.label"
    :hold-count="studio.placedHolds.length"
    :dirty="studio.unsavedChanges"
    :simulation-enabled="simulationEnabled"
  >
    <section v-if="activePage === 'dashboard'" class="page dashboard-page">
      <div class="workbench-hero">
        <div>
          <p class="eyebrow">本地工作台</p>
          <h2>工作台总览</h2>
          <p>选择岩板规格、查看资产状态，并进入定线工作台或 AI 实验室。</p>
        </div>
        <div class="command-row">
          <el-button type="primary" :icon="Plus" @click="startBlankStudio">新建岩板</el-button>
          <el-button :icon="Collection" @click="activePage = 'library'">管理岩点</el-button>
          <el-button :icon="Grid" @click="activePage = 'standard-board'">标准板库</el-button>
          <el-button v-if="simulationEnabled" :icon="Histogram" @click="activePage = 'simulation'">仿真审核</el-button>
          <el-button :icon="Histogram" @click="activePage = 'ai-lab'">进入 AI 实验室</el-button>
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
            <p class="eyebrow">规格选择</p>
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
            <small>{{ template.ai_supported ? '支持 AI 组合与审核' : '仅支持手工定线' }}</small>
          </button>
        </div>
        <div class="template-detail-panel">
          <div>
            <h3>{{ selectedDashboardTemplate.label }}</h3>
            <p>{{ selectedDashboardTemplate.description }}</p>
          </div>
          <div class="template-detail-meta">
            <span>{{ selectedDashboardTemplate.cellLabel }}</span>
            <span>{{ selectedDashboardTemplate.physicalLabel }}</span>
            <span>孔距 {{ selectedDashboardTemplate.spacingLabel }}</span>
            <span>{{ selectedDashboardTemplate.ai_supported ? 'AI 可用' : '仅手工定线' }}</span>
          </div>
        </div>
      </section>

      <div class="dashboard-grid">
        <section class="section-block">
          <div class="section-heading">
            <div>
              <p class="eyebrow">最近编辑</p>
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
            <small>{{ board.beta_sequence?.length || 0 }} Beta / {{ board.placed_holds?.length || 0 }} 岩点 / {{ workflowLabel(board) }}</small>
          </button>
        </section>

        <section class="section-block">
          <div class="section-heading">
            <div>
              <p class="eyebrow">当前编辑状态</p>
              <h3>当前状态</h3>
            </div>
            <span class="state-badge">{{ studio.unsavedChanges ? '未保存' : '已同步' }}</span>
          </div>
          <div class="state-list">
            <span>岩板：{{ studio.currentBoardSpec.cellLabel }}</span>
            <span>规格尺寸：{{ studio.currentBoardSpec.physicalLabel }}</span>
            <span>模式：{{ studio.currentBoardSpec.ai_supported ? '手工定线 + AI 辅助' : '仅手工定线' }}</span>
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
                <p class="eyebrow">岩点选择</p>
                <h3>岩点选择</h3>
              </div>
              <el-segmented
                v-model="library.previewMode"
                :options="[{ label: '轮廓', value: 'vector' }, { label: '图片', value: 'image' }]"
              />
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
          <p class="eyebrow">本地岩点资产</p>
          <h2>岩点资源库</h2>
        </div>
        <el-button :icon="Refresh" :loading="library.loading" @click="library.fetchAllHoldData">刷新资源库</el-button>
      </div>
      <div class="library-grid">
        <section class="section-block upload-panel">
          <div>
            <p class="eyebrow">录入新岩点</p>
            <h3>上传岩点</h3>
          </div>
          <el-select v-model="library.uploadInfo.hold_type">
            <el-option v-for="type in library.holdTypes" :key="type" :label="type" :value="type" />
          </el-select>
          <el-input v-model="library.uploadInfo.variant" placeholder="变体名称，例如 large_crimp_01" />
          <small class="upload-help">支持 PNG、JPEG、WebP；白底图片上传后会自动去除背景。</small>
          <el-upload accept="image/png,image/jpeg,image/webp" :auto-upload="false" :show-file-list="true" :limit="1" :on-change="onUploadFile" :on-remove="removeUploadFile">
            <el-button :icon="Upload">选择图片</el-button>
          </el-upload>
          <el-button type="primary" :loading="library.loading" @click="library.uploadImage">上传</el-button>
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
            <el-select v-model="library.typeFilter">
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
              <el-button
                v-if="!library.showArchived"
                text
                type="danger"
                :icon="Delete"
                @click="library.archiveHold(hold.hold_type, hold.variant)"
              >
                归档
              </el-button>
              <el-button v-else text type="primary" @click="library.restoreHold(hold.hold_type, hold.variant)">恢复使用</el-button>
            </article>
          </div>
          <div v-if="!library.filteredHolds.length" class="empty-state">
            <strong>{{ library.showArchived ? '归档箱为空' : '暂无岩点资源' }}</strong>
            <span>{{ library.showArchived ? '归档后的岩点会显示在这里。' : '上传岩点后可在定线工作台中使用。' }}</span>
          </div>
        </section>
      </div>
    </section>

    <section v-else-if="activePage === 'boards'" class="page">
      <div class="page-header">
        <div>
          <p class="eyebrow">本地线路资产</p>
          <h2>岩板资产</h2>
        </div>
        <div class="command-row">
          <el-button :icon="Refresh" :loading="boards.loading" @click="boards.fetchMyBoards">刷新</el-button>
          <el-button type="primary" :icon="Plus" @click="startBlankStudio">新建岩板</el-button>
        </div>
      </div>
      <el-segmented
        v-model="boardAssetMode"
        class="board-mode-switch"
        :options="[{ label: '资产列表', value: 'list' }, { label: '岩板对照', value: 'compare' }]"
      />

      <template v-if="boardAssetMode === 'list'">
        <el-segmented
          v-model="savedBoardView"
          :options="[
            { label: `已启用 ${boards.savedBoards.length}`, value: 'active' },
            { label: `归档箱 ${boards.archivedBoards.length}`, value: 'archived' },
          ]"
        />
        <section class="section-block board-tag-filter-panel">
          <div class="section-heading">
            <div>
              <h3>按标签筛选</h3>
              <span>已匹配 {{ filteredSavedBoards.length }} / {{ visibleSavedBoards.length }} 个岩板资产</span>
            </div>
            <el-button text :disabled="!savedBoardFilters.tagIds.length" @click="clearSavedBoardTags">清除标签</el-button>
          </div>
          <div class="tag-filter-controls">
            <el-select v-model="savedBoardFilters.tagIds" multiple clearable collapse-tags collapse-tags-tooltip placeholder="选择标签">
              <el-option-group v-for="group in savedBoardTagGroups" :key="group.key" :label="group.label">
                <el-option v-for="tag in group.tags" :key="tag.id" :label="tag.label" :value="tag.id" />
              </el-option-group>
            </el-select>
            <el-segmented
              v-model="savedBoardFilters.match"
              :options="[{ label: '全部满足', value: 'all' }, { label: '满足任一', value: 'any' }]"
            />
          </div>
        </section>
        <div class="board-assets">
          <article v-for="board in filteredSavedBoards" :key="board.saved_id || board.route_name" class="board-card">
            <div>
              <strong>{{ board.route_name || '未命名岩板' }}</strong>
              <span>{{ boardSpecDisplayLabel(board) }} / {{ board.placed_holds?.length || 0 }} 岩点 / {{ board.beta_sequence?.length || 0 }} Beta</span>
              <div class="board-readiness">
                <span class="state-badge" :class="{ ready: board.workflow_status === 'ready_for_review' }">{{ workflowLabel(board) }}</span>
                <span v-if="board.ai_eligible && !board.archived_at" class="state-badge ready">AI 可用</span>
                <span v-else-if="!board.archived_at" class="state-badge">AI 不可用</span>
              </div>
              <small v-if="board.readiness_issues?.length" class="readiness-note">{{ board.readiness_issues.slice(0, 2).join('；') }}</small>
              <div class="route-tag-list" aria-label="岩板标签">
                <span v-for="tag in resolvedBoardTags(board)" :key="tag" class="route-tag">{{ tagLabel(tag) }}</span>
              </div>
            </div>
            <div class="card-actions">
              <template v-if="!board.archived_at">
                <el-button :icon="Edit" @click="loadBoardIntoStudio(board)">载入编辑</el-button>
                <el-button :icon="EditPen" @click="renameBoard(board)">重命名</el-button>
                <el-button type="danger" plain :icon="Delete" @click="archiveBoard(board)">归档</el-button>
              </template>
              <el-button v-else type="primary" plain @click="restoreBoard(board)">恢复岩板</el-button>
            </div>
          </article>
          <div v-if="!visibleSavedBoards.length" class="empty-state">
            <strong>{{ savedBoardView === 'archived' ? '归档箱为空' : '暂无保存的岩板资产' }}</strong>
            <span>{{ savedBoardView === 'archived' ? '归档资产可以在这里恢复。' : '完成保存后会在这里显示。' }}</span>
          </div>
          <div v-else-if="!filteredSavedBoards.length" class="empty-state">
            <strong>没有匹配的岩板资产</strong>
            <span>清除或调整标签条件后再试。</span>
          </div>
        </div>
      </template>

      <template v-else>
        <section class="section-block board-compare-picker">
          <div class="section-heading">
            <div>
              <h3>选择 2–4 块已启用岩板</h3>
              <span>第一块自动作为基准；对照仅在当前页面保留，不会修改或保存岩板。</span>
            </div>
            <el-button text :disabled="!compareBoardIds.length" @click="clearBoardComparison">清空对照</el-button>
          </div>
          <el-checkbox-group v-model="compareBoardIds" :max="4" class="board-compare-options">
            <el-checkbox
              v-for="board in boards.savedBoards"
              :key="board.saved_id"
              :value="board.saved_id"
              border
            >
              {{ board.route_name || '未命名岩板' }} · {{ board.board_spec?.cellLabel || `${board.board_spec?.columns || board.board_spec?.cols || 11} × ${board.board_spec?.rows || 18}` }}
            </el-checkbox>
          </el-checkbox-group>
          <p v-if="boards.savedBoards.length < 2" class="control-help">至少需要两块已启用岩板。归档岩板恢复后才可加入对照。</p>
          <p v-else-if="compareBoardIds.length < 2" class="control-help">还需选择 {{ 2 - compareBoardIds.length }} 块岩板才能开始对照。</p>
        </section>

        <div v-if="comparedBoards.length >= 2" :class="['board-comparison-grid', `count-${comparedBoards.length}`]">
          <BoardComparisonPanel
            v-for="(board, index) in comparedBoards"
            :key="board.saved_id"
            :board="board"
            :reference="index === 0 ? null : comparedBoards[0]"
            :label="index === 0 ? '基准岩板' : `对照岩板 ${index}`"
            :baseline="index === 0"
            :can-set-baseline="index > 0"
            removable
            :resolve-hold-visual="library.resolveHoldVisual"
            @set-baseline="setComparisonBaseline(board.saved_id)"
            @remove="removeComparedBoard(board.saved_id)"
          />
        </div>
      </template>
    </section>

    <section v-else-if="activePage === 'standard-board'" class="page standard-board-page">
      <div class="page-header">
        <div>
          <p class="eyebrow">标准线路数据</p>
          <h2>标准线路库</h2>
        </div>
        <div class="command-row">
          <el-button :icon="Refresh" :loading="standardBoard.loading" @click="fetchStandardRoutes">刷新</el-button>
          <el-button type="primary" :loading="standardBoard.generating" @click="generateStandardRoute">生成候选线路</el-button>
        </div>
      </div>

      <el-segmented
        v-model="standardBoard.mode"
        :options="[
          { label: '线路库', value: 'routes' },
          { label: '待修复路线', value: 'repairs' },
        ]"
        @change="handleStandardModeChange"
      />

      <section class="section-block standard-filters">
        <el-input
          v-if="standardBoard.mode === 'routes'"
          v-model="standardBoard.filters.q"
          clearable
          placeholder="搜索名称、来源 ID 或定线者"
          :prefix-icon="Search"
          @keyup.enter="applyStandardFilters"
        />
        <el-select v-if="standardBoard.mode === 'routes'" v-model="standardBoard.filters.difficulty" placeholder="难度">
          <el-option v-for="grade in standardBoard.difficulties" :key="grade" :label="grade" :value="grade" />
        </el-select>
        <el-select v-if="standardBoard.mode === 'routes'" v-model="standardBoard.filters.sort" placeholder="排序">
          <el-option label="综合评分优先" value="score_desc" />
          <el-option label="难度指数从高到低" value="difficulty_score_desc" />
          <el-option label="难度指数从低到高" value="difficulty_score_asc" />
          <el-option label="难度错配优先" value="grade_mismatch_desc" />
          <el-option label="重复次数优先" value="repeats_desc" />
          <el-option label="横向跨度优先" value="span_desc" />
          <el-option label="岩点更少优先" value="holds_asc" />
        </el-select>
        <el-select v-if="standardBoard.mode === 'routes'" v-model="standardBoard.filters.predicted_grade" clearable placeholder="模型复核等级">
          <el-option v-for="grade in standardBoard.difficulties" :key="`predicted-${grade}`" :label="grade" :value="grade" />
        </el-select>
        <el-select v-if="standardBoard.mode === 'routes'" v-model="standardBoard.filters.grade_warning" clearable placeholder="难度复核">
          <el-option label="轻微错配" value="soft" />
          <el-option label="严重错配" value="hard" />
          <el-option label="可信度不足" value="uncertain" />
        </el-select>
        <el-checkbox v-if="standardBoard.mode === 'routes'" v-model="standardBoard.filters.benchmark_only">只看标杆线</el-checkbox>
        <el-select
          v-if="standardBoard.mode === 'routes'"
          v-model="standardBoard.filters.tag_ids"
          multiple
          clearable
          collapse-tags
          collapse-tags-tooltip
          placeholder="路线标签"
        >
          <el-option-group v-for="group in standardRouteTagGroups" :key="group.key" :label="group.label">
            <el-option v-for="tag in group.tags" :key="tag.id" :label="tag.label" :value="tag.id" />
          </el-option-group>
        </el-select>
        <el-segmented
          v-if="standardBoard.mode === 'routes'"
          v-model="standardBoard.filters.tag_match"
          :options="[{ label: '全部满足', value: 'all' }, { label: '满足任一', value: 'any' }]"
        />
        <el-select v-if="standardBoard.mode === 'repairs'" v-model="standardBoard.repairFilters.status" placeholder="修复状态">
          <el-option label="已生成修复候选" value="repaired" />
          <el-option label="可尝试但未通过" value="repairable" />
          <el-option label="不可修复" value="unrepairable" />
        </el-select>
        <el-input
          v-if="standardBoard.mode === 'repairs'"
          v-model="standardBoard.repairFilters.q"
          clearable
          placeholder="搜索名称、来源 ID 或定线者"
          :prefix-icon="Search"
          @keyup.enter="applyRepairFilters"
        />
        <el-button
          type="primary"
          plain
          :loading="standardBoard.mode === 'routes' ? standardBoard.loading : standardBoard.repairLoading"
          @click="standardBoard.mode === 'routes' ? applyStandardFilters() : applyRepairFilters()"
        >
          应用筛选
        </el-button>
      </section>

      <el-alert v-if="standardBoard.error" type="error" :closable="false" :title="standardBoard.error" />
      <el-alert
        v-if="standardBoard.generatedMeta"
        type="success"
        :closable="false"
        :title="`已生成标准板线路：重用率 ${(standardBoard.generatedMeta.reuse_rate * 100).toFixed(1)}%，${reuseQualityLabel(standardBoard.generatedMeta.reuse_quality)}`"
      />

      <div v-if="standardBoard.mode === 'routes'" class="standard-board-layout">
        <section class="section-block route-list-panel">
          <div class="section-heading">
            <div>
              <p class="eyebrow">线路列表</p>
              <h3>{{ standardBoard.total }} 条匹配线路</h3>
            </div>
            <span class="state-badge">坐标预览</span>
          </div>
          <el-skeleton v-if="standardBoard.loading" :rows="8" animated />
          <div v-else-if="!standardBoard.routes.length" class="empty-state">
            <strong>暂无匹配线路</strong>
            <span>调整难度或标杆线条件后再试。</span>
          </div>
          <button
            v-for="route in standardBoard.routes"
            v-show="!standardBoard.loading"
            :key="route.source_id"
            class="standard-route-row"
            :class="{ active: standardBoard.selected?.source_id === route.source_id }"
            @click="loadStandardRoute(route.source_id)"
          >
            <span>
              <strong>{{ route.display_name }}</strong>
              <small>MoonBoard 原始 {{ route.grade }} / 模型复核 {{ route.predicted_grade || '-' }} / {{ route.features.hold_count }} 点</small>
              <small>{{ confidenceLabel(route.confidence_tier) }} · {{ calibrationLabel(route.calibration_status) }}</small>
              <small>{{ route.setter_name }} · {{ route.is_benchmark ? 'Benchmark' : '普通线路' }}</small>
              <small>{{ gradeWarningLabel(route) }}</small>
              <span class="route-tag-list">
                <span v-for="tag in route.tags || []" :key="tag" class="route-tag">{{ tagLabel(tag) }}</span>
              </span>
            </span>
            <span>
              <em>{{ route.quality_score ?? Math.round(route.score) }}</em>
              <small class="quality-tier">{{ tierLabel(route.quality_tier) }}</small>
              <small>难度 {{ route.difficulty_score ?? '-' }}</small>
              <small>{{ route.repeats }} 次重复</small>
            </span>
          </button>
          <el-pagination
            v-if="standardBoard.total > standardBoard.filters.limit"
            class="route-pagination"
            background
            layout="prev, pager, next"
            :page-size="standardBoard.filters.limit"
            :total="standardBoard.total"
            :current-page="Math.floor(standardBoard.filters.offset / standardBoard.filters.limit) + 1"
            @current-change="changeStandardPage"
          />
        </section>

        <section class="standard-preview-column">
          <div class="standard-preview-canvas">
            <BoardCanvas
              :columns="standardBoardColumns"
              :rows="standardBoardRows"
              :base-holds="standardBoard.selected?.board_setup || []"
              :route-overlay="standardBoard.selected?.route_overlay || standardBoard.selected?.virtual_led || []"
              :holds="standardBoard.selected?.board_asset?.placed_holds || []"
              :route-steps="standardBoard.selected?.board_asset?.beta_sequence || []"
              :selected-hold="null"
              :board-spec="standardBoardSpec"
              :frame-style="standardBoardFrameStyle"
              :get-coord-style="getStandardBoardCoordStyle"
              :resolve-hold-visual="library.resolveHoldVisual"
              @place="() => {}"
              @select="() => {}"
            />
          </div>

          <section class="section-block standard-detail-panel">
            <template v-if="standardBoard.selected">
              <div class="section-heading">
                <div>
                  <p class="eyebrow">当前线路</p>
                  <h3>{{ standardBoard.selected.display_name }}</h3>
                  <p class="route-source-line">
                    {{ standardBoard.selected.setter_name }} · MoonBoard 原始等级 {{ standardBoard.selected.grade }}
                  </p>
                </div>
                <div class="command-row">
                  <el-button :type="standardBoard.activity?.favorite ? 'warning' : 'default'" plain @click="toggleStandardFavorite">
                    {{ standardBoard.activity?.favorite ? '取消收藏' : '收藏' }}
                  </el-button>
                  <el-button v-if="simulationEnabled" plain @click="openSelectedRouteSimulation">仿真审核</el-button>
                  <el-button type="primary" plain @click="loadStandardIntoStudio">载入定线工作台</el-button>
                </div>
              </div>
              <div class="standard-stats">
                <span>原始 {{ standardBoard.selected.grade }}</span>
                <span>模型复核 {{ standardBoard.selected.predicted_grade || '-' }}</span>
                <span>{{ confidenceLabel(standardBoard.selected.confidence_tier) }}</span>
                <span>{{ calibrationLabel(standardBoard.selected.calibration_status) }}</span>
                <span>难度 {{ standardBoard.selected.difficulty_score ?? '-' }}</span>
                <span>{{ gradeWarningLabel(standardBoard.selected) }}</span>
                <span>{{ standardBoard.selected.quality_score ?? 0 }} 分</span>
                <span>{{ tierLabel(standardBoard.selected.quality_tier) }}</span>
                <span>{{ standardBoard.selected.features.x_span }} 列跨度</span>
                <span>{{ standardBoard.selected.features.y_span }} 行高度</span>
                <span>{{ standardBoard.selected.validation?.valid_for_climb ? '可攀路线' : '需复核' }}</span>
              </div>
              <a
                v-if="standardBoard.selected.source_url"
                class="source-link"
                :href="standardBoard.selected.source_url"
                target="_blank"
                rel="noreferrer"
              >
                查看原始线路来源
              </a>
              <div class="route-tag-list" aria-label="路线标签">
                <span v-for="tag in standardBoard.selected.tags || []" :key="tag" class="route-tag">{{ tagLabel(tag) }}</span>
              </div>
              <div class="score-breakdown">
                <span v-for="item in scoreBreakdownItems(standardBoard.selected.score_breakdown)" :key="item.key">
                  {{ item.label }} {{ item.value }}
                </span>
              </div>
              <section class="difficulty-panel">
                <div class="section-heading">
                  <div>
                    <p class="eyebrow">难度说明</p>
                    <h3>难度评估</h3>
                  </div>
                  <span class="state-badge">可信度 {{ percentLabel(standardBoard.selected.difficulty_confidence) }}</span>
                </div>
                <div class="score-breakdown">
                  <span v-for="item in difficultyBreakdownItems(standardBoard.selected.difficulty_breakdown)" :key="item.key">
                    {{ item.label }} {{ item.value }}
                  </span>
                </div>
                <div class="review-reasons">
                  <span v-for="reason in standardBoard.selected.difficulty_reasons || []" :key="reason">{{ reason }}</span>
                </div>
              </section>
              <div class="marker-legend">
                <span>手起点 {{ standardBoard.selected.marker_summary?.counts?.start_hands || 0 }}</span>
                <span>脚起点 {{ standardBoard.selected.marker_summary?.counts?.start_feet || 0 }}</span>
                <span>中间点 {{ standardBoard.selected.features.mid_count }}</span>
                <span>终点 {{ standardBoard.selected.features.end_count }}</span>
              </div>
              <div v-if="standardBoard.selected.review_reasons?.length" class="review-reasons">
                <span v-for="reason in standardBoard.selected.review_reasons" :key="reason">{{ reason }}</span>
              </div>
              <section class="standard-activity-panel">
                <div class="section-heading">
                  <div>
                    <p class="eyebrow">训练记录</p>
                    <h3>我的训练记录</h3>
                  </div>
                  <span class="state-badge">{{ standardBoard.activity?.stats?.attempts_total || 0 }} 次尝试</span>
                </div>
                <div class="standard-stats">
                  <span>完成 {{ standardBoard.activity?.stats?.sends_total || 0 }}</span>
                  <span>Flash {{ standardBoard.activity?.stats?.flashes_total || 0 }}</span>
                  <span>最近 {{ resultLabel(standardBoard.activity?.stats?.last_result) }}</span>
                </div>
                <div class="activity-form">
                  <span>我的评分</span>
                  <el-rate :model-value="standardBoard.activity?.rating || 0" @change="rateStandardRoute" />
                  <el-select v-model="standardBoard.activityForm.result" placeholder="结果">
                    <el-option label="Flash" value="flash" />
                    <el-option label="完成" value="send" />
                    <el-option label="尝试" value="attempt" />
                    <el-option label="失败" value="fail" />
                  </el-select>
                  <el-input-number v-model="standardBoard.activityForm.attempts" :min="1" :max="999" />
                  <el-select v-model="standardBoard.activityForm.perceived_grade" clearable placeholder="体感难度">
                    <el-option v-for="grade in standardBoard.difficulties" :key="grade" :label="grade" :value="grade" />
                  </el-select>
                  <el-input v-model="standardBoard.activityForm.notes" placeholder="备注" />
                  <el-button type="primary" :loading="standardBoard.activityLoading" @click="submitStandardAscentLog">记录</el-button>
                </div>
                <div class="activity-log-list">
                  <span v-for="log in standardBoard.activity?.logs || []" :key="log.id">
                    {{ resultLabel(log.result) }} / {{ log.attempts }} 次 / {{ log.perceived_grade || '未填难度' }}
                  </span>
                </div>
              </section>
              <div class="virtual-led-list">
                <span v-for="point in standardBoard.selected.route_overlay || standardBoard.selected.virtual_led" :key="point.coord_id">
                  {{ point.coord_id }} {{ markerLabel(point.role) }} -> LED {{ point.led_index }}
                </span>
              </div>
            </template>
            <div v-else class="empty-state">
              <strong>选择一条线路</strong>
              <span>系统只在网页画布中标记线路坐标，不连接任何真实控制器。</span>
            </div>
          </section>
        </section>
      </div>

      <div v-else class="standard-board-layout">
        <section class="section-block route-list-panel">
          <div class="section-heading">
            <div>
              <p class="eyebrow">修复队列</p>
              <h3>{{ standardBoard.repairTotal }} 条待修复线路</h3>
            </div>
            <span class="state-badge">候选修复</span>
          </div>
          <div class="command-row repair-actions">
            <el-checkbox
              :model-value="allVisibleRepairedSelected"
              :indeterminate="someVisibleRepairedSelected"
              :disabled="!visibleRepairedIds.length"
              @change="toggleVisibleRepairSelection"
            >
              全选已修复
            </el-checkbox>
            <el-button
              type="primary"
              plain
              :disabled="!standardBoard.selectedRepairIds.length"
              :loading="standardBoard.repairPublishing"
              @click="publishSelectedRepairs"
            >
              放入线路库
            </el-button>
          </div>
          <el-skeleton v-if="standardBoard.repairLoading" :rows="8" animated />
          <div v-else-if="!standardBoard.repairs.length" class="empty-state">
            <strong>暂无待修复候选</strong>
            <span>切换状态或刷新队列后再试。</span>
          </div>
          <button
            v-for="repair in standardBoard.repairs"
            v-show="!standardBoard.repairLoading"
            :key="repair.source_id"
            class="standard-route-row"
            :class="{ active: standardBoard.selectedRepair?.source_id === repair.source_id }"
            @click="loadRepairRoute(repair.source_id)"
          >
            <el-checkbox
              :model-value="isRepairSelected(repair.source_id)"
              :disabled="repair.repair_status !== 'repaired'"
              @click.stop
              @change="toggleRepairSelection(repair.source_id, $event)"
            />
            <span>
              <strong>{{ repair.source_name || `标准线路 ${repair.source_id}` }}</strong>
              <small>{{ repair.setter_name }} · MoonBoard 原始等级 {{ repair.original_grade }}</small>
              <small>{{ repair.review_reasons?.join(' / ') || repairStatusLabel(repair.repair_status) }}</small>
            </span>
            <span>
              <em>{{ repair.quality_score ?? '-' }}</em>
              <small class="quality-tier">{{ repairStatusLabel(repair.repair_status) }}</small>
              <small>难度 {{ repair.difficulty_score ?? '-' }}</small>
            </span>
          </button>
          <el-pagination
            v-if="standardBoard.repairTotal > standardBoard.repairFilters.limit"
            class="route-pagination"
            background
            layout="prev, pager, next"
            :page-size="standardBoard.repairFilters.limit"
            :total="standardBoard.repairTotal"
            :current-page="Math.floor(standardBoard.repairFilters.offset / standardBoard.repairFilters.limit) + 1"
            @current-change="changeRepairPage"
          />
        </section>

        <section v-if="standardBoard.repairLoading" class="section-block standard-preview-column repair-preview-column">
          <el-skeleton :rows="12" animated />
        </section>
        <section v-else-if="standardBoard.repairs.length" class="standard-preview-column repair-preview-column">
          <div class="repair-comparison-grid">
            <article class="repair-preview-panel">
              <div class="preview-panel-heading">
                <span>修复前</span>
                <small>{{ standardBoard.repairComparison?.original?.predicted_grade || '-' }}</small>
              </div>
              <div class="standard-preview-canvas">
                <BoardCanvas
                  :columns="standardBoardColumns"
                  :rows="standardBoardRows"
                  :base-holds="standardBoard.repairComparison?.original?.board_setup || []"
                  :route-overlay="standardBoard.repairComparison?.original?.route_overlay || standardBoard.repairComparison?.original?.virtual_led || []"
                  :holds="standardBoard.repairComparison?.original?.board_asset?.placed_holds || []"
                  :route-steps="standardBoard.repairComparison?.original?.board_asset?.beta_sequence || []"
                  :selected-hold="null"
                  :board-spec="standardBoardSpec"
                  :frame-style="standardBoardFrameStyle"
                  :get-coord-style="getStandardBoardCoordStyle"
                  :resolve-hold-visual="library.resolveHoldVisual"
                  @place="() => {}"
                  @select="() => {}"
                />
              </div>
            </article>
            <article class="repair-preview-panel">
              <div class="preview-panel-heading">
                <span>修复后</span>
                <small>{{ standardBoard.repairComparison?.repaired?.predicted_grade || '-' }}</small>
              </div>
              <div v-if="standardBoard.repairComparison?.repaired" class="standard-preview-canvas">
                <BoardCanvas
                  :columns="standardBoardColumns"
                  :rows="standardBoardRows"
                  :base-holds="standardBoard.repairComparison.repaired.board_setup || []"
                  :route-overlay="standardBoard.repairComparison.repaired.route_overlay || standardBoard.repairComparison.repaired.virtual_led || []"
                  :holds="standardBoard.repairComparison.repaired.board_asset?.placed_holds || []"
                  :route-steps="standardBoard.repairComparison.repaired.board_asset?.beta_sequence || []"
                  :selected-hold="null"
                  :board-spec="standardBoardSpec"
                  :frame-style="standardBoardFrameStyle"
                  :get-coord-style="getStandardBoardCoordStyle"
                  :resolve-hold-visual="library.resolveHoldVisual"
                  @place="() => {}"
                  @select="() => {}"
                />
              </div>
              <div v-else class="repair-empty-panel">
                <strong>暂无自动修复结果</strong>
                <span>这条路线可尝试人工处理，但当前自动修复没有通过校验。</span>
                <span v-for="reason in standardBoard.selectedRepair?.review_reasons || []" :key="reason">{{ reason }}</span>
              </div>
            </article>
          </div>
          <section class="section-block standard-detail-panel">
            <template v-if="standardBoard.selectedRepair">
              <div class="section-heading">
                <div>
                  <p class="eyebrow">修复候选</p>
                  <h3>{{ standardBoard.selectedRepair.source_name || `标准线路 ${standardBoard.selectedRepair.source_id}` }}</h3>
                </div>
                <div class="command-row">
                  <el-button :disabled="standardBoard.selectedRepair.repair_status !== 'repaired'" @click="previewRepairRoute(standardBoard.selectedRepair.source_id)">预览修复</el-button>
                  <el-button type="primary" plain :disabled="!standardBoard.repairPreview?.board_asset" @click="loadRepairIntoStudio">载入定线工作台</el-button>
                </div>
              </div>
              <div class="standard-stats">
                <span>{{ repairStatusLabel(standardBoard.selectedRepair.repair_status) }}</span>
                <span>补手点 {{ standardBoard.selectedRepair.added_start_hands?.join(', ') || '无' }}</span>
                <span>派生脚点 {{ standardBoard.selectedRepair.derived_start_feet?.join(', ') || '无' }}</span>
                <span>评分 {{ standardBoard.selectedRepair.quality_score ?? '-' }}</span>
                <span>预测 {{ standardBoard.selectedRepair.predicted_grade || '-' }}</span>
                <span>难度 {{ standardBoard.selectedRepair.difficulty_score ?? '-' }}</span>
                <span>{{ gradeWarningLabel(standardBoard.selectedRepair) }}</span>
              </div>
              <div v-if="standardBoard.repairComparison?.repaired" class="score-breakdown">
                <span v-for="item in difficultyBreakdownItems(standardBoard.repairComparison.repaired.difficulty_breakdown)" :key="item.key">
                  {{ item.label }} {{ item.value }}
                </span>
              </div>
              <div v-if="standardBoard.repairComparison?.repaired?.difficulty_reasons?.length" class="review-reasons">
                <span v-for="reason in standardBoard.repairComparison.repaired.difficulty_reasons" :key="reason">{{ reason }}</span>
              </div>
              <div class="review-reasons">
                <span v-for="reason in standardBoard.selectedRepair.review_reasons || []" :key="reason">{{ reason }}</span>
              </div>
            </template>
            <div v-else class="empty-state">
              <strong>选择一条待修复线路</strong>
              <span>系统只会生成修复候选，不会覆盖原始数据。</span>
            </div>
          </section>
        </section>
        <section v-else class="section-block empty-state">
          <strong>当前筛选下没有修复候选</strong>
          <span>原始线路不会被修改；可以切换修复状态或稍后重新生成审核队列。</span>
        </section>
      </div>
    </section>

    <SimulationLab
      v-else-if="simulationEnabled && activePage === 'simulation'"
      :initial-source-id="simulationSourceId"
      :resolve-hold-visual="library.resolveHoldVisual"
      @load-candidate="loadSimulationCandidate"
    />

    <section v-else class="page ai-page">
      <div class="lab-panel">
        <div class="lab-heading">
          <div>
            <p class="eyebrow">规则辅助实验</p>
            <h2>实验任务</h2>
          </div>
          <el-button :icon="Refresh" :loading="boards.loading" @click="boards.fetchMyBoards">刷新岩板</el-button>
        </div>
        <div class="ai-lab-scope" role="note" aria-label="AI 实验室功能定位">
          <strong>辅助定线，不替代试爬</strong>
          <span>用于讨论候选、发现明显结构问题、生成不覆盖原线路的草案，并保留可复核的评分和规则证据。</span>
        </div>
        <section class="ai-board-picker">
          <div class="panel-heading">
            <div>
              <h3>选择岩板资产</h3>
              <span>AI 实验室会基于这里选中的岩板执行任务。</span>
            </div>
            <el-button v-if="selectedAiBoard" plain @click="loadSelectedAiBoardIntoStudio">载入定线工作台</el-button>
          </div>
          <template v-if="aiAvailableBoards.length">
            <el-select v-model="aiExperiment.selectedBoardId" placeholder="选择岩板资产">
              <el-option
                v-for="board in aiAvailableBoards"
                :key="board.saved_id || board.route_name"
                :label="board.route_name || '未命名岩板'"
                :value="board.saved_id"
              />
            </el-select>
            <div class="ai-board-list">
              <button
                v-for="board in aiAvailableBoards"
                :key="board.saved_id || board.route_name"
                type="button"
                class="ai-board-option"
                :class="{ active: selectedAiBoard?.saved_id === board.saved_id }"
                @click="selectAiBoard(board)"
              >
                <strong>{{ board.route_name || '未命名岩板' }}</strong>
                <span>{{ boardSpecDisplayLabel(board) }} / {{ board.placed_holds?.length || 0 }} 岩点 / {{ board.beta_sequence?.length || 0 }} Beta</span>
                <span>{{ workflowLabel(board) }}{{ board.ai_eligible ? ' / AI 可用' : ' / 布局初审' }}</span>
              </button>
            </div>
          </template>
          <div v-else class="empty-state">
            <strong>{{ aiExperiment.mode === 'compose_route' ? '没有可用于 AI 组合的完整线路' : '没有可用于布局初审的 11×18 岩板' }}</strong>
            <span>{{ aiExperiment.mode === 'compose_route' ? '先在定线工作台按提示补全 Beta 和起终点，再保存线路。' : '先保存一块 11×18 岩板。' }}</span>
            <div class="command-row">
              <el-button type="primary" plain @click="activePage = 'boards'">查看岩板资产</el-button>
              <el-button @click="activePage = 'studio'">进入定线工作台</el-button>
            </div>
          </div>
          <div v-if="selectedAiBoard" class="selected-board-summary">
            <strong>{{ selectedAiBoard.route_name || '未命名岩板' }}</strong>
            <span>{{ selectedAiBoardStats.spec }}</span>
            <span>{{ selectedAiBoardStats.holds }} 岩点</span>
            <span>{{ selectedAiBoardStats.beta }} Beta</span>
            <span>{{ selectedAiBoardStats.difficulty }}</span>
            <span>{{ workflowLabel(selectedAiBoard) }}</span>
          </div>
          <el-alert
            v-if="aiBoardBlockingMessage"
            type="warning"
            :closable="false"
            :title="aiBoardBlockingMessage"
            show-icon
          />
          <el-alert
            v-else-if="aiBoardWarnings.length"
            type="info"
            :closable="false"
            title="提交前提示"
            :description="aiBoardWarnings.join(' ')"
            show-icon
          />
        </section>
        <div class="experiment-controls">
          <el-segmented
            v-model="aiExperiment.mode"
            :options="[
              { label: '重新组合路线', value: 'compose_route' },
              { label: '提出修改建议', value: 'review_route' },
            ]"
          />
          <el-select
            v-if="aiExperiment.mode === 'compose_route'"
            v-model="aiExperiment.generation_goal"
            aria-label="AI 组合目标"
            placeholder="选择组合目标"
          >
            <el-option label="质量优先" value="quality_first" />
            <el-option label="目标难度优先" value="grade_match" />
            <el-option label="动作风格多样" value="style_variation" />
          </el-select>
          <el-select
            v-else
            v-model="aiExperiment.review_focus"
            aria-label="AI 审核重点"
            placeholder="选择审核重点"
          >
            <el-option label="综合检查" value="overall" />
            <el-option label="脚点检查" value="footholds" />
            <el-option label="难度检查" value="difficulty" />
            <el-option label="动作顺序检查" value="beta_sequence" />
          </el-select>
          <p class="control-help">
            {{ aiExperiment.mode === 'compose_route'
              ? '只有通过完整静态人体工学门禁的岩板才会返回；无合格路径时建议保留原线路。'
              : '所选重点会改变专项检查；自动修复岩板同样必须通过完整静态门禁。' }}
          </p>
        </div>
        <div class="command-row">
          <el-button type="primary" :disabled="!canRunAiExperiment" :loading="routeGen.loading" @click="runAiExperiment">提交所选岩板</el-button>
          <el-button v-if="routeGen.loading" @click="routeGen.cancelGeneration">取消任务</el-button>
          <el-button @click="activePage = 'studio'">返回定线工作台</el-button>
        </div>
        <el-alert
          v-if="routeGen.taskId"
          type="info"
          :closable="false"
          :title="`任务 ${routeGen.taskId} · ${aiTaskStatusLabel(routeGen.status)} · ${routeGen.elapsedSeconds} 秒`"
        />
        <el-alert v-if="routeGen.error" type="error" :closable="false" :title="routeGen.error" />
        <section v-if="routeGen.result" class="experiment-result">
          <header class="experiment-verdict">
            <div>
              <span>{{ routeGen.result.mode === 'review_route' ? '定线建议' : '重组建议' }}</span>
              <strong>{{ routeGen.result.recommendation?.title || routeGen.result.review_summary || routeGen.result.analysis_summary }}</strong>
              <p>{{ routeGen.result.recommendation?.summary || routeGen.result.review_summary }}</p>
            </div>
            <span
              v-if="routeGen.result.risk_level"
              :class="['verdict-risk', `is-${routeGen.result.metrics?.risk_assessment_status === 'partial' ? 'partial' : routeGen.result.risk_level}`]"
            >
              {{ riskAssessmentLabel(routeGen.result) }}
            </span>
          </header>

          <template v-if="routeGen.result.mode === 'compose_route'">
            <el-alert
              v-if="routeGen.result.failure_suggestion"
              type="warning"
              :closable="false"
              :title="routeGen.result.failure_suggestion"
              show-icon
            />
            <div v-if="routeGen.result.selected_routes?.[0]" class="ai-primary-board">
              <BoardComparisonPanel
                :board="routeGen.result.selected_routes[0]"
                label="最佳新岩板"
                loadable
                :show-beta="false"
                :show-movement-count="false"
                :show-details="false"
                :resolve-hold-visual="library.resolveHoldVisual"
                @load="loadAiCandidateIntoStudio(routeGen.result.selected_routes[0])"
              />
            </div>
          </template>

          <template v-else>
            <article v-for="violation in routeGen.result.violations" :key="violation.code" class="result-card result-card-critical">
              <span>必须处理</span>
              <strong>{{ violation.message }}</strong>
              <small v-if="violation.hold_ids?.length">相关岩点：{{ violation.hold_ids.join('、') }}</small>
            </article>
            <article v-for="suggestion in routeGen.result.suggestions" :key="suggestion.title" class="result-card">
              <span>{{ suggestionGroupLabel(suggestion) }}</span>
              <strong>{{ suggestion.title }}</strong>
              <p>{{ suggestion.detail }}</p>
            </article>
            <div v-if="reviewRepairCandidate" class="ai-primary-board">
              <BoardComparisonPanel
                :board="reviewRepairCandidate"
                label="通过门禁的修复岩板"
                loadable
                :show-beta="false"
                :show-movement-count="false"
                :show-details="false"
                :resolve-hold-visual="library.resolveHoldVisual"
                @load="loadAiCandidateIntoStudio(reviewRepairCandidate)"
              />
            </div>
          </template>

          <el-collapse class="ai-analysis-collapse">
            <el-collapse-item title="查看分析依据" name="analysis">
              <div class="result-context">
                <span>分析岩板：{{ selectedAiBoard?.route_name || '所选岩板' }}</span>
                <span>{{ selectedAiBoardStats.holds }} 岩点 / {{ selectedAiBoardStats.difficulty }}</span>
                <span>{{ routeGen.result.llm_enriched ? 'AI 已用中文润色' : '本地中文结果' }}</span>
              </div>
              <div class="result-metrics">
                <span v-if="routeGen.result.metrics?.target_grade">目标 {{ routeGen.result.metrics.target_grade }}</span>
                <span v-if="routeGen.result.metrics?.quality_score !== undefined">结构质量 {{ routeGen.result.metrics.quality_score }}</span>
                <span v-if="routeGen.result.metrics?.predicted_grade">MoonBoard 等效难度 {{ routeGen.result.metrics.predicted_grade }}</span>
                <span v-if="routeGen.result.metrics?.risk_score !== undefined">{{ riskMetricLabel(routeGen.result.metrics) }}</span>
                <span v-if="routeGen.result.risk_level">等级 {{ riskLevelLabel(routeGen.result.risk_level) }}</span>
                <span v-if="routeGen.result.metrics?.review_scope">{{ reviewScopeLabel(routeGen.result.metrics.review_scope) }}</span>
              </div>
              <div v-if="routeGen.result.applied_constraints?.length" class="result-metrics">
                <span v-for="constraint in routeGen.result.applied_constraints" :key="constraint">{{ constraint }}</span>
              </div>

              <div v-if="routeGen.result.mode === 'compose_route' && aiComparisonReference" class="ai-comparison-grid count-2">
                <BoardComparisonPanel
                  :board="aiComparisonReference"
                  label="原岩板"
                  baseline
                  :show-beta="false"
                  :show-movement-count="false"
                  :resolve-hold-visual="library.resolveHoldVisual"
                />
                <BoardComparisonPanel
                  v-if="routeGen.result.selected_routes?.[0]"
                  :board="routeGen.result.selected_routes[0]"
                  :reference="aiComparisonReference"
                  :label="candidateMeta(0).label_text || '最佳新岩板'"
                  :meta="candidateMeta(0)"
                  :show-beta="false"
                  :show-movement-count="false"
                  :resolve-hold-visual="library.resolveHoldVisual"
                />
              </div>

              <template v-if="routeGen.result.mode === 'review_route'">
                <div v-if="routeGen.result.board" class="review-board-preview">
                  <BoardComparisonPanel
                    :board="routeGen.result.board"
                    label="审核对象"
                    baseline
                    :show-movement-count="false"
                    :resolve-hold-visual="library.resolveHoldVisual"
                  />
                </div>
                <article v-for="suggestion in routeGen.result.suggestions" :key="`evidence-${suggestion.title}`" class="result-card">
                  <strong>{{ suggestion.title }}</strong>
                  <dl class="suggestion-evidence">
                    <div><dt>本次观测</dt><dd>{{ suggestion.observed || '暂无量化观测' }}</dd></div>
                    <div><dt>判定阈值</dt><dd>{{ suggestion.threshold || '未设置阈值' }}</dd></div>
                    <div><dt>预计改善</dt><dd>{{ suggestion.expected_effect || '需要定线者复核' }}</dd></div>
                  </dl>
                  <div class="suggestion-locators">
                    <span v-if="suggestion.hold_ids?.length">相关岩点：{{ suggestion.hold_ids.join('、') }}</span>
                    <span v-if="suggestion.beta_steps?.length">原线路 Beta 步骤：{{ suggestion.beta_steps.join('、') }}</span>
                    <span>证据{{ evidenceStatusLabel(suggestion.evidence_status) }} · {{ confidenceLabel(suggestion.confidence) }}</span>
                  </div>
                </article>
              </template>

              <AIExperimentExplanation
                v-if="routeGen.result.explanation"
                :explanation="routeGen.result.explanation"
              />
              <div v-if="routeGen.result.algorithm_notes?.length" class="result-metrics">
                <span v-for="note in routeGen.result.algorithm_notes" :key="note">{{ note }}</span>
              </div>
            </el-collapse-item>
          </el-collapse>
        </section>
      </div>
    </section>
  </AppShell>
</template>

<script setup>
import { computed, defineAsyncComponent, defineComponent, h, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { Collection, Delete, DocumentChecked, Edit, EditPen, Grid, Histogram, Plus, Refresh, Search, Upload } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import AIExperimentExplanation from './components/AIExperimentExplanation.vue'
import AppShell from './components/AppShell.vue'
import BoardCanvas from './components/BoardCanvas.vue'
import BoardComparisonPanel from './components/BoardComparisonPanel.vue'
import InspectorPanel from './components/InspectorPanel.vue'
import { useBoardPersistence } from './composables/useBoardPersistence'
import { useHoldLibrary } from './composables/useHoldLibrary'
import { useRouteGeneration } from './composables/useRouteGeneration'
import { useStudioEditor } from './composables/useStudioEditor'
import { DEFAULT_FONT_GRADE, FONT_GRADES, UNGRADED, calibrationLabel, confidenceLabel } from './constants/gradeSystem'
import { ROUTE_TAG_GROUPS, boardSystemTags, boardTags, matchesTags, tagLabel } from './constants/routeTags'
import standardBoardService from './services/standardBoardService'

const activePage = ref('dashboard')
const simulationEnabled = import.meta.env.VITE_ENABLE_SIMULATION === 'true'
const SimulationLab = simulationEnabled
  ? defineAsyncComponent(() => import('./components/SimulationLab.vue'))
  : null
const library = reactive(useHoldLibrary())
const boards = reactive(useBoardPersistence())
const studio = reactive(useStudioEditor())
const routeGen = reactive(useRouteGeneration())
const selectedDashboardTemplateId = ref(studio.activeBoardPresetId)
const aiExperiment = reactive({
  mode: 'compose_route',
  generation_goal: 'quality_first',
  review_focus: 'overall',
  selectedBoardId: '',
})
const simulationSourceId = ref('')
const boardAssetMode = ref('list')
const savedBoardView = ref('active')
const compareBoardIds = ref([])
const savedBoardFilters = reactive({ tagIds: [], match: 'all' })
const standardBoardColumns = Array.from({ length: 11 }, (_, index) => String.fromCharCode(65 + index))
const standardBoardRows = Array.from({ length: 18 }, (_, index) => index + 1)
const standardBoardSpec = {
  preset_id: 'classic-11x18',
  template_key: 'spray-small',
  label: '11×18 标准训练板',
  name: '11×18 标准训练板',
  columns: 11,
  cols: 11,
  rows: 18,
  hole_spacing_x_mm: 200,
  hole_spacing_y_mm: 200,
  board_width_mm: 2440,
  board_height_mm: 3660,
  grid_width_mm: 2000,
  grid_height_mm: 3400,
  margin_left_mm: 220,
  margin_right_mm: 220,
  margin_bottom_mm: 130,
  margin_top_mm: 130,
  angle_degrees: 40,
  total_holes: 198,
  unit: 'mm',
  reference_system: 'standard-board-derived',
  cellLabel: '11 x 18',
  physicalLabel: '2440 x 3660 mm',
  spacingLabel: '200 x 200 mm',
  angleLabel: '40°',
  material: null,
  skinClass: null,
}
const standardBoard = reactive({
  mode: 'routes',
  loading: false,
  generating: false,
  activityLoading: false,
  repairLoading: false,
  repairPublishing: false,
  error: '',
  routes: [],
  repairs: [],
  selected: null,
  selectedRepair: null,
  repairPreview: null,
  repairComparison: null,
  selectedRepairIds: [],
  activity: null,
  generatedMeta: null,
  total: 0,
  repairTotal: 0,
  difficulties: FONT_GRADES,
  filters: {
    q: '',
    difficulty: DEFAULT_FONT_GRADE,
    predicted_grade: '',
    grade_warning: '',
    benchmark_only: false,
    tag_ids: [],
    tag_match: 'all',
    sort: 'score_desc',
    limit: 24,
    offset: 0,
  },
  repairFilters: {
    q: '',
    status: '',
    limit: 24,
    offset: 0,
  },
  activityForm: {
    result: 'attempt',
    attempts: 1,
    perceived_grade: '',
    notes: '',
  },
})

const pageTitle = computed(() => ({
  dashboard: '总览',
  studio: '定线工作台',
  library: '岩点库',
  boards: '岩板资产',
  'standard-board': '标准板库',
  simulation: '仿真审核',
  'ai-lab': 'AI 实验室',
}[activePage.value] || '攀岩定线辅助系统'))

const selectedDashboardTemplate = computed(() => (
  studio.boardPresets.find((template) => template.id === selectedDashboardTemplateId.value) || studio.boardPresets[0]
))

const aiAvailableBoards = computed(() => boards.savedBoards.filter((board) => {
  const columns = Number(board.board_spec?.columns || board.board_spec?.cols || 11)
  const rows = Number(board.board_spec?.rows || 18)
  if (columns !== 11 || rows !== 18) return false
  return aiExperiment.mode === 'review_route' || board.ai_eligible
}))

const selectedAiBoard = computed(() => {
  if (!aiAvailableBoards.value.length) return null
  return aiAvailableBoards.value.find((board) => board.saved_id === aiExperiment.selectedBoardId) || aiAvailableBoards.value[0]
})

const selectedAiBoardStats = computed(() => {
  const board = selectedAiBoard.value
  return {
    holds: board?.placed_holds?.length || 0,
    beta: board?.beta_sequence?.length || 0,
    difficulty: board?.difficulty || UNGRADED,
    spec: boardSpecDisplayLabel(board),
  }
})

const aiBoardWarnings = computed(() => {
  const board = selectedAiBoard.value
  if (!board) return ['请先从岩板资产中选择一块岩板。']

  return board.readiness_warnings || []
})

const aiBoardBlockingMessage = computed(() => {
  const board = selectedAiBoard.value
  if (!board) return '请先选择一块已保存的岩板。'

  const holds = board.placed_holds || []
  if (!holds.length) return '所选岩板没有岩点，无法提交。'
  const columns = Number(board.board_spec?.columns || board.board_spec?.cols || 11)
  const rows = Number(board.board_spec?.rows || 18)
  const angle = Number(board.board_spec?.angle_degrees || 40)
  if (columns !== 11 || rows !== 18 || angle !== 40) return 'AI 实验目前只支持 11×18、40° 岩板，其他规格可以继续手工编辑。'
  if (aiExperiment.mode === 'compose_route' && !board.ai_eligible) {
    return board.readiness_issues?.[0] || 'AI 组合只接受通过完整性检查的线路。'
  }
  return ''
})

const canRunAiExperiment = computed(() => !routeGen.loading && !aiBoardBlockingMessage.value)

const visibleRepairedIds = computed(() => standardBoard.repairs
  .filter((repair) => repair.repair_status === 'repaired')
  .map((repair) => repair.source_id))

const allVisibleRepairedSelected = computed(() => (
  visibleRepairedIds.value.length > 0
  && visibleRepairedIds.value.every((sourceId) => standardBoard.selectedRepairIds.includes(sourceId))
))

const standardRouteTagGroups = computed(() => ROUTE_TAG_GROUPS.filter((group) => group.key !== 'source'))
const savedBoardTagGroups = computed(() => {
  const known = ROUTE_TAG_GROUPS.map((group) => ({ ...group, tags: [...group.tags] }))
  const knownIds = new Set(known.flatMap((group) => group.tags.map((tag) => tag.id)))
  const legacyTags = [...new Set(boards.savedBoards.flatMap((board) => board.tags || []))]
    .filter((tag) => !knownIds.has(tag))
    .map((id) => ({ id, label: tagLabel(id) }))
  if (legacyTags.length) known.push({ key: 'legacy', label: '已有标签', tags: legacyTags })
  return known
})
const visibleSavedBoards = computed(() => savedBoardView.value === 'archived' ? boards.archivedBoards : boards.savedBoards)
const filteredSavedBoards = computed(() => visibleSavedBoards.value.filter((board) => (
  matchesTags(boardTags(board), savedBoardFilters.tagIds, savedBoardFilters.match)
)))
const comparedBoards = computed(() => compareBoardIds.value
  .map((savedId) => boards.savedBoards.find((board) => board.saved_id === savedId))
  .filter(Boolean))
const aiComparisonReference = computed(() => routeGen.result?.board || selectedAiBoard.value)
const reviewRepairCandidate = computed(() => (
  routeGen.result?.suggestions?.find((suggestion) => suggestion.candidate_route)?.candidate_route || null
))

const someVisibleRepairedSelected = computed(() => (
  visibleRepairedIds.value.some((sourceId) => standardBoard.selectedRepairIds.includes(sourceId))
  && !allVisibleRepairedSelected.value
))

const standardBoardFrameStyle = computed(() => ({
  '--board-ratio': `${standardBoardSpec.board_width_mm} / ${standardBoardSpec.board_height_mm}`,
  '--board-columns': standardBoardSpec.columns,
  '--board-rows': standardBoardSpec.rows,
  '--grid-left': `${(standardBoardSpec.margin_left_mm / standardBoardSpec.board_width_mm) * 100}%`,
  '--grid-right': `${(standardBoardSpec.margin_right_mm / standardBoardSpec.board_width_mm) * 100}%`,
  '--grid-bottom': `${(standardBoardSpec.margin_bottom_mm / standardBoardSpec.board_height_mm) * 100}%`,
  '--grid-top': `${(standardBoardSpec.margin_top_mm / standardBoardSpec.board_height_mm) * 100}%`,
}))

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

function warnBeforeUnload(event) {
  if (!studio.unsavedChanges) return
  event.preventDefault()
  event.returnValue = ''
}

onMounted(async () => {
  window.addEventListener('beforeunload', warnBeforeUnload)
  await Promise.all([library.fetchAllHoldData(), boards.fetchMyBoards(), fetchStandardRoutes()])
})

onBeforeUnmount(() => {
  window.removeEventListener('beforeunload', warnBeforeUnload)
})

watch(
  [() => boards.savedBoards, () => aiExperiment.mode],
  () => {
    const availableBoards = aiAvailableBoards.value
    if (!availableBoards.length) {
      aiExperiment.selectedBoardId = ''
      return
    }
    if (!availableBoards.some((board) => board.saved_id === aiExperiment.selectedBoardId)) {
      aiExperiment.selectedBoardId = availableBoards[0].saved_id || ''
    }
  },
  { immediate: true }
)

watch(
  () => boards.savedBoards,
  (activeBoards) => {
    const activeIds = new Set(activeBoards.map((board) => board.saved_id))
    compareBoardIds.value = compareBoardIds.value.filter((savedId) => activeIds.has(savedId)).slice(0, 4)
  },
  { deep: true }
)

watch(activePage, () => {
  window.requestAnimationFrame(() => window.scrollTo({ top: 0, left: 0, behavior: 'auto' }))
})

async function changePage(nextPage) {
  if (nextPage === 'simulation' && !simulationEnabled) return
  if (nextPage === activePage.value) return
  if (activePage.value === 'studio' && studio.unsavedChanges) {
    try {
      await ElMessageBox.confirm('当前修改仍会保留在本次工作区，但尚未写入本地岩板库。是否切换页面？', '未保存的草稿', {
        confirmButtonText: '离开并保留草稿',
        cancelButtonText: '继续编辑',
        type: 'warning',
      })
    } catch {
      return
    }
  }
  activePage.value = nextPage
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
  const boardToSave = {
    ...studio.currentBoard,
    tags: [...new Set([...(studio.currentBoard.tags || []), ...boardSystemTags(studio.currentBoard)])],
  }
  const saved = await boards.saveBoard(boardToSave)
  if (!saved) return
  studio.loadBoard({ ...boardToSave, ...saved })
  if (saved.workflow_status === 'draft') {
    ElMessage.warning(`已保存为草稿：${saved.readiness_issues?.[0] || '线路尚未通过完整性检查'}`)
  } else {
    ElMessage.success(saved.ai_eligible ? '线路已保存，可进入 AI 实验' : '线路已保存，可进行人工检查')
  }
}

function resolvedBoardTags(board) {
  return boardTags(board)
}

function boardSpecDisplayLabel(board = {}) {
  const columns = Number(board.board_spec?.columns || board.board_spec?.cols || 11)
  const rows = Number(board.board_spec?.rows || 18)
  return {
    '11x18': '11×18 标准训练板',
    '14x20': '14×20 扩展训练板',
    '16x24': '16×24 大型训练板',
    '18x22': '18×22 宽体训练板',
  }[`${columns}x${rows}`] || `${columns}×${rows} 岩板`
}

function clearSavedBoardTags() {
  savedBoardFilters.tagIds = []
}

function clearBoardComparison() {
  compareBoardIds.value = []
}

function setComparisonBaseline(savedId) {
  compareBoardIds.value = [savedId, ...compareBoardIds.value.filter((id) => id !== savedId)]
}

function removeComparedBoard(savedId) {
  compareBoardIds.value = compareBoardIds.value.filter((id) => id !== savedId)
}

function loadBoardIntoStudio(board) {
  studio.loadBoard(board)
  activePage.value = 'studio'
}

function loadAiCandidateIntoStudio(route) {
  studio.loadBoard(route, { markUnsaved: true })
  activePage.value = 'studio'
  ElMessage.info('候选路线已载入定线工作台；保存后才会写入本地岩板库。')
}

async function renameBoard(board) {
  const renamed = await boards.renameSavedBoard(board)
  if (renamed && studio.currentBoard.saved_id === renamed.saved_id) studio.loadBoard(renamed)
}

async function archiveBoard(board) {
  const archived = await boards.archiveSavedBoard(board)
  if (archived && studio.currentBoard.saved_id === board.saved_id) await studio.newBlankBoard()
}

async function restoreBoard(board) {
  await boards.restoreSavedBoard(board)
}

function workflowLabel(board = {}) {
  if (board.archived_at) return '已归档'
  return board.workflow_status === 'ready_for_review' ? '可检查' : '草稿'
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

function applyStandardFilters() {
  standardBoard.filters.offset = 0
  fetchStandardRoutes()
}

function changeStandardPage(page) {
  standardBoard.filters.offset = (page - 1) * standardBoard.filters.limit
  fetchStandardRoutes()
}

async function loadStandardRoute(sourceId) {
  standardBoard.error = ''
  try {
    const response = await standardBoardService.getRoute(sourceId)
    standardBoard.selected = response.data
    await fetchStandardActivity(sourceId)
  } catch (error) {
    standardBoard.error = error.response?.data?.detail || error.message || '标准板线路详情加载失败'
  }
}

async function fetchStandardActivity(sourceId = standardBoard.selected?.source_id) {
  if (!sourceId) return
  standardBoard.activityLoading = true
  try {
    const response = await standardBoardService.getActivity(sourceId)
    standardBoard.activity = response.data
  } catch (error) {
    standardBoard.activity = {
      favorite: false,
      rating: null,
      logs: [],
      stats: { attempts_total: 0, sends_total: 0, flashes_total: 0, last_result: null },
    }
    standardBoard.error = error.response?.data?.detail || '训练记录暂时不可用'
  } finally {
    standardBoard.activityLoading = false
  }
}

async function toggleStandardFavorite() {
  if (!standardBoard.selected?.source_id) return
  standardBoard.activityLoading = true
  try {
    const response = standardBoard.activity?.favorite
      ? await standardBoardService.unfavoriteRoute(standardBoard.selected.source_id)
      : await standardBoardService.favoriteRoute(standardBoard.selected.source_id)
    standardBoard.activity = response.data
  } catch (error) {
    standardBoard.error = error.response?.data?.detail || error.message || '收藏状态更新失败'
  } finally {
    standardBoard.activityLoading = false
  }
}

async function rateStandardRoute(rating) {
  if (!standardBoard.selected?.source_id || !rating) return
  standardBoard.activityLoading = true
  try {
    const response = await standardBoardService.rateRoute(standardBoard.selected.source_id, rating)
    standardBoard.activity = response.data
  } catch (error) {
    standardBoard.error = error.response?.data?.detail || error.message || '评分保存失败'
  } finally {
    standardBoard.activityLoading = false
  }
}

async function submitStandardAscentLog() {
  if (!standardBoard.selected?.source_id) return
  standardBoard.activityLoading = true
  try {
    const response = await standardBoardService.logAscent(standardBoard.selected.source_id, {
      result: standardBoard.activityForm.result,
      attempts: standardBoard.activityForm.attempts,
      perceived_grade: standardBoard.activityForm.perceived_grade || null,
      notes: standardBoard.activityForm.notes,
    })
    standardBoard.activity = response.data
    standardBoard.activityForm.notes = ''
    standardBoard.activityForm.attempts = 1
    ElMessage.success('训练记录已保存')
  } catch (error) {
    standardBoard.error = error.response?.data?.detail || error.message || '训练记录保存失败'
  } finally {
    standardBoard.activityLoading = false
  }
}

async function fetchRepairRoutes() {
  standardBoard.repairLoading = true
  standardBoard.error = ''
  try {
    const response = await standardBoardService.listRepairs(standardBoard.repairFilters)
    standardBoard.repairs = response.data?.routes || []
    standardBoard.repairTotal = response.data?.total || 0
    const currentIds = new Set(standardBoard.repairs.map((repair) => repair.source_id))
    standardBoard.selectedRepairIds = standardBoard.selectedRepairIds.filter((sourceId) => currentIds.has(sourceId))
    if ((!standardBoard.selectedRepair || !standardBoard.repairs.some((repair) => repair.source_id === standardBoard.selectedRepair?.source_id)) && standardBoard.repairs.length) {
      await loadRepairRoute(standardBoard.repairs[0].source_id)
    }
  } catch (error) {
    standardBoard.error = error.response?.data?.detail || error.message || '待修复路线加载失败'
  } finally {
    standardBoard.repairLoading = false
  }
}

function applyRepairFilters() {
  standardBoard.repairFilters.offset = 0
  fetchRepairRoutes()
}

function changeRepairPage(page) {
  standardBoard.repairFilters.offset = (page - 1) * standardBoard.repairFilters.limit
  fetchRepairRoutes()
}

async function loadRepairRoute(sourceId) {
  standardBoard.error = ''
  try {
    const response = await standardBoardService.compareRepair(sourceId)
    standardBoard.repairComparison = response.data
    standardBoard.selectedRepair = response.data?.candidate || null
    standardBoard.repairPreview = response.data?.repaired || null
  } catch (error) {
    standardBoard.error = error.response?.data?.detail || error.message || '修复候选加载失败'
  }
}

async function previewRepairRoute(sourceId) {
  standardBoard.error = ''
  try {
    const response = await standardBoardService.compareRepair(sourceId)
    standardBoard.repairComparison = response.data
    standardBoard.selectedRepair = response.data?.candidate || standardBoard.selectedRepair
    standardBoard.repairPreview = response.data?.repaired || null
  } catch (error) {
    standardBoard.error = error.response?.data?.detail || error.message || '修复预览加载失败'
  }
}

function loadRepairIntoStudio() {
  const boardAsset = standardBoard.repairComparison?.repaired?.board_asset || standardBoard.repairPreview?.board_asset
  if (!boardAsset) return
  studio.loadBoard(boardAsset, { markUnsaved: true })
  activePage.value = 'studio'
  ElMessage.info('修复副本已载入定线工作台；保存后才会写入本地岩板库。')
}

function isRepairSelected(sourceId) {
  return standardBoard.selectedRepairIds.includes(sourceId)
}

function toggleRepairSelection(sourceId, selected) {
  if (selected) {
    if (!standardBoard.selectedRepairIds.includes(sourceId)) {
      standardBoard.selectedRepairIds.push(sourceId)
    }
    return
  }
  standardBoard.selectedRepairIds = standardBoard.selectedRepairIds.filter((item) => item !== sourceId)
}

function toggleVisibleRepairSelection(selected) {
  if (!selected) {
    standardBoard.selectedRepairIds = standardBoard.selectedRepairIds.filter((sourceId) => !visibleRepairedIds.value.includes(sourceId))
    return
  }
  const selectedSet = new Set(standardBoard.selectedRepairIds)
  visibleRepairedIds.value.forEach((sourceId) => selectedSet.add(sourceId))
  standardBoard.selectedRepairIds = Array.from(selectedSet)
}

async function publishSelectedRepairs() {
  if (!standardBoard.selectedRepairIds.length) return
  standardBoard.repairPublishing = true
  standardBoard.error = ''
  try {
    const response = await standardBoardService.publishRepairs(standardBoard.selectedRepairIds)
    const published = response.data?.published || []
    const skipped = response.data?.skipped || []
    standardBoard.selectedRepairIds = []
    await Promise.all([fetchStandardRoutes(), fetchRepairRoutes()])
    if (published.length) ElMessage.success(`已放入线路库 ${published.length} 条`)
    if (skipped.length) ElMessage.warning(`有 ${skipped.length} 条未发布，请查看状态`)
  } catch (error) {
    standardBoard.error = error.response?.data?.detail || error.message || '修复路线发布失败'
  } finally {
    standardBoard.repairPublishing = false
  }
}

function handleStandardModeChange(mode) {
  if (mode === 'repairs' && !standardBoard.repairs.length) fetchRepairRoutes()
  if (mode === 'routes' && !standardBoard.routes.length) fetchStandardRoutes()
}

function getStandardBoardCoordStyle(coord = 'A1') {
  const [, rawColumn = 'A', rawRow = '1'] = String(coord).match(/^([A-Z]+)(\d+)$/i) || []
  const column = rawColumn.toUpperCase()
  const row = Number(rawRow) || 1
  const xIndex = Math.max(0, standardBoardColumns.indexOf(column))
  const yIndex = Math.max(0, standardBoardRows.indexOf(row))
  const xMm = standardBoardSpec.margin_left_mm + xIndex * standardBoardSpec.hole_spacing_x_mm
  const yMm = standardBoardSpec.margin_bottom_mm + yIndex * standardBoardSpec.hole_spacing_y_mm
  return {
    left: `${(xMm / standardBoardSpec.board_width_mm) * 100}%`,
    bottom: `${(yMm / standardBoardSpec.board_height_mm) * 100}%`,
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
    ElMessage.success('候选线路已生成并加载坐标预览')
  } catch (error) {
    standardBoard.error = error.response?.data?.detail || error.message || '标准板线路生成失败'
  } finally {
    standardBoard.generating = false
  }
}

function loadStandardIntoStudio() {
  if (!standardBoard.selected?.board_asset) return
  studio.loadBoard(standardBoard.selected.board_asset, { markUnsaved: true })
  activePage.value = 'studio'
  ElMessage.info('标准线路副本已载入定线工作台；原始线路不会被覆盖。')
}

function openSelectedRouteSimulation() {
  if (!simulationEnabled) return
  if (!standardBoard.selected?.source_id) return
  simulationSourceId.value = standardBoard.selected.source_id
  activePage.value = 'simulation'
}

function loadSimulationCandidate(board) {
  if (!board) return
  studio.loadBoard(board, { markUnsaved: true })
  activePage.value = 'studio'
  ElMessage.success('修复副本已载入定线工作台，原线路未被覆盖')
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

function resultLabel(result) {
  return {
    flash: 'Flash',
    send: '完成',
    attempt: '尝试',
    fail: '失败',
  }[result] || '无记录'
}

function repairStatusLabel(status) {
  return {
    repairable: '可尝试',
    repaired: '已修复候选',
    unrepairable: '不可修复',
  }[status] || status
}

function gradeWarningLabel(route = {}) {
  if (!route?.grade_warning || route.grade_warning === 'none') return '难度匹配'
  if (route.grade_warning === 'uncertain') return '难度可信度不足'
  const direction = Number(route.grade_delta || 0) > 0 ? '疑似偏硬' : '疑似偏软'
  return route.grade_warning === 'hard' ? `${direction}，需复核` : direction
}

function percentLabel(value) {
  if (value === undefined || value === null) return '-'
  return `${Math.round(Number(value) * 100)}%`
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

function difficultyBreakdownItems(breakdown = {}) {
  const labels = {
    move_distance: '跨度',
    hold_demand: '岩点',
    foot_demand: '脚点',
    body_tension: '张力',
    sequence_complexity: '复杂度',
    start_finish_pressure: '起终压力',
    data_adjustment: '数据修正',
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

function selectAiBoard(board) {
  aiExperiment.selectedBoardId = board.saved_id || ''
}

function loadSelectedAiBoardIntoStudio() {
  if (!selectedAiBoard.value) return
  loadBoardIntoStudio(selectedAiBoard.value)
}

function cloneBoardForAi(board) {
  return JSON.parse(JSON.stringify(board))
}

function suggestionGroupLabel(suggestion) {
  if (suggestion.group === 'must_fix') return '必须修'
  if (suggestion.group === 'should_fix') return '建议修'
  if (suggestion.group === 'optional') return '可选优化'
  const text = `${suggestion.title || ''} ${suggestion.detail || ''}`
  if (text.includes('Beta') || text.includes('动作序列')) return '信息补充'
  if (text.includes('修正') || text.includes('调整') || text.includes('风险')) return '必须修'
  return '建议优化'
}

function reuseQualityLabel(value) {
  return {
    below_pass: '低于通过标准',
    pass: '达到通过标准',
    optimal: '达到最优标准',
  }[value] || '待复核'
}

function riskLevelLabel(level) {
  return {
    low: '低',
    medium: '中',
    high: '高',
  }[level] || level
}

function riskAssessmentLabel(result) {
  if (result?.metrics?.risk_assessment_status === 'partial') return '风险未完整评估'
  return `风险${riskLevelLabel(result?.risk_level)}`
}

function riskMetricLabel(metrics = {}) {
  const scope = metrics.risk_scope
  if (metrics.risk_assessment_status === 'partial') {
    return `结构风险 ${metrics.risk_score} / 动作未完整评估`
  }
  if (scope === 'structure_and_action') return `结构与动作风险 ${metrics.risk_score}`
  if (scope === 'structure_and_difficulty') return `结构与难度风险 ${metrics.risk_score}`
  return `结构风险 ${metrics.risk_score}`
}

function reviewScopeLabel(scope) {
  return {
    full_beta: '已执行完整 Beta 检查',
    layout_and_difficulty: '结构与难度专项检查',
    layout_only: '岩点布局初审',
  }[scope] || scope
}

function evidenceStatusLabel(status) {
  return {
    measured: '已量化',
    estimated: '为模型估算',
    not_measured: '尚未量化',
  }[status] || '待复核'
}

function aiTaskStatusLabel(status) {
  return {
    idle: '尚未提交',
    pending: '等待执行',
    running: '正在计算',
    completed: '已完成',
    failed: '执行失败',
    cancelled: '已取消',
  }[status] || status
}

function candidateMeta(index) {
  return routeGen.result?.candidate_routes?.[index] || {}
}

function runAiExperiment() {
  if (aiBoardBlockingMessage.value) {
    ElMessage.warning(aiBoardBlockingMessage.value)
    return
  }

  const board = cloneBoardForAi(selectedAiBoard.value)
  ElMessage.info(`已提交“${board.route_name || '未命名岩板'}”，AI 实验室将返回可查询任务结果。`)
  routeGen.generateRoute({
    mode: aiExperiment.mode,
    board,
    generation_goal: aiExperiment.generation_goal,
    review_focus: aiExperiment.review_focus,
    target_difficulty: FONT_GRADES.includes(board.difficulty) ? board.difficulty : DEFAULT_FONT_GRADE,
  })
}
</script>
