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
        <el-alert
          class="local-mode-alert"
          type="info"
          :closable="false"
          show-icon
          title="本地模式：跳过登录后数据保存在本机，不同步云端。"
        />
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

      <el-segmented
        v-model="standardBoard.mode"
        :options="[
          { label: '线路库', value: 'routes' },
          { label: '待修复路线', value: 'repairs' },
        ]"
        @change="handleStandardModeChange"
      />

      <section class="section-block standard-filters">
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
        <el-select v-if="standardBoard.mode === 'routes'" v-model="standardBoard.filters.predicted_v_grade" clearable placeholder="预测难度">
          <el-option v-for="grade in standardBoard.difficulties" :key="`predicted-${grade}`" :label="grade" :value="grade" />
        </el-select>
        <el-select v-if="standardBoard.mode === 'routes'" v-model="standardBoard.filters.grade_warning" clearable placeholder="难度复核">
          <el-option label="轻微错配" value="soft" />
          <el-option label="严重错配" value="hard" />
          <el-option label="可信度不足" value="uncertain" />
        </el-select>
        <el-checkbox v-if="standardBoard.mode === 'routes'" v-model="standardBoard.filters.benchmark_only">只看标杆线</el-checkbox>
        <el-select v-if="standardBoard.mode === 'repairs'" v-model="standardBoard.repairFilters.status" placeholder="修复状态">
          <el-option label="已生成修复候选" value="repaired" />
          <el-option label="可尝试但未通过" value="repairable" />
          <el-option label="不可修复" value="unrepairable" />
        </el-select>
        <el-button
          type="primary"
          plain
          :loading="standardBoard.mode === 'routes' ? standardBoard.loading : standardBoard.repairLoading"
          @click="standardBoard.mode === 'routes' ? fetchStandardRoutes() : fetchRepairRoutes()"
        >
          应用筛选
        </el-button>
      </section>

      <el-alert v-if="standardBoard.error" type="error" :closable="false" :title="standardBoard.error" />
      <el-alert
        v-if="standardBoard.generatedMeta"
        type="success"
        :closable="false"
        :title="`已生成标准板线路：重用率 ${(standardBoard.generatedMeta.reuse_rate * 100).toFixed(1)}%，${standardBoard.generatedMeta.reuse_quality}`"
      />

      <div v-if="standardBoard.mode === 'routes'" class="standard-board-layout">
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
              <small>标称 {{ route.v_grade }} / 预测 {{ route.predicted_v_grade || '-' }} / {{ route.features.hold_count }} 点 / {{ tierLabel(route.quality_tier) }}</small>
              <small>{{ gradeWarningLabel(route) }}</small>
            </span>
            <span>
              <em>{{ route.quality_score ?? Math.round(route.score) }}</em>
              <small class="quality-tier">{{ tierLabel(route.quality_tier) }}</small>
              <small>难度 {{ route.difficulty_score ?? '-' }}</small>
              <small>{{ route.repeats }} repeats</small>
            </span>
          </button>
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
                  <p class="eyebrow">Selected Route</p>
                  <h3>{{ standardBoard.selected.display_name }}</h3>
                </div>
                <div class="command-row">
                  <el-button :type="standardBoard.activity?.favorite ? 'warning' : 'default'" plain @click="toggleStandardFavorite">
                    {{ standardBoard.activity?.favorite ? '取消收藏' : '收藏' }}
                  </el-button>
                  <el-button type="primary" plain @click="loadStandardIntoStudio">载入 Studio</el-button>
                </div>
              </div>
              <div class="standard-stats">
                <span>标称 {{ standardBoard.selected.v_grade }}</span>
                <span>预测 {{ standardBoard.selected.predicted_v_grade || '-' }}</span>
                <span>难度 {{ standardBoard.selected.difficulty_score ?? '-' }}</span>
                <span>{{ gradeWarningLabel(standardBoard.selected) }}</span>
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
              <section class="difficulty-panel">
                <div class="section-heading">
                  <div>
                    <p class="eyebrow">Difficulty</p>
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
                    <p class="eyebrow">Training Log</p>
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
              <span>系统会在网页画布中进行虚拟点亮，不连接任何真实控制器。</span>
            </div>
          </section>
        </section>
      </div>

      <div v-else class="standard-board-layout">
        <section class="section-block route-list-panel">
          <div class="section-heading">
            <div>
              <p class="eyebrow">Repair Queue</p>
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
          <div v-if="!standardBoard.repairs.length" class="empty-state">
            <strong>暂无待修复候选</strong>
            <span>切换状态或刷新队列后再试。</span>
          </div>
          <button
            v-for="repair in standardBoard.repairs"
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
              <strong>Standard route {{ repair.source_id }}</strong>
              <small>{{ repair.review_reasons?.join(' / ') || repair.repair_status }}</small>
              <small>预测 {{ repair.predicted_v_grade || '-' }} / {{ gradeWarningLabel(repair) }}</small>
            </span>
            <span>
              <em>{{ repair.quality_score ?? '-' }}</em>
              <small class="quality-tier">{{ repairStatusLabel(repair.repair_status) }}</small>
              <small>难度 {{ repair.difficulty_score ?? '-' }}</small>
            </span>
          </button>
        </section>

        <section class="standard-preview-column repair-preview-column">
          <div class="repair-comparison-grid">
            <article class="repair-preview-panel">
              <div class="preview-panel-heading">
                <span>修复前</span>
                <small>{{ standardBoard.repairComparison?.original?.predicted_v_grade || '-' }}</small>
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
                <small>{{ standardBoard.repairComparison?.repaired?.predicted_v_grade || '-' }}</small>
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
                  <p class="eyebrow">Repair Candidate</p>
                  <h3>Standard route {{ standardBoard.selectedRepair.source_id }}</h3>
                </div>
                <div class="command-row">
                  <el-button :disabled="standardBoard.selectedRepair.repair_status !== 'repaired'" @click="previewRepairRoute(standardBoard.selectedRepair.source_id)">预览修复</el-button>
                  <el-button type="primary" plain :disabled="!standardBoard.repairPreview?.board_asset" @click="loadRepairIntoStudio">载入 Studio</el-button>
                </div>
              </div>
              <div class="standard-stats">
                <span>{{ repairStatusLabel(standardBoard.selectedRepair.repair_status) }}</span>
                <span>补手点 {{ standardBoard.selectedRepair.added_start_hands?.join(', ') || '无' }}</span>
                <span>派生脚点 {{ standardBoard.selectedRepair.derived_start_feet?.join(', ') || '无' }}</span>
                <span>评分 {{ standardBoard.selectedRepair.quality_score ?? '-' }}</span>
                <span>预测 {{ standardBoard.selectedRepair.predicted_v_grade || '-' }}</span>
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
      </div>
    </section>

    <section v-else class="page ai-page">
      <div class="lab-panel">
        <div class="lab-heading">
          <div>
            <p class="eyebrow">AI Lab</p>
            <h2>实验任务</h2>
          </div>
          <el-button :icon="Refresh" :loading="boards.loading" @click="boards.fetchMyBoards">刷新岩板</el-button>
        </div>
        <section class="ai-board-picker">
          <div class="panel-heading">
            <div>
              <h3>选择岩板资产</h3>
              <span>AI Lab 会基于这里选中的岩板执行任务。</span>
            </div>
            <el-button v-if="selectedAiBoard" plain @click="loadSelectedAiBoardIntoStudio">载入 Studio</el-button>
          </div>
          <template v-if="boards.savedBoards.length">
            <el-select v-model="aiExperiment.selectedBoardId" placeholder="选择岩板资产">
              <el-option
                v-for="board in boards.savedBoards"
                :key="board.saved_id || board.route_name"
                :label="board.route_name || '未命名岩板'"
                :value="board.saved_id"
              />
            </el-select>
            <div class="ai-board-list">
              <button
                v-for="board in boards.savedBoards"
                :key="board.saved_id || board.route_name"
                type="button"
                class="ai-board-option"
                :class="{ active: selectedAiBoard?.saved_id === board.saved_id }"
                @click="selectAiBoard(board)"
              >
                <strong>{{ board.route_name || '未命名岩板' }}</strong>
                <span>{{ board.board_spec?.label || '岩板' }} / {{ board.placed_holds?.length || 0 }} 岩点 / {{ board.beta_sequence?.length || 0 }} Beta</span>
              </button>
            </div>
          </template>
          <div v-else class="empty-state">
            <strong>还没有可用于 AI Lab 的岩板资产</strong>
            <span>先在 Studio 保存岩板，或到岩板资产页确认已有数据。</span>
            <div class="command-row">
              <el-button type="primary" plain @click="activePage = 'boards'">查看岩板资产</el-button>
              <el-button @click="activePage = 'studio'">进入 Studio</el-button>
            </div>
          </div>
          <div v-if="selectedAiBoard" class="selected-board-summary">
            <strong>{{ selectedAiBoard.route_name || '未命名岩板' }}</strong>
            <span>{{ selectedAiBoardStats.spec }}</span>
            <span>{{ selectedAiBoardStats.holds }} 岩点</span>
            <span>{{ selectedAiBoardStats.beta }} Beta</span>
            <span>{{ selectedAiBoardStats.difficulty }}</span>
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
          <el-input
            v-model="aiExperiment.user_requirements"
            type="textarea"
            :rows="3"
            placeholder="输入本次实验要求，例如：增加动态动作，或检查脚点是否过高"
          />
        </div>
        <div class="command-row">
          <el-button type="primary" :disabled="!canRunAiExperiment" :loading="routeGen.loading" @click="runAiExperiment">提交所选岩板</el-button>
          <el-button v-if="routeGen.loading" @click="routeGen.cancelGeneration">取消任务</el-button>
          <el-button @click="activePage = 'studio'">返回 Studio</el-button>
        </div>
        <el-alert v-if="routeGen.taskId" type="info" :closable="false" :title="`任务 ID：${routeGen.taskId}`" />
        <el-alert v-if="routeGen.error" type="error" :closable="false" :title="routeGen.error" />
        <section v-if="routeGen.result" class="experiment-result">
          <div class="result-context">
            <span>分析岩板：{{ selectedAiBoard?.route_name || '所选岩板' }}</span>
            <span>{{ selectedAiBoardStats.holds }} 岩点 / {{ selectedAiBoardStats.beta }} Beta / {{ selectedAiBoardStats.difficulty }}</span>
            <span>{{ routeGen.result.llm_enriched ? 'LLM 已润色' : '本地算法结果' }}</span>
          </div>
          <div class="result-metrics">
            <span v-if="routeGen.result.analysis_summary">{{ routeGen.result.analysis_summary }}</span>
            <span v-if="routeGen.result.metrics?.target_v_grade">目标 {{ routeGen.result.metrics.target_v_grade }}</span>
            <span v-if="routeGen.result.metrics?.quality_score !== undefined">质量 {{ routeGen.result.metrics.quality_score }}</span>
            <span v-if="routeGen.result.metrics?.predicted_v_grade">预测 {{ routeGen.result.metrics.predicted_v_grade }}</span>
            <span v-if="routeGen.result.metrics?.risk_score !== undefined">风险 {{ routeGen.result.metrics.risk_score }}</span>
            <span v-if="routeGen.result.risk_level">等级 {{ riskLevelLabel(routeGen.result.risk_level) }}</span>
          </div>
          <div v-if="routeGen.result.applied_constraints?.length" class="result-metrics">
            <span v-for="constraint in routeGen.result.applied_constraints" :key="constraint">{{ constraint }}</span>
          </div>
          <template v-if="routeGen.result.mode === 'compose_route'">
            <el-alert
              v-if="routeGen.result.failure_suggestion"
              type="warning"
              :closable="false"
              :title="routeGen.result.failure_suggestion"
              show-icon
            />
            <article v-for="(route, index) in routeGen.result.selected_routes" :key="route.route_name" class="result-card">
              <span>{{ candidateMeta(index).label_text || '候选路线' }}</span>
              <strong>{{ route.route_name }}</strong>
              <p>{{ route.setter_commentary }}</p>
              <span>
                {{ route.placed_holds?.length || 0 }} 岩点 / {{ route.beta_sequence?.length || 0 }} Beta
                / 质量 {{ candidateMeta(index).quality_score ?? '-' }}
                / 预测 {{ candidateMeta(index).predicted_v_grade || '-' }}
              </span>
              <small v-if="candidateMeta(index).notes?.length">{{ candidateMeta(index).notes.join(' / ') }}</small>
              <el-button @click="loadBoardIntoStudio(route)">载入 Studio</el-button>
            </article>
          </template>
          <template v-else>
            <strong>{{ routeGen.result.review_summary }}</strong>
            <p>风险等级：{{ routeGen.result.risk_level }}</p>
            <article v-for="violation in routeGen.result.violations" :key="violation.code" class="result-card result-card-critical">
              <span>必须修</span>
              <strong>{{ violation.message }}</strong>
              <small v-if="violation.hold_ids?.length">相关岩点：{{ violation.hold_ids.join(', ') }}</small>
            </article>
            <article v-for="suggestion in routeGen.result.suggestions" :key="suggestion.title" class="result-card">
              <span>{{ suggestionGroupLabel(suggestion) }}</span>
              <strong>{{ suggestion.title }}</strong>
              <p>{{ suggestion.detail }}</p>
              <span v-if="suggestion.hold_ids?.length">相关岩点：{{ suggestion.hold_ids.join(', ') }}</span>
              <el-button v-if="suggestion.candidate_route" type="primary" plain @click="loadBoardIntoStudio(suggestion.candidate_route)">载入修复候选</el-button>
            </article>
          </template>
          <div v-if="routeGen.result.algorithm_notes?.length" class="result-metrics">
            <span v-for="note in routeGen.result.algorithm_notes" :key="note">{{ note }}</span>
          </div>
        </section>
      </div>
    </section>
  </AppShell>
</template>

<script setup>
import { computed, defineComponent, h, onMounted, reactive, ref, watch } from 'vue'
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
const aiExperiment = reactive({ mode: 'compose_route', user_requirements: '', selectedBoardId: '' })
const standardBoardColumns = Array.from({ length: 11 }, (_, index) => String.fromCharCode(65 + index))
const standardBoardRows = Array.from({ length: 18 }, (_, index) => index + 1)
const standardBoardSpec = {
  preset_id: 'classic-11x18',
  template_key: 'spray-small',
  label: 'Standard training board 11x18',
  name: 'Standard training board 11x18',
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
  angleLabel: '40 deg',
  material: 'wood composite',
  skinClass: 'skin-wood-classic',
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
  difficulties: ['V0', 'V1', 'V2', 'V3', 'V4', 'V5', 'V6', 'V7', 'V8', 'V9', 'V10'],
  filters: {
    difficulty: 'V3',
    predicted_v_grade: '',
    grade_warning: '',
    benchmark_only: false,
    sort: 'score_desc',
    limit: 24,
    offset: 0,
  },
  repairFilters: {
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
  studio: 'Studio 工作台',
  library: '岩点库',
  boards: '岩板资产',
  'standard-board': '标准板库',
  'ai-lab': 'AI Lab',
}[activePage.value] || 'Climbing Board Studio'))

const selectedDashboardTemplate = computed(() => (
  studio.boardPresets.find((template) => template.id === selectedDashboardTemplateId.value) || studio.boardPresets[0]
))

const selectedAiBoard = computed(() => {
  if (!boards.savedBoards.length) return null
  return boards.savedBoards.find((board) => board.saved_id === aiExperiment.selectedBoardId) || boards.savedBoards[0]
})

const selectedAiBoardStats = computed(() => {
  const board = selectedAiBoard.value
  return {
    holds: board?.placed_holds?.length || 0,
    beta: board?.beta_sequence?.length || 0,
    difficulty: board?.difficulty || 'V3',
    spec: board?.board_spec?.label || board?.board_spec?.name || '岩板',
  }
})

const aiBoardWarnings = computed(() => {
  const board = selectedAiBoard.value
  if (!board) return ['请先从岩板资产中选择一块岩板。']

  const holds = board.placed_holds || []
  if (!holds.length) return ['所选岩板没有岩点，无法提交 AI Lab。']

  const warnings = []
  const startZoneCount = holds.filter((hold) => hold.y >= 1 && hold.y <= 4).length
  const topZoneCount = holds.filter((hold) => hold.y >= 16 && hold.y <= 18).length
  const hasStartJug = holds.some((hold) => hold.y >= 1 && hold.y <= 4 && hold.hold_type === 'Jug')
  const hasTopJug = holds.some((hold) => hold.y >= 16 && hold.y <= 18 && hold.hold_type === 'Jug')

  if (startZoneCount < 2) warnings.push('起步区岩点少于 2 个。')
  if (topZoneCount < 1) warnings.push('完攀区缺少岩点。')
  if (!hasStartJug) warnings.push('起步区缺少 Jug，重组成功率会降低。')
  if (!hasTopJug) warnings.push('完攀区缺少 Jug，重组成功率会降低。')
  if (!board.beta_sequence?.length) warnings.push('没有 Beta 序列，修改建议会偏向结构检查。')

  return warnings
})

const aiBoardBlockingMessage = computed(() => {
  const board = selectedAiBoard.value
  if (!board) return '请先选择一块已保存的岩板。'

  const holds = board.placed_holds || []
  if (!holds.length) return '所选岩板没有岩点，无法提交。'
  if (aiExperiment.mode !== 'compose_route') return ''

  const startZoneCount = holds.filter((hold) => hold.y >= 1 && hold.y <= 4).length
  const topZoneCount = holds.filter((hold) => hold.y >= 16 && hold.y <= 18).length
  if (holds.length < 6) return '重新组合路线至少需要 6 个岩点。'
  if (startZoneCount < 2) return '重新组合路线需要至少 2 个起步区岩点。'
  if (topZoneCount < 1) return '重新组合路线需要至少 1 个完攀区岩点。'
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

onMounted(async () => {
  if (currentUser.value) await Promise.all([library.fetchAllHoldData(), boards.fetchMyBoards(), fetchStandardRoutes()])
})

watch(
  () => boards.savedBoards,
  (savedBoards) => {
    if (!savedBoards.length) {
      aiExperiment.selectedBoardId = ''
      return
    }
    if (!savedBoards.some((board) => board.saved_id === aiExperiment.selectedBoardId)) {
      aiExperiment.selectedBoardId = savedBoards[0].saved_id || ''
    }
  },
  { immediate: true }
)

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
    console.warn('Standard-board activity unavailable', error)
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
  studio.loadBoard(boardAsset)
  activePage.value = 'studio'
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

function riskLevelLabel(level) {
  return {
    low: '低',
    medium: '中',
    high: '高',
  }[level] || level
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
  ElMessage.info(`已提交“${board.route_name || '未命名岩板'}”，AI Lab 将返回可查询任务结果。`)
  routeGen.generateRoute({
    mode: aiExperiment.mode,
    board,
    user_requirements: aiExperiment.user_requirements,
    target_difficulty: board.difficulty || 'V3',
  })
}
</script>
