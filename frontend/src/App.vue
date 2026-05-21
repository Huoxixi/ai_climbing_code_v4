<template>
  <div class="symbiosis-app">
    <header class="workspace-topbar">
      <div class="topbar-brand-block">
        <div class="topbar-logo">🧗</div>
        <div>
          <div class="topbar-kicker">Climbing Board Simulator</div>
          <h1>攀岩岩板模拟设计系统</h1>
        </div>
      </div>
      <div class="topbar-center">
        <span class="status-pill" :class="editorMode">{{ editorModeLabel }}</span>
        <span class="status-pill subtle">{{ currentBoardSpec.label }}</span>
        <span class="status-pill subtle">{{ currentBoard.placed_holds.length }} 个岩点</span>
        <span class="status-pill subtle">{{ unsavedChanges ? '有未保存修改' : '已同步到本地状态' }}</span>
      </div>
      <div class="user-entry">
        <template v-if="currentUser">
          <div class="user-avatar">{{ currentUser.name.slice(0, 1).toUpperCase() }}</div>
          <div class="user-meta">
            <strong>{{ currentUser.name }}</strong>
            <span>云端同步接口已预留</span>
          </div>
          <button class="ghost-btn" @click="handleLogout">退出</button>
        </template>
        <template v-else>
          <button class="login-btn" @click="showLoginDialog = true">登录 / 云端入口</button>
        </template>
      </div>
    </header>

    <nav class="workspace-switcher" aria-label="功能页导航">
      <button
        v-for="item in workspaceTabs"
        :key="item.key"
        :class="{ active: activeWorkspace === item.key }"
        @click="activeWorkspace = item.key"
      >
        <span class="tab-icon">{{ item.icon }}</span>
        <span class="tab-copy">
          <strong>{{ item.label }}</strong>
          <small>{{ item.desc }}</small>
        </span>
      </button>
    </nav>

    <div v-if="showLoginDialog" class="login-dialog-backdrop" @click.self="showLoginDialog = false">
      <div class="login-dialog">
        <div class="login-dialog-header">
          <div>
            <span>Account Portal</span>
            <h2>登录入口预览</h2>
          </div>
          <button @click="showLoginDialog = false">✕</button>
        </div>
        <p class="login-note">当前为本地 Mock 登录。后续接入云数据库时，可直接替换为真实鉴权接口。</p>
        <div class="field">
          <label>邮箱</label>
          <input v-model="loginForm.email" type="email" placeholder="setter@example.com" />
        </div>
        <div class="field">
          <label>显示名称</label>
          <input v-model="loginForm.name" type="text" placeholder="定线员名称" />
        </div>
        <button class="login-submit" @click="handleLogin">进入工作台</button>
      </div>
    </div>

    <div v-if="loading" class="loading-overlay">
      <div class="loading-content">
        <div class="progress-circle">
          <svg viewBox="0 0 100 100">
            <circle class="bg" cx="50" cy="50" r="45"></circle>
            <circle class="pulse" cx="50" cy="50" r="45"></circle>
          </svg>
          <div class="agent-avatar">AI</div>
        </div>
        <div class="reflection-log">
          <p class="log-line animate-pulse">{{ currentReflectionMsg }}</p>
        </div>
      </div>
    </div>

    <div class="main-layout" :class="`workspace-${activeWorkspace}`">
      <section v-if="activeWorkspace === 'dashboard'" class="dashboard-workspace">
        <div class="dashboard-hero-card">
          <div>
            <span class="section-kicker">Board Simulation Operations</span>
            <h2>自由组合岩点，搭建你的模拟岩板</h2>
            <p>当前版本聚焦“岩板模拟设计”：选择底层岩板规格、组合岩点库、拖拽布点、编辑岩板属性并保存资产。AI 定线功能已暂时封印，避免干扰手动设计流程。</p>
            <div class="dashboard-actions">
              <button class="primary" @click="startStudioWithBlankBoard">开始模拟建板</button>
              <button @click="activeWorkspace = 'library'">管理岩点资源</button>
            </div>
          </div>
          <div class="dashboard-metrics">
            <div><strong>{{ currentBoard.placed_holds.length }}</strong><span>当前岩点</span></div>
            <div><strong>{{ routeSteps.length }}</strong><span>Beta 动作</span></div>
            <div><strong>{{ savedBoards.length }}</strong><span>保存岩板</span></div>
            <div><strong>{{ managedHolds.length }}</strong><span>资源岩点</span></div>
          </div>
        </div>

        <div class="dashboard-card-grid">
          <article class="dashboard-card">
            <span>底层岩板</span>
            <strong>{{ currentBoardSpec.label }}</strong>
            <small>{{ currentBoardSpec.columns }} 列 × {{ currentBoardSpec.rows }} 行 · {{ currentBoardSpec.angleLabel }}</small>
          </article>
          <article class="dashboard-card">
            <span>编辑状态</span>
            <strong>{{ editorModeLabel }}</strong>
            <small>{{ unsavedChanges ? '当前岩板存在未保存修改' : '当前状态已同步' }}</small>
          </article>
          <article class="dashboard-card">
            <span>候选岩点池</span>
            <strong>{{ holdPool.length }}</strong>
            <small>可拖拽到岩板的候选岩点</small>
          </article>
          <article class="dashboard-card">
            <span>资源覆盖</span>
            <strong>{{ managedHolds.length }}</strong>
            <small>图片与矢量资源合计</small>
          </article>
        </div>

        <BoardTemplatePicker
          :templates="boardPresets"
          :active-template-id="activeBoardPresetId"
          @select="startBoardFromPreset"
        />

        <div class="dashboard-lower-grid">
          <section class="dashboard-panel">
            <h3>⚡ 快速开始</h3>
            <div class="quick-action-grid">
              <button @click="startStudioWithBlankBoard">＋ 新建模拟岩板</button>
              <button @click="activeWorkspace = 'studio'">规格 选择岩板规格</button>
              <button @click="activeWorkspace = 'library'">🧱 管理岩点资源</button>
              <button @click="activeWorkspace = 'boards'">🗂️ 查看岩板资产</button>
            </div>
          </section>
          <section class="dashboard-panel">
            <h3>最近岩板</h3>
            <div v-if="!savedBoards.length" class="pool-empty-state">暂无已保存岩板。</div>
            <div v-for="board in savedBoards.slice(0, 5)" :key="board.saved_id" class="saved-board-item premium" @click="loadSavedBoard(board); activeWorkspace = 'studio'">
              <div class="saved-board-info">
                <div class="saved-board-name">{{ board.route_name }}</div>
                <div class="saved-board-difficulty">{{ board.beta_sequence?.length || 0 }} moves · 点击载入 Studio</div>
              </div>
            </div>
          </section>
        </div>
      </section>

      <section v-if="activeWorkspace === 'ai-lab'" class="ai-lab-workspace">
        <div class="ai-sealed-card">
          <span class="section-kicker">AI Lab · Sealed</span>
          <h2>AI 定线功能暂时封印</h2>
          <p>
            当前版本的产品主路径已切换为“岩板模拟设计系统”。AI 生成路线不会作为主入口触发，
            也不会向用户推荐自动定线流程。你可以继续在 Studio 中选择岩板模板、组合岩点池、拖拽布点、编辑 Beta 并保存岩板资产。
          </p>
          <div class="sealed-roadmap">
            <div><strong>当前可用</strong><span>多规格岩板 · 手动布点 · 岩点池 · Beta 编辑 · 资产保存</span></div>
            <div><strong>暂不开放</strong><span>/api/generate 自动生成与 AI CTA 主流程</span></div>
            <div><strong>未来恢复</strong><span>保留实验室入口，后续可在不干扰模拟系统的前提下恢复</span></div>
          </div>
          <div class="dashboard-actions">
            <button class="primary" @click="activeWorkspace = 'studio'">返回模拟设计</button>
            <button @click="activeWorkspace = 'dashboard'">查看系统总览</button>
          </div>
        </div>
      </section>

      <section v-if="activeWorkspace === 'library'" class="workspace-page library-workspace">
        <div class="workspace-page-header">
          <div>
            <span class="section-kicker">Hold Library</span>
            <h2>岩点资源管理</h2>
            <p>这里专注处理岩点资源的上传、预览和删除。岩板设计页只调用这些资源，不再混入资源管理表单。</p>
          </div>
          <div class="module-jump-actions">
            <button class="primary" @click="activeWorkspace = 'studio'">返回岩板设计</button>
            <button @click="activeWorkspace = 'boards'">查看岩板资产</button>
          </div>
        </div>

        <div class="library-layout-grid">
          <section class="workspace-panel resource-upload-panel">
            <h3 class="group-title">🛠️ 上传新岩点</h3>
            <div class="upload-section">
              <div class="field">
                <label>岩点类型</label>
                <select v-model="uploadInfo.hold_type">
                  <option v-for="type in holdTypes" :key="type" :value="type">{{ type }}</option>
                </select>
              </div>
              <div class="field">
                <label>变体名称 (英文/数字)</label>
                <input type="text" v-model="uploadInfo.variant" placeholder="例如: large_crimp_01">
              </div>
              <input type="file" @change="onFileChange" accept="image/*" />
              <button @click="uploadImage" :disabled="!uploadInfo.file || !uploadInfo.variant">上传新岩点</button>
            </div>
          </section>

          <section class="workspace-panel resource-library-panel">
            <div class="panel-title-row">
              <div>
                <h3 class="group-title">▦ 已录入岩点</h3>
                <p>{{ managedHolds.length }} 个资源岩点，可在 Studio 中作为设计素材使用。</p>
              </div>
              <button @click="fetchAllHoldData">刷新资源</button>
            </div>
            <div class="hold-library workspace-library-list">
              <div v-for="hold in managedHolds" :key="hold.key" class="library-item">
                <div class="library-item-thumbnail">
                  <div class="thumbnail-visual">
                    <template v-if="hold.svgPath">
                      <svg viewBox="0 0 100 100" class="vector-svg">
                        <path :d="hold.svgPath" :fill="getShapeColor(hold.hold_type)" />
                      </svg>
                    </template>
                    <template v-else-if="hold.imageUrl">
                      <img :src="hold.imageUrl" class="hold-image" />
                    </template>
                  </div>
                </div>
                <div class="library-item-info">
                  <span class="info-type">{{ hold.hold_type }}</span>
                  <span class="info-variant">{{ hold.variant }}</span>
                </div>
                <button @click="deleteHold(hold.hold_type, hold.variant)" class="library-item-delete-btn">🗑️</button>
              </div>
              <div v-if="managedHolds.length === 0" class="pool-empty-state">
                岩点库是空的，请先上传新岩点。
              </div>
            </div>
          </section>
        </div>
      </section>

      <section v-if="activeWorkspace === 'boards'" class="workspace-page boards-workspace">
        <div class="workspace-page-header">
          <div>
            <span class="section-kicker">Board Assets</span>
            <h2>岩板资产</h2>
            <p>这里专注保存岩板的查看、载入、重命名和删除。点击“载入编辑”后再进入 Studio，不再占用设计页侧栏。</p>
          </div>
          <div class="module-jump-actions">
            <button class="primary" @click="startStudioWithBlankBoard">新建模拟岩板</button>
            <button @click="activeWorkspace = 'library'">管理岩点资源</button>
          </div>
        </div>

        <section class="workspace-panel boards-asset-panel">
          <div class="panel-title-row">
            <div>
              <h3 class="group-title">🗂️ 已保存岩板</h3>
              <p>{{ savedBoards.length ? `共 ${savedBoards.length} 个岩板资产` : '暂无已保存岩板资产' }}</p>
            </div>
            <button @click="fetchMyBoards">刷新列表</button>
          </div>

          <div v-if="!savedBoards.length" class="asset-empty-card">
            <strong>还没有保存岩板</strong>
            <span>进入岩板设计页完成布点后，可以将当前岩板保存为资产。</span>
            <button @click="activeWorkspace = 'studio'">去岩板设计</button>
          </div>

          <div v-else class="asset-card-grid">
            <article v-for="board in savedBoards" :key="board.saved_id" class="asset-card">
              <div class="asset-card-main" @click="loadSavedBoard(board); activeWorkspace = 'studio'">
                <span class="asset-kicker">{{ board.board_spec?.label || '模拟岩板' }}</span>
                <h3>{{ board.route_name }}</h3>
                <p>{{ board.setter_commentary || '暂无备注' }}</p>
                <div class="asset-meta-row">
                  <span>{{ board.placed_holds?.length || 0 }} 个岩点</span>
                  <span>{{ board.beta_sequence?.length || 0 }} 个动作</span>
                  <span>{{ board.visibility || 'private' }}</span>
                </div>
              </div>
              <div class="asset-actions">
                <button class="primary" @click="loadSavedBoard(board); activeWorkspace = 'studio'">载入编辑</button>
                <button @click="renameSavedBoard(board)">重命名</button>
                <button class="danger" @click="deleteSavedBoard(board)">删除</button>
              </div>
            </article>
          </div>
        </section>
      </section>

      <aside v-if="activeWorkspace === 'studio'" class="sidebar studio-tools-sidebar" :class="{ 'is-collapsed': !isSidebarOpen }">
        <div class="sidebar-content">
          <header class="brand">
            <div class="logo">🧗‍♂️</div>
            <div class="titles">
              <h1>岩板模拟系统</h1>
              <p>Board Simulation Workspace</p>
            </div>
          </header>

          <section class="config-group">
            <h3 class="group-title">🧭 岩板模拟参数</h3>
            <div class="field">
              <label>底层岩板规格</label>
              <select v-model="activeBoardPresetId" @change="applyBoardPreset(activeBoardPresetId)">
                <option v-for="preset in boardPresets" :key="preset.id" :value="preset.id">
                  {{ preset.label }} · {{ preset.columns }}×{{ preset.rows }}
                </option>
              </select>
            </div>
            <div class="board-preset-summary">
              <strong>{{ currentBoardSpec.label }}</strong>
              <span>{{ currentBoardSpec.description }}</span>
              <small>{{ currentBoardSpec.columns }} 列 × {{ currentBoardSpec.rows }} 行 · {{ currentBoardSpec.angleLabel }} · {{ currentBoardSpec.material }}</small>
            </div>
            <div class="simulation-note">
              当前阶段已封印 AI 定线，工作台只保留手动组合岩点、模拟布板、动作序列编辑和资产保存。
            </div>
          </section>

<section class="config-group">
  <h3 class="group-title">🧪 定线岩点选择 (Hold Selector)</h3>
  <div class="hold-creator-console">
    <div class="creator-grid">
      <!-- 左侧：参数控制 -->
      <div class="creator-controls">
        <div class="field">
          <label>类型 (Type)</label>
          <select v-model="draftHold.type">
            <option v-for="type in holdTypes" :key="type" :value="type">{{ type }}</option>
          </select>
        </div>
        <div class="field">
          <label>形状 (Variant)</label>
          <select v-model="draftHold.variant">
            <option value="random">随机</option>
            <option v-for="v in availableVariants" :key="v" :value="v">{{ v }}</option>
          </select>
        </div>
        <div class="field">
          <label>缩放 (Scale): {{ draftHold.scale.toFixed(1) }}x</label>
          <input type="range" min="0.5" max="2" step="0.1" v-model.number="draftHold.scale" />
        </div>
        <div class="field">
          <label>旋转 (Rotation): {{ draftHold.rotation }}°</label>
          <input type="range" min="0" max="360" step="5" v-model.number="draftHold.rotation" />
        </div>
      </div>
      <!-- 右侧：可视化预览 -->
      <div class="creator-preview-wrapper">
        <div class="creator-preview">
          <div class="preview-visual-large" :style="{ transform: `rotate(${draftHold.rotation}deg) scale(${draftHold.scale})` }">
            <template v-if="previewMode === 'vector'">
              <svg v-if="getHoldSvg({ hold_type: draftHold.type, variant: draftHold.variant })" viewBox="0 0 100 100" class="vector-svg">
                <path :d="getHoldSvg({ hold_type: draftHold.type, variant: draftHold.variant })" :fill="getShapeColor(draftHold.type)" />
              </svg>
              <span v-else class="no-preview-text">无矢量图</span>
            </template>
            <template v-if="previewMode === 'image'">
              <img v-if="getHoldImage({ hold_type: draftHold.type, variant: draftHold.variant })" :src="getHoldImage({ hold_type: draftHold.type, variant: draftHold.variant })" class="hold-image" />
              <span v-else class="no-preview-text">无真实图</span>
            </template>
          </div>
        </div>
        <div class="preview-toggle">
            <button @click="previewMode = 'vector'" :class="{ active: previewMode === 'vector' }">矢量</button>
            <button @click="previewMode = 'image'" :class="{ active: previewMode === 'image' }">真实</button>
        </div>
      </div>
    </div>
    <button @click="addHoldToPool" class="add-to-pool-btn">➕ 添加到岩点池</button>
  </div>
</section>

<section class="config-group">
  <h3 class="group-title">📦 岩点池 (Hold Pool)</h3>
  <div class="hold-pool-roster">
    <div v-if="!holdPool.length" class="pool-empty-state">
      岩点池是空的，请从上方定线岩点选择添加。
    </div>
    <div v-for="hold in holdPool" :key="hold.id" class="pool-item-card">
      <div class="pool-item-thumbnail">
        <div class="thumbnail-visual" :style="{ transform: `rotate(${hold.rotation}deg) scale(${hold.scale})` }">
          <template v-if="getHoldSvg({ hold_type: hold.type, variant: hold.variant })">
            <svg viewBox="0 0 100 100" class="vector-svg">
              <path :d="getHoldSvg({ hold_type: hold.type, variant: hold.variant })" :fill="getShapeColor(hold.type)" />
            </svg>
          </template>
          <template v-else-if="getHoldImage({ hold_type: hold.type, variant: hold.variant })">
            <img :src="getHoldImage({ hold_type: hold.type, variant: hold.variant })" class="hold-image" />
          </template>
        </div>
      </div>
      <div class="pool-item-info">
        <span class="info-type">{{ hold.type }} - {{ hold.variant }}</span>
        <span class="info-params">{{ hold.rotation }}°, {{ hold.scale.toFixed(1) }}x</span>
      </div>
      <button @click="removeHoldFromPool(hold.id)" class="pool-item-remove-btn">✖</button>
    </div>
  </div>
</section>

<section class="config-group compact-studio-panel">
  <h3 class="group-title">🎛️ 当前岩板</h3>
  <div class="field">
    <label>岩板名称</label>
    <input v-model="currentBoard.route_name" @input="markUnsaved" />
  </div>
  <div class="input-row">
    <div class="field">
      <label>来源</label>
      <input :value="currentBoard.source_type || editorMode" disabled />
    </div>
    <div class="field">
      <label>可见性</label>
      <select v-model="currentBoard.visibility" @change="markUnsaved">
        <option value="private">私有</option>
        <option value="team">团队</option>
        <option value="public">公开</option>
      </select>
    </div>
  </div>
  <div class="field">
    <label>备注 / 定线说明</label>
    <textarea v-model="currentBoard.setter_commentary" @input="markUnsaved"></textarea>
  </div>
</section>

<section class="config-group compact-studio-panel">
  <h3 class="group-title">🧩 选中岩点</h3>
  <div v-if="!selectedHold" class="pool-empty-state">点击岩板上的岩点后可编辑参数。</div>
  <template v-else>
    <div class="selected-hold-id">{{ selectedHold.id }}</div>
    <div class="input-row">
      <div class="field">
        <label>类型</label>
        <select v-model="selectedHold.hold_type" @change="syncSelectedHoldType">
          <option v-for="type in holdTypes" :key="type" :value="type">{{ type }}</option>
        </select>
      </div>
      <div class="field">
        <label>形状</label>
        <input v-model="selectedHold.variant" @input="markUnsaved" />
      </div>
    </div>
    <div class="field">
      <label>旋转：{{ Number(selectedHold.rotation || 0).toFixed(0) }}°</label>
      <input type="range" min="0" max="360" step="5" v-model.number="selectedHold.rotation" @input="markUnsaved" />
    </div>
    <div class="field">
      <label>缩放：{{ Number(selectedHold.scale || 1).toFixed(1) }}x</label>
      <input type="range" min="0.5" max="2" step="0.1" v-model.number="selectedHold.scale" @input="markUnsaved" />
    </div>
    <div class="inspector-actions">
      <button @click="toggleSelectedStart">{{ selectedHold.is_start ? '取消起步点' : '设为起步点' }}</button>
      <button class="danger" @click="deletePlacedHold(selectedHold)">删除岩点</button>
    </div>
  </template>
</section>

<section v-if="routeSteps.length" class="config-group compact-studio-panel studio-beta-panel">
  <h3 class="group-title">📜 攀爬动作序列</h3>
  <div class="beta-editor-panel">
    <div class="field compact-field">
      <label>当前编辑肢体</label>
      <select v-model="betaEditor.selectedLimb">
        <option value="" disabled>请选择左手/右手/左脚/右脚</option>
        <option v-for="limb in limbOptions" :key="limb" :value="limb">{{ getLimbName(limb) }}</option>
      </select>
    </div>
    <div class="beta-editor-status" :class="{ active: isBetaEditorActive }">
      {{ isBetaEditorActive ? `待选点：${betaEditModeLabel}` : '点击动作卡片上的按钮开始编辑' }}
    </div>
    <button v-if="isBetaEditorActive" class="beta-editor-cancel" @click="cancelBetaEdit">取消编辑</button>
  </div>
  <div class="step-scroll-area compact-step-scroll">
    <div v-for="(m, idx) in routeSteps" :key="idx"
         class="step-item"
         :class="{ 
           'is-active': idx === currentIndex, 
           'is-top': m.is_top,
           'is-start': m.step === 0,
           'is-edit-target': betaEditor.targetIndex === idx
         }"
         @click="currentIndex = idx">
      <div class="step-indicator">
        <div class="step-line"></div>
        <div class="step-number">{{ m.step }}</div>
      </div>
      <div class="step-content">
        <div class="step-meta">
          <span class="limb-tag" :class="m.limb.toLowerCase()">{{ getLimbName(m.limb) }}</span>
          <span class="hold-id">{{ m.hold_id }}</span>
        </div>
        <p class="intent" v-if="m.intent">{{ m.intent }}</p>
        <p class="intent" v-else-if="m.step === 0">上墙起步</p>
        <div class="step-actions">
          <button @click.stop="startBetaEdit('edit', idx)">改</button>
          <button @click.stop="startBetaEdit('insert-before', idx)">前插</button>
          <button @click.stop="startBetaEdit('insert-after', idx)">后插</button>
          <button class="danger" @click.stop="deleteBetaStep(idx)">删</button>
        </div>
      </div>
      <div v-if="m.is_top" class="top-medal">🏆</div>
    </div>
  </div>
</section>

          <footer class="actions">
            <button @click="notifyAiSealed" :disabled="loading" class="generate-btn sealed-generate-btn" v-if="!loading">
              AI 定线已封印
            </button>
            <button @click="cancelGeneration" class="generate-btn cancel-btn" v-if="loading">
              ❌ 取消生成
            </button>
            <div v-if="error" class="error-toast">{{ error }}</div>
          </footer>
        </div>
      </aside>

      <button v-if="activeWorkspace === 'studio'" class="sidebar-toggle-btn" @click="isSidebarOpen = !isSidebarOpen" :class="{ 'is-closed': !isSidebarOpen }">
        {{ isSidebarOpen ? '◀' : '▶' }}
      </button>

      <main v-if="activeWorkspace === 'studio'" class="stage studio-stage">
        <!-- 岩板旁快捷岩点池：区别于左侧“定线配置岩点池” -->
        <aside class="board-side-hold-pool" :class="{ 'is-open': isBoardPoolOpen }">
          <button
            v-if="!isBoardPoolOpen"
            class="board-pool-toggle"
            @click="isBoardPoolOpen = true"
            title="打开岩板快捷岩点池"
          >
            🧱<span>岩点池</span>
          </button>

          <div v-else class="board-pool-panel">
            <div class="board-pool-header">
              <div>
                <h3>🧱 岩板快捷岩点池</h3>
                <p>从这里拖拽岩点到岩板上</p>
              </div>
              <button class="board-pool-close" @click="isBoardPoolOpen = false">✕</button>
            </div>

            <div class="board-pool-tabs">
              <button
                @click="boardPoolSource = 'board'"
                :class="{ active: boardPoolSource === 'board' }"
              >
                本岩板已添加类型
              </button>
              <button
                @click="boardPoolSource = 'all'"
                :class="{ active: boardPoolSource === 'all' }"
              >
                全部已有类型
              </button>
            </div>

            <div class="board-pool-filters">
              <button
                v-for="type in boardPoolTypeFilters"
                :key="type"
                @click="boardPoolFilter = type"
                :class="{ active: boardPoolFilter === type }"
              >
                {{ type === 'All' ? '全部' : type }}
              </button>
            </div>

            <div class="board-pool-list">
              <div v-if="filteredBoardPoolHolds.length === 0" class="board-pool-empty">
                当前分类下暂无可用岩点。
              </div>
              <div
                v-for="hold in filteredBoardPoolHolds"
                :key="hold.key"
                class="board-pool-hold-card"
                @mousedown="onHoldMouseDown($event, hold, true)"
                :title="`拖拽 ${hold.type} - ${hold.variant} 到岩板`"
              >
                <div class="board-pool-hold-thumb">
                  <div class="hold-visual" :style="{ transform: `rotate(${hold.rotation || 0}deg) scale(${Math.min(1.15, hold.scale || 1)})` }">
                    <template v-if="getHoldSvg(hold)">
                      <svg viewBox="0 0 100 100" class="vector-svg">
                        <path :d="getHoldSvg(hold)" :fill="getShapeColor(hold.type)" />
                      </svg>
                    </template>
                    <template v-else-if="getHoldImage(hold)">
                      <img :src="getHoldImage(hold)" class="hold-image" />
                    </template>
                    <template v-else>
                      <div class="geometric-shape" :class="hold.type.toLowerCase()" :style="{ color: getShapeColor(hold.type) }">
                        <div class="inner-shadow"></div>
                        <div class="bolt-hole"></div>
                      </div>
                    </template>
                  </div>
                </div>
                <div class="board-pool-hold-info">
                  <span class="board-pool-hold-type">{{ hold.type }}</span>
                  <span class="board-pool-hold-variant">{{ hold.variant }}</span>
                </div>
                <span v-if="hold.count > 1" class="board-pool-count">×{{ hold.count }}</span>
              </div>
            </div>
          </div>
        </aside>

        <div class="stage-header">
          <div class="route-info">
            <h2>{{ currentBoard.route_name }}</h2>
            <div class="commentary-card" v-if="currentBoard.setter_commentary">
              <span class="quote-icon">"</span>
              <p>{{ currentBoard.setter_commentary }}</p>
            </div>
          </div>
        </div>

        <div class="board-toolbar">
          <button @click="createNewBlankBoard">＋ 新建模拟岩板</button>
          <button @click="saveBoard" :disabled="!currentBoard.placed_holds.length">💾 保存当前岩板</button>
          <button @click="clearCurrentBoard" :disabled="!currentBoard.placed_holds.length">🧹 清空岩板</button>
          <button @click="activeWorkspace = 'library'">▦ 岩点资源</button>
          <button @click="activeWorkspace = 'boards'">🗂️ 岩板资产</button>
          <button @click="notifyAiSealed" class="sealed-tool">🔒 AI 定线封印中</button>
        </div>

        <div class="wall-display">
          <div class="wall-frame" :class="[{ 'is-empty-board': !placedHolds.length }, currentBoardSpec.skinClass]" :style="boardFrameStyle">
            <div v-if="!placedHolds.length" class="blank-board-hint">
              <strong>空白岩板已就绪</strong>
              <span>选择底层岩板规格后，点击孔位或从快捷岩点池拖拽岩点上墙。</span>
            </div>
            <!-- 坐标轴 -->
            <div class="axis-x">
              <span v-for="x in coordinateColumns" :key="x">{{ x }}</span>
            </div>
            <div class="axis-y">
              <span v-for="y in coordinateRows" :key="y">{{ y }}</span>
            </div>

            <div class="grid-backdrop">
              <template v-for="y in coordinateRows" :key="'y-'+y">
                <div v-for="x in coordinateColumns" :key="x+y"
                     class="hole" :style="getCoord(x+y)" @click.stop="placeDraftHoldAt(x+y)"></div>
              </template>
            </div>

             <div v-for="hold in placedHolds" :key="hold.id"
                  class="hold-entity"
                  :class="{ 'start-glow': isStart(hold.id), 'top-glow': isTop(hold.id), 'is-selected': selectedHold && selectedHold.id === hold.id, 'is-beta-pick-target': isBetaEditorActive }"
                  :style="getCoord(hold.id)"
                   @mousedown="onHoldMouseDown($event, hold)"
                   @contextmenu.prevent="deletePlacedHold(hold)">
              <div class="hold-visual" :style="{ transform: `rotate(${hold.rotation}deg) scale(${hold.scale || 1.0})` }">
                <!-- 优先渲染 SVG 矢量 -->
                <div v-if="getHoldSvg(hold)" class="hold-vector-container">
                  <svg :viewBox="'0 0 100 100'" class="vector-svg">
                    <path :d="getHoldSvg(hold)" :fill="getShapeColor(hold.hold_type || hold.type)" />
                  </svg>
                </div>

                <!-- 其次显示图片 -->
                <div v-else-if="getHoldImage(hold)" class="hold-image-container">
                  <img :src="getHoldImage(hold)" class="hold-image" />
                </div>
                
                <!-- 无图片时回退到 CSS 图形 -->
                <div v-else class="geometric-shape" 
                     :class="(hold.hold_type || hold.type).toLowerCase()"
                     :style="{ color: getShapeColor(hold.hold_type || hold.type) }">
                  <div class="inner-shadow"></div>
                  <div class="bolt-hole"></div>
                </div>
              </div>
              <div class="hold-tooltip">
                <div class="tooltip-row"><span class="label">ID:</span> {{ hold.id }}</div>
                <div class="tooltip-row"><span class="label">类型:</span> {{ hold.hold_type || hold.type }}</div>
                <div class="tooltip-row"><span class="label">旋转:</span> {{ hold.rotation }}°</div>
              </div>
            </div>

            <div v-for="(pos, limb) in currentLimbs" :key="limb"
                 class="limb-cursor" :class="limb.toLowerCase()"
                 :style="getCoord(pos.id)">
              <span class="limb-icon">{{ getLimbEmoji(limb) }}</span>
            </div>
          </div>

          <!-- 移到岩板下方 -->
          <div class="controls" :style="controlPanelStyle">
            <div class="control-labels">
              <span class="step-counter">动作序列 {{ routeSteps.length > 0 ? currentIndex + 1 : 0 }} / {{ routeSteps.length }}</span>
              <span class="difficulty-tag">{{ profile.target_difficulty }}</span>
            </div>
            <input type="range" v-model.number="currentIndex" min="0" :max="maxIndex" class="modern-slider" />
             <div class="route-actions">
                <div class="route-switcher">
                    <button @click="activeRouteIndex = 0" :class="{ 'active': activeRouteIndex === 0 }" :disabled="allRoutes.length < 1">①</button>
                    <button @click="activeRouteIndex = 1" :class="{ 'active': activeRouteIndex === 1 }" :disabled="allRoutes.length < 2">②</button>
                </div>
                 <button @click="saveBoard" class="save-board-btn" :disabled="!currentBoard.placed_holds.length">💾 {{ currentBoard?.saved_id ? '更新岩板' : '保存岩板' }}</button>
            </div>
            <div v-if="isBetaEditorActive" class="beta-edit-hint">
              <span>正在{{ betaEditModeLabel }}：{{ betaEditor.selectedLimb ? `选择 ${getLimbName(betaEditor.selectedLimb)}` : '请先选择左手/右手/左脚/右脚' }}，然后点击岩板上已有岩点作为目标。</span>
              <button @click="cancelBetaEdit">取消本次操作</button>
            </div>
          </div>
        </div>
      </main>

      <!-- 右侧边栏: 攀爬动作序列 -->
      <aside v-if="false && routeSteps.length" class="sidebar right-sidebar">
        <div class="sidebar-content">
          <section class="timeline-section">
            <h3 class="group-title">📜 攀爬动作序列</h3>
            <div class="beta-editor-panel">
              <div class="field compact-field">
                <label>当前编辑肢体</label>
                <select v-model="betaEditor.selectedLimb">
                  <option value="" disabled>请选择左手/右手/左脚/右脚</option>
                  <option v-for="limb in limbOptions" :key="limb" :value="limb">{{ getLimbName(limb) }}</option>
                </select>
              </div>
              <div class="beta-editor-status" :class="{ active: isBetaEditorActive }">
                {{ isBetaEditorActive ? `待选点：${betaEditModeLabel}` : '点击动作卡片上的按钮开始编辑' }}
              </div>
              <button v-if="isBetaEditorActive" class="beta-editor-cancel" @click="cancelBetaEdit">取消编辑</button>
            </div>
            <div class="step-scroll-area">
              <div v-for="(m, idx) in routeSteps" :key="idx"
                   class="step-item"
                   :class="{ 
                     'is-active': idx === currentIndex, 
                     'is-top': m.is_top,
                      'is-start': m.step === 0,
                      'is-edit-target': betaEditor.targetIndex === idx
                   }"
                   @click="currentIndex = idx">
                <div class="step-indicator">
                   <div class="step-line"></div>
                   <div class="step-number">{{ m.step }}</div>
                </div>
                <div class="step-content">
                  <div class="step-meta">
                    <span class="limb-tag" :class="m.limb.toLowerCase()">{{ getLimbName(m.limb) }}</span>
                    <span class="hold-id">{{ m.hold_id }}</span>
                  </div>
                  <p class="intent" v-if="m.intent">{{ m.intent }}</p>
                  <p class="intent" v-else-if="m.step === 0">上墙起步</p>
                  <div class="step-actions">
                    <button @click.stop="startBetaEdit('edit', idx)">改</button>
                    <button @click.stop="startBetaEdit('insert-before', idx)">前插</button>
                    <button @click.stop="startBetaEdit('insert-after', idx)">后插</button>
                    <button class="danger" @click.stop="deleteBetaStep(idx)">删</button>
                  </div>
                </div>
                <div v-if="m.is_top" class="top-medal">🏆</div>
              </div>
            </div>
          </section>
        </div>
      </aside>

      <aside v-if="false" class="inspector-panel">
        <section class="config-group">
          <h3 class="group-title">🎛️ 岩板属性</h3>
          <div class="field">
            <label>岩板名称</label>
            <input v-model="currentBoard.route_name" @input="markUnsaved" />
          </div>
          <div class="input-row">
              <div class="field">
                <label>岩板规格</label>
                <select v-model="activeBoardPresetId" @change="applyBoardPreset(activeBoardPresetId)">
                  <option v-for="preset in boardPresets" :key="preset.id" :value="preset.id">{{ preset.label }}</option>
                </select>
              </div>
            <div class="field">
              <label>来源</label>
              <input :value="currentBoard.source_type || editorMode" disabled />
            </div>
            <div class="field">
              <label>可见性</label>
              <select v-model="currentBoard.visibility" @change="markUnsaved">
                <option value="private">私有</option>
                <option value="team">团队</option>
                <option value="public">公开</option>
              </select>
            </div>
          </div>
          <div class="field">
            <label>备注 / 定线说明</label>
            <textarea v-model="currentBoard.setter_commentary" @input="markUnsaved"></textarea>
          </div>
        </section>

        <section class="config-group">
          <h3 class="group-title">🧩 选中岩点</h3>
          <div v-if="!selectedHold" class="pool-empty-state">点击岩板上的岩点后可编辑参数。</div>
          <template v-else>
            <div class="selected-hold-id">{{ selectedHold.id }}</div>
            <div class="input-row">
              <div class="field">
                <label>类型</label>
                <select v-model="selectedHold.hold_type" @change="syncSelectedHoldType">
                  <option v-for="type in holdTypes" :key="type" :value="type">{{ type }}</option>
                </select>
              </div>
              <div class="field">
                <label>形状</label>
                <input v-model="selectedHold.variant" @input="markUnsaved" />
              </div>
            </div>
            <div class="field">
              <label>旋转：{{ Number(selectedHold.rotation || 0).toFixed(0) }}°</label>
              <input type="range" min="0" max="360" step="5" v-model.number="selectedHold.rotation" @input="markUnsaved" />
            </div>
            <div class="field">
              <label>缩放：{{ Number(selectedHold.scale || 1).toFixed(1) }}x</label>
              <input type="range" min="0.5" max="2" step="0.1" v-model.number="selectedHold.scale" @input="markUnsaved" />
            </div>
            <div class="inspector-actions">
              <button @click="toggleSelectedStart">{{ selectedHold.is_start ? '取消起步点' : '设为起步点' }}</button>
              <button class="danger" @click="deletePlacedHold(selectedHold)">删除岩点</button>
            </div>
          </template>
        </section>
      </aside>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, reactive, watch } from 'vue'
import BoardTemplatePicker from './components/BoardTemplatePicker.vue'
import { useAuth } from './composables/useAuth'
import { createBlankBoard } from './composables/useBoardEditor'
import apiClient, { API_BASE_URL } from './services/apiClient'
import boardService from './services/boardService'
import {
  BOARD_TEMPLATES,
  DEFAULT_BOARD_TEMPLATE_ID,
  LEGACY_BOARD_TEMPLATE_ID,
  createAxisLabels,
  createBoardSpecSnapshot,
  getBoardTemplateById,
  normalizeBoardSpec,
} from './constants/boardTemplates'

// --- 基础状态 ---
const isSidebarOpen = ref(true) // 控制侧边栏显隐
const profile = ref({ height: 175, arm_span: 180, target_difficulty: 'V1', special_requirements: '' })
const holdTypes = ['Jug', 'Crimp', 'Sloper', 'Pinch', 'Pocket', 'Foot']

const { currentUser, login, logout } = useAuth()
const showLoginDialog = ref(false)
const loginForm = reactive({ email: '', name: '' })
const manualBoard = ref(createBlankBoard())
const unsavedChanges = ref(false)
const activeWorkspace = ref('dashboard')
const workspaceTabs = [
  { key: 'dashboard', label: '总览', icon: '📊', desc: '模拟状态与快捷入口' },
  { key: 'studio', label: '岩板设计', icon: '🧗', desc: '规格选择、布点与动作序列' },
  { key: 'library', label: '岩点资源', icon: '▦', desc: '上传与管理' },
  { key: 'boards', label: '岩板资产', icon: '🗂️', desc: '保存、载入与版本管理' },
  { key: 'ai-lab', label: 'AI 实验室', icon: '🔒', desc: '封印态与未来恢复位' },
]

const boardPresets = BOARD_TEMPLATES
const activeBoardPresetId = ref(DEFAULT_BOARD_TEMPLATE_ID)
const getBoardPresetById = getBoardTemplateById

const currentBoardSpec = computed(() => {
  const savedSpec = currentBoard.value?.board_spec
  const preset = getBoardPresetById(savedSpec?.preset_id || activeBoardPresetId.value)
  return savedSpec ? normalizeBoardSpec(savedSpec) : createBoardSpecSnapshot(preset)
})

const coordinateColumns = computed(() =>
  currentBoardSpec.value.xLabels?.length ? currentBoardSpec.value.xLabels : createAxisLabels(currentBoardSpec.value.columns)
)
const coordinateRows = computed(() =>
  currentBoardSpec.value.yLabels?.length
    ? currentBoardSpec.value.yLabels
    : Array.from({ length: currentBoardSpec.value.rows }, (_, index) => index + 1)
)
const boardFrameStyle = computed(() => ({
  width: `${currentBoardSpec.value.width}px`,
  height: `${currentBoardSpec.value.height}px`,
  maxWidth: `min(72vw, ${currentBoardSpec.value.width}px)`,
  maxHeight: 'calc(100vh - 310px)',
}))
const controlPanelStyle = computed(() => ({
  maxWidth: `${Math.min(currentBoardSpec.value.width, 760)}px`,
}))

const getColumnIndex = (label = 'A') => {
  const normalized = String(label).toUpperCase()
  return normalized.split('').reduce((total, char) => total * 26 + char.charCodeAt(0) - 64, 0) - 1
}

const getColumnLabel = (index = 0) => createAxisLabels(index + 1)[index]

const parseCoord = (coord = 'A1') => {
  const [, column = 'A', row = '1'] = String(coord).match(/^([A-Z]+)(\d+)$/i) || []
  return {
    column,
    row: Number(row),
    columnIndex: getColumnIndex(column),
  }
}

const syncCurrentBoardSpec = (preset = getBoardPresetById(activeBoardPresetId.value)) => {
  if (!currentBoard.value) return
  currentBoard.value.board_spec = createBoardSpecSnapshot(getBoardPresetById(preset.preset_id || preset.id || activeBoardPresetId.value))
}

const isHoldInsideSpec = (hold, spec = currentBoardSpec.value) => {
  const coord = parseCoord(hold.x && hold.y ? `${hold.x}${hold.y}` : (hold.id || 'A1'))
  const columnIndex = hold.x ? getColumnIndex(hold.x) : coord.columnIndex
  const rowIndex = Number(hold.y || coord.row || 1)
  return columnIndex >= 0 && columnIndex < spec.columns && rowIndex >= 1 && rowIndex <= spec.rows
}

const applyBoardPreset = (presetId) => {
  const preset = getBoardPresetById(presetId)
  activeBoardPresetId.value = preset.id
  if (!currentBoard.value) return

  const outOfRangeHolds = (currentBoard.value.placed_holds || []).filter((hold) => !isHoldInsideSpec(hold, preset))
  if (outOfRangeHolds.length > 0) {
    const shouldContinue = confirm(`当前有 ${outOfRangeHolds.length} 个岩点超出新岩板范围，切换规格会移除这些岩点及相关动作，是否继续？`)
    if (!shouldContinue) {
      activeBoardPresetId.value = currentBoard.value.board_spec?.preset_id || currentBoardSpec.value.preset_id
      return
    }
    const removedIds = new Set(outOfRangeHolds.map((hold) => hold.id))
    currentBoard.value.placed_holds = (currentBoard.value.placed_holds || []).filter((hold) => !removedIds.has(hold.id))
    currentBoard.value.beta_sequence = (currentBoard.value.beta_sequence || []).filter((step) => !removedIds.has(step.hold_id))
    selectedHold.value = null
    normalizeBetaSequence(currentIndex.value)
  }

  syncCurrentBoardSpec(preset)
  markUnsaved()
}

const handleLogin = async () => {
  await login(loginForm)
  showLoginDialog.value = false
}

const handleLogout = async () => {
  await logout()
}

const markUnsaved = () => {
  unsavedChanges.value = true
  if (currentBoard.value) {
    currentBoard.value.updated_at = new Date().toISOString()
  }
}

// --- 🌟 岩点图片映射 ---
const holdImageMap = reactive({})
const holdVectorMap = reactive({})

const fetchHoldMapping = async () => {
  try {
    const response = await apiClient.get('/api/holds/mapping');
    // 创建一个新的空对象，然后分配，以确保响应性
    const newMap = {};
    Object.assign(newMap, response.data);
    Object.keys(holdImageMap).forEach(key => delete holdImageMap[key]);
    Object.assign(holdImageMap, newMap);
  } catch (error) {
    console.error("无法加载岩点图片映射:", error);
  }
};

const fetchHoldVectors = async () => {
  try {
    const response = await apiClient.get('/api/holds/vectors');
    const newMap = {};
    Object.assign(newMap, response.data);
    Object.keys(holdVectorMap).forEach(key => delete holdVectorMap[key]);
    Object.assign(holdVectorMap, newMap);
  } catch (error) {
    console.error("无法加载岩点矢量映射:", error);
  }
};

const fetchAllHoldData = async () => {
  await fetchHoldMapping();
  await fetchHoldVectors();
}

fetchAllHoldData(); // 初始化时加载

const uploadInfo = reactive({
  hold_type: 'Jug',
  variant: '',
  file: null
});

const onFileChange = (e) => {
  uploadInfo.file = e.target.files[0];
};

const uploadImage = async () => {
  if (!uploadInfo.file || !uploadInfo.variant.trim()) {
    alert('请确保已选择文件并填写了变体名称。');
    return;
  }

  const formData = new FormData();
  formData.append('hold_type', uploadInfo.hold_type);
  formData.append('variant', uploadInfo.variant.trim());
  formData.append('file', uploadInfo.file);

  try {
    const response = await apiClient.post('/api/holds/upload', formData);
    if (response.data.success) {
      alert('上传成功!');
      await fetchAllHoldData(); // 重新加载所有数据
      // 清空上传表单
      uploadInfo.variant = '';
      uploadInfo.file = null;
      // 重置文件输入，以便可以再次选择相同的文件
      const fileInput = document.querySelector('input[type="file"]');
      if(fileInput) fileInput.value = '';

    } else {
      alert('上传失败。');
    }
  } catch (error) {
    console.error('上传处理失败:', error);
    alert(`上传失败: ${error.response?.data?.detail || error.message}`);
  }
};

const deleteHold = async (hold_type, variant) => {
  if (!confirm(`确定要删除岩点 '${hold_type} - ${variant}' 吗? 这个操作不可逆。`)) {
    return;
  }
  try {
    await apiClient.delete(`/api/holds/${hold_type}/${variant}`);
    alert('删除成功!');
    await fetchAllHoldData();
  } catch (error) {
    console.error('删除失败:', error);
    alert(`删除失败: ${error.response?.data?.detail || error.message}`);
  }
};

const getHoldImage = (hold) => {
  const type = hold.hold_type || hold.type;
  const typeMap = holdImageMap[type];
  if (!typeMap) return null;

  let imageUrl = typeMap[hold.variant];
  if (hold.variant === 'random' || !imageUrl) {
    const availableVariants = Object.keys(typeMap).filter(v => v !== 'default');
    imageUrl = typeMap['default'] || (availableVariants.length > 0 ? typeMap[availableVariants[0]] : null);
  }
  
  return imageUrl ? `${API_BASE_URL}${imageUrl}` : null;
}

const getHoldSvg = (hold) => {
  const type = hold.hold_type || hold.type;
  const typeMap = holdVectorMap[type];
  if (!typeMap) return null;
  
  let svgPath = typeMap[hold.variant];
  if (hold.variant === 'random' || !svgPath) {
    const availableVariants = Object.keys(typeMap).filter(v => v !== 'default');
    svgPath = typeMap['default'] || (availableVariants.length > 0 ? typeMap[availableVariants[0]] : null);
  }
  
  return svgPath;
}

const getHoldScale = (hold) => {
  // 在新模式下，每个岩点实例自带缩放属性
  const poolHold = holdPool.value.find(h => h.id === hold.id)
  return poolHold ? poolHold.scale : 1.0
}

// --- 购物车模式重构 ---
const holdPool = ref([]) // 岩点池，存放最终配置
const isBoardPoolOpen = ref(false)
const boardPoolSource = ref('board') // board | all
const boardPoolFilter = ref('All')
const boardPoolTypeFilters = computed(() => ['All', ...holdTypes])
const draftHold = reactive({ // 造物台，用于编辑单个岩点
  type: 'Jug',
  variant: 'random',
  scale: 1.0,
  rotation: 0
})
const previewMode = ref('vector'); // 'vector' or 'image'

const availableVariants = computed(() => {
  const imageVariants = holdImageMap[draftHold.type] ? Object.keys(holdImageMap[draftHold.type]) : [];
  const vectorVariants = holdVectorMap[draftHold.type] ? Object.keys(holdVectorMap[draftHold.type]) : [];
  // 合并并去重，同时过滤掉 'default'
  return [...new Set([...imageVariants, ...vectorVariants])].filter(v => v !== 'default');
});

watch(() => draftHold.type, (newType) => {
  const variantsForNewType = availableVariants.value;
  if (draftHold.variant !== 'random' && !variantsForNewType.includes(draftHold.variant)) {
    draftHold.variant = 'random';
  }
});

// 添加到岩点池
const addHoldToPool = () => {
  const newHold = {
    ...draftHold,
    id: Date.now() // 使用时间戳作为唯一ID
  }
  holdPool.value.push(newHold)
}

// 从岩点池移除
const removeHoldFromPool = (id) => {
  holdPool.value = holdPool.value.filter(hold => hold.id !== id)
}
// --- 重构结束 ---

const loading = ref(false)
const error = ref('')
const allRoutes = ref([])
const activeRouteIndex = ref(0)
const routeData = computed(() => allRoutes.value[activeRouteIndex.value] || null)
const savedBoards = ref([])
const taskId = ref(null)
const pollingTimer = ref(null)
const currentBoard = computed(() => routeData.value || manualBoard.value)
const editorMode = computed(() => routeData.value ? (routeData.value.source_type === 'manual' ? 'manual' : 'generated') : 'manual')
const editorModeLabel = computed(() => editorMode.value === 'manual' ? '模拟建板模式' : '历史 AI 结果模式')

// 🌟 核心修复：用 currentIndex 取代 currentStep，强制按数组绝对索引逐个播放！
const currentIndex = ref(0)
const currentReflectionMsg = ref('')

const reflectionMessages = [
  "正在初始化模拟设计工作台...",
  "分析当前岩板规格拓扑结构...",
  "准备岩点池与孔位映射...",
  "校验动作序列编辑状态...",
  "同步岩板资产草稿...",
  "当前版本 AI 定线保持封印...",
  "模拟岩板已就绪..."
]

let autoPlayTimer = null // 动画播放器

const pollForResult = async (id) => {
  pollingTimer.value = setInterval(async () => {
    try {
      const res = await apiClient.get(`/api/result/${id}`);
      if (res.data.status === 'RUNNING') {
        // continue polling
      } else {
        clearInterval(pollingTimer.value);
        loading.value = false;
        taskId.value = null;

        if (res.data.selected_routes && res.data.selected_routes.length > 0) {
          const generationHoldPoolSnapshot = JSON.parse(JSON.stringify(holdPool.value));
          allRoutes.value = res.data.selected_routes.map(route => ({
            ...route,
            source_type: 'ai-generated',
            visibility: route.visibility || 'private',
            tags: route.tags || [],
            owner_id: currentUser.value?.id || route.owner_id || null,
            source_hold_pool: generationHoldPoolSnapshot
          }));
          activeRouteIndex.value = 0;
          unsavedChanges.value = false;
          if (res.data.failure_suggestion) {
            error.value = res.data.failure_suggestion;
          }
        } else {
          allRoutes.value = [];
          error.value = res.data.failure_suggestion || '未能生成有效路线。';
        }
        
        let idx = 0
        autoPlayTimer = setInterval(() => {
          if (idx < maxIndex.value) { currentIndex.value = ++idx }
          else { clearInterval(autoPlayTimer) }
        }, 1000)
      }
    } catch (err) {
      clearInterval(pollingTimer.value);
      loading.value = false;
      taskId.value = null;
      error.value = err.response?.data?.detail || err.message;
    }
  }, 2000);
};

const generateRoute = async () => {
  notifyAiSealed()
}

const notifyAiSealed = () => {
  loading.value = false
  error.value = 'AI 定线功能已暂时封印：请使用岩板规格、岩点池和拖拽布点完成模拟设计。'
}

const cancelGeneration = async () => {
  if (!taskId.value) return;
  try {
    await apiClient.post(`/api/cancel/${taskId.value}`);
    clearInterval(pollingTimer.value);
    loading.value = false;
    error.value = "生成已取消。";
    taskId.value = null;
  } catch (err) {
    error.value = err.response?.data?.detail || "取消失败。";
  }
};

// --- 计算属性 ---
const managedHolds = computed(() => {
  const holds = [];
  const allTypes = new Set([...Object.keys(holdImageMap), ...Object.keys(holdVectorMap)]);
  allTypes.forEach((hold_type) => {
    const variants = new Set([
      ...Object.keys(holdImageMap[hold_type] || {}),
      ...Object.keys(holdVectorMap[hold_type] || {})
    ]);
    variants.forEach((variant) => {
      holds.push({
        key: `${hold_type}-${variant}`,
        hold_type,
        variant,
        imageUrl: holdImageMap[hold_type]?.[variant] ? `${API_BASE_URL}${holdImageMap[hold_type][variant]}` : null,
        svgPath: holdVectorMap[hold_type]?.[variant] || null
      });
    });
  });
  return holds.sort((a,b) => a.key.localeCompare(b.key));
});

const placedHolds = computed(() => currentBoard.value?.placed_holds || []);
const routeSteps = computed(() => currentBoard.value?.beta_sequence || []);

const normalizePoolHold = (hold, index = 0, source = 'board') => {
  const type = hold.hold_type || hold.type;
  const variant = hold.variant || 'default';
  return {
    key: `${source}-${type}-${variant}-${hold.rotation ?? 0}-${hold.scale ?? 1}-${index}`,
    type,
    hold_type: type,
    variant,
    rotation: Number(hold.rotation ?? 0),
    scale: Number(hold.scale ?? 1),
    count: Number(hold.count ?? 1),
    source
  };
}

const aggregateBoardPoolHolds = (holds, source = 'board') => {
  const grouped = new Map();
  holds.forEach((rawHold, index) => {
    const hold = normalizePoolHold(rawHold, index, source);
    const key = `${hold.type}-${hold.variant}-${hold.rotation}-${hold.scale}`;
    const existing = grouped.get(key);
    if (existing) {
      existing.count += 1;
    } else {
      grouped.set(key, {
        ...hold,
        key: `${source}-${key}`
      });
    }
  });
  return Array.from(grouped.values()).sort((a, b) => `${a.type}-${a.variant}`.localeCompare(`${b.type}-${b.variant}`));
}

const boardGeneratedHoldPool = computed(() => {
  const sourceHolds = routeData.value?.source_hold_pool?.length
    ? routeData.value.source_hold_pool
    : (holdPool.value.length ? holdPool.value : (placedHolds.value.length ? placedHolds.value : [draftHold]));
  return aggregateBoardPoolHolds(sourceHolds, 'board');
});

const allLibraryHoldPool = computed(() => managedHolds.value.map((hold, index) => ({
  key: `all-${hold.hold_type}-${hold.variant}-${index}`,
  type: hold.hold_type,
  hold_type: hold.hold_type,
  variant: hold.variant,
  rotation: 0,
  scale: 1,
  count: 1,
  source: 'all'
})));

const filteredBoardPoolHolds = computed(() => {
  const sourceList = boardPoolSource.value === 'board' ? boardGeneratedHoldPool.value : allLibraryHoldPool.value;
  if (boardPoolFilter.value === 'All') return sourceList;
  return sourceList.filter(hold => hold.type === boardPoolFilter.value);
});

// 计算剩余岩点 (Remaining Holds)
const remainingHolds = computed(() => {
  if (!holdPool.value.length) return [];
  const usedCounts = {};
  placedHolds.value.forEach(h => {
    const key = `${h.hold_type || h.type}-${h.variant}`;
    usedCounts[key] = (usedCounts[key] || 0) + 1;
  });

  const remaining = [];
  // 必须对副本进行操作，避免影响原始 holdPool 的响应性或在计算属性中产生副作用
  holdPool.value.forEach(p => {
    const key = `${p.type}-${p.variant}`;
    if (usedCounts[key] > 0) {
      usedCounts[key]--;
    } else {
      remaining.push(p);
    }
  });
  return remaining;
});

// 🌟 核心修复：最大帧数就是数组长度减一
const maxIndex = computed(() => Math.max(0, routeSteps.value.length - 1))

const isStart = (id) => placedHolds.value.some(h => h.id === id && h.is_start) || routeSteps.value.some(s => s.step === 0 && s.hold_id === id)
const isTop = (id) => routeSteps.value.some(s => s.is_top && s.hold_id === id)

// 🌟 核心修复：按数组切片 (slice) 截取肢体位置，并修正起步阶段显示
const currentLimbs = computed(() => {
  const limbs = {};
  const currentMove = routeSteps.value[currentIndex.value];

  if (currentMove && (currentMove.lh || currentMove.rh || currentMove.lf || currentMove.rf)) {
    if (currentMove.lh) limbs.LH = { id: currentMove.lh };
    if (currentMove.rh) limbs.RH = { id: currentMove.rh };
    if (currentMove.lf) limbs.LF = { id: currentMove.lf };
    if (currentMove.rf) limbs.RF = { id: currentMove.rf };
    return limbs;
  }

  // 修正逻辑：如果当前是起步动作 (step 0)，则显示所有起步点
  if (currentMove && currentMove.step === 0) {
    routeSteps.value.forEach(m => {
      if (m.step === 0) {
        limbs[m.limb] = { id: m.hold_id };
      }
    });
  } else {
    // 正常播放后续动作
    routeSteps.value.slice(0, currentIndex.value + 1).forEach(m => {
      limbs[m.limb] = { id: m.hold_id };
    });
  }
  
  return limbs;
});

const getCoord = (id) => {
  if (!id) return { left: '50%', bottom: '50%' }
  const { columnIndex, row } = parseCoord(id)
  const xIdx = columnIndex
  const yIdx = row - 1
  const maxX = Math.max(1, currentBoardSpec.value.columns - 1)
  const maxY = Math.max(1, currentBoardSpec.value.rows - 1)
  return { left: `${8 + (xIdx / maxX) * 84}%`, bottom: `${8 + (yIdx / maxY) * 84}%` }
}

const makeHoldAt = (coord, source = draftHold) => {
  const { column, row } = parseCoord(coord)
  const type = source.hold_type || source.type || 'Jug'
  return {
    id: coord,
    x: column,
    y: row,
    hold_type: type,
    type,
    variant: source.variant || 'random',
    rotation: Number(source.rotation ?? 0),
    scale: Number(source.scale ?? 1),
    is_start: false,
  }
}

const placeHoldOnCurrentBoard = (coord, source = draftHold) => {
  if (!currentBoard.value.placed_holds) currentBoard.value.placed_holds = []
  const exists = currentBoard.value.placed_holds.some((hold) => hold.id === coord)
  if (exists) {
    alert(`孔位 ${coord} 已有岩点，请先移动或删除原岩点。`)
    return null
  }
  const hold = makeHoldAt(coord, source)
  currentBoard.value.placed_holds.push(hold)
  selectedHold.value = hold
  markUnsaved()
  return hold
}

function placeDraftHoldAt(coord) {
  if (isBetaEditorActive.value) return
  placeHoldOnCurrentBoard(coord, draftHold)
}

function createNewBlankBoard(presetId = activeBoardPresetId.value) {
  if (unsavedChanges.value && !confirm('当前岩板有未保存修改，确定新建模拟岩板吗？')) return false
  const preset = getBoardPresetById(presetId)
  activeBoardPresetId.value = preset.id
  allRoutes.value = []
  activeRouteIndex.value = 0
  currentIndex.value = 0
  selectedHold.value = null
  manualBoard.value = createBlankBoard({
    route_name: `${preset.label} · 空白模拟岩板`,
    owner_id: currentUser.value?.id || null,
    source_type: 'manual',
    difficulty: '模拟设计',
    board_spec: createBoardSpecSnapshot(preset),
    setter_commentary: `使用 ${preset.label}（${preset.columns}×${preset.rows}）作为底层岩板进行手动模拟布点。`,
  })
  unsavedChanges.value = false
  return true
}

function startBoardFromPreset(presetId) {
  const previousPresetId = activeBoardPresetId.value
  activeBoardPresetId.value = presetId
  const created = createNewBlankBoard(presetId)
  if (created) {
    activeWorkspace.value = 'studio'
  } else {
    activeBoardPresetId.value = previousPresetId
  }
}

function startStudioWithBlankBoard() {
  if (createNewBlankBoard()) {
    activeWorkspace.value = 'studio'
  }
}

function clearCurrentBoard() {
  if (!currentBoard.value.placed_holds.length) return
  if (!confirm('确定清空当前岩板上的所有岩点和动作序列吗？')) return
  currentBoard.value.placed_holds = []
  currentBoard.value.beta_sequence = []
  selectedHold.value = null
  currentIndex.value = 0
  markUnsaved()
}

function syncSelectedHoldType() {
  if (!selectedHold.value) return
  selectedHold.value.type = selectedHold.value.hold_type
  markUnsaved()
}

function toggleSelectedStart() {
  if (!selectedHold.value) return
  selectedHold.value.is_start = !selectedHold.value.is_start
  markUnsaved()
}

const getShapeColor = (type) => ({ Jug: '#10b981', Crimp: '#ef4444', Sloper: '#f59e0b', Pinch: '#8b5cf6', Pocket: '#3b82f6', Foot: '#94a3b8' }[type] || '#10b981')
const getLimbName = (limb) => ({ LH: '左手', RH: '右手', LF: '左脚', RF: '右脚' }[limb] || limb)
const getLimbEmoji = (limb) => ({ LH: '✋', RH: '✋', LF: '🦶', RF: '🦶' }[limb] || limb)

// --- Beta Sequence Editor ---
const limbOptions = ['LH', 'RH', 'LF', 'RF']
const betaEditor = reactive({
  mode: null, // edit | insert-before | insert-after
  targetIndex: null,
  selectedLimb: 'LH'
})

const isBetaEditorActive = computed(() => Boolean(betaEditor.mode) && betaEditor.targetIndex !== null)
const betaEditModeLabel = computed(() => ({
  edit: '修改当前动作',
  'insert-before': '在当前动作前插入',
  'insert-after': '在当前动作后插入'
}[betaEditor.mode] || '编辑动作'))

function startBetaEdit(mode, index) {
  if (!currentBoard.value || index < 0 || index >= routeSteps.value.length) return
  betaEditor.mode = mode
  betaEditor.targetIndex = index
  betaEditor.selectedLimb = mode === 'edit' ? (routeSteps.value[index]?.limb || 'LH') : ''
  currentIndex.value = index
  if (autoPlayTimer) clearInterval(autoPlayTimer)
}

function cancelBetaEdit() {
  betaEditor.mode = null
  betaEditor.targetIndex = null
}

function createEditedStep(limb, holdId, fallbackIndex = 0) {
  return {
    step: fallbackIndex,
    limb,
    hold_id: holdId,
    intent: `人工编辑：${getLimbName(limb)}移动到 ${holdId}`,
    is_top: false,
    lh: null,
    rh: null,
    lf: null,
    rf: null,
  }
}

function normalizeBetaSequence(preferredIndex = currentIndex.value) {
  if (!currentBoard.value) return
  const sequence = currentBoard.value.beta_sequence || []
  const limbs = { LH: null, RH: null, LF: null, RF: null }

  sequence.forEach((step, index) => {
    const limb = limbOptions.includes(step.limb) ? step.limb : 'LH'
    step.step = index
    step.limb = limb
    step.is_top = sequence.length > 0 && index === sequence.length - 1
    limbs[limb] = step.hold_id
    step.lh = limbs.LH
    step.rh = limbs.RH
    step.lf = limbs.LF
    step.rf = limbs.RF
    if (!step.intent) {
      step.intent = index === 0 ? '上墙起步' : `${getLimbName(limb)}移动到 ${step.hold_id}`
    }
  })

  currentIndex.value = Math.max(0, Math.min(preferredIndex, Math.max(0, sequence.length - 1)))
}

function applyBetaEditToHold(hold) {
  if (!currentBoard.value || !isBetaEditorActive.value || !hold?.id) return
  if (!limbOptions.includes(betaEditor.selectedLimb)) {
    alert('请先选择要移动的四肢：左手、右手、左脚或右脚。')
    return
  }
  const sequence = currentBoard.value.beta_sequence || []
  const targetIndex = betaEditor.targetIndex
  const newStep = createEditedStep(betaEditor.selectedLimb, hold.id, targetIndex)

  if (betaEditor.mode === 'edit') {
    sequence.splice(targetIndex, 1, {
      ...sequence[targetIndex],
      ...newStep,
      intent: `人工修改：${getLimbName(betaEditor.selectedLimb)}改到 ${hold.id}`,
    })
    normalizeBetaSequence(targetIndex)
  } else {
    const insertIndex = betaEditor.mode === 'insert-before' ? targetIndex : targetIndex + 1
    sequence.splice(insertIndex, 0, newStep)
    normalizeBetaSequence(insertIndex)
  }

  cancelBetaEdit()
}

function deleteBetaStep(index) {
  if (!currentBoard.value || index < 0 || index >= routeSteps.value.length) return
  const step = routeSteps.value[index]
  if (!confirm(`确定删除动作 ${step.step}: ${getLimbName(step.limb)} -> ${step.hold_id} 吗？`)) return
  currentBoard.value.beta_sequence.splice(index, 1)
  normalizeBetaSequence(Math.min(index, currentBoard.value.beta_sequence.length - 1))
  cancelBetaEdit()
  markUnsaved()
}

// --- Interactive Editor ---
const selectedHold = ref(null);
const isFromTray = ref(false);
const interaction = reactive({ type: null, startX: 0, startY: 0, startRotation: 0, startScale: 0 });

function deletePlacedHold(hold) {
  if (!currentBoard.value || !hold) return;

  const holdId = hold.id;
  if (!confirm(`确定删除岩板上的点 ${holdId} 吗？`)) {
    return;
  }

  currentBoard.value.placed_holds = (currentBoard.value.placed_holds || []).filter(h => h.id !== holdId);

  currentBoard.value.beta_sequence = (currentBoard.value.beta_sequence || [])
    .filter(step => step.hold_id !== holdId)
    .map(step => ({
      ...step,
      lh: step.lh === holdId ? null : step.lh,
      rh: step.rh === holdId ? null : step.rh,
      lf: step.lf === holdId ? null : step.lf,
      rf: step.rf === holdId ? null : step.rf,
    }));

  normalizeBetaSequence(Math.min(currentIndex.value, currentBoard.value.beta_sequence.length - 1));

  if (selectedHold.value?.id === holdId) {
    selectedHold.value = null;
    interaction.type = null;
  }

  if (currentIndex.value > maxIndex.value) {
    currentIndex.value = maxIndex.value;
  }
  markUnsaved()
}

function onHoldMouseDown(event, hold, fromTray = false) {
  event.preventDefault();

  if (!fromTray && isBetaEditorActive.value) {
    applyBetaEditToHold(hold)
    return
  }
  
  if (fromTray) {
    if (!currentBoard.value) return;
    if (!Array.isArray(currentBoard.value.placed_holds)) {
      currentBoard.value.placed_holds = [];
    }
    // 从托盘拖拽，创建一个副本
    const newHold = {
      ...hold,
      id: `ADD_${Date.now()}`,
      hold_type: hold.type, 
      type: hold.type,
      variant: hold.variant,
      rotation: Number(hold.rotation ?? 0),
      scale: Number(hold.scale ?? 1),
      x: 'A', y: 1
    };
    currentBoard.value.placed_holds.push(newHold);
    selectedHold.value = newHold;
    isFromTray.value = true;
    markUnsaved()
  } else {
    selectedHold.value = hold;
    isFromTray.value = false;
  }
  
  if (event.ctrlKey) {
    interaction.type = 'rotate';
    interaction.startRotation = selectedHold.value.rotation;
  } else if (event.shiftKey) {
    interaction.type = 'scale';
    interaction.startScale = selectedHold.value.scale || 1.0;
  } else {
    interaction.type = 'drag';
  }
  
  interaction.startX = event.clientX;
  interaction.startY = event.clientY;
  
  window.addEventListener('mousemove', onMouseMove);
  window.addEventListener('mouseup', onMouseUp);
}

function onMouseMove(event) {
  if (!selectedHold.value || !interaction.type) return;
  
  const dx = event.clientX - interaction.startX;
  const dy = event.clientY - interaction.startY;

  if (interaction.type === 'rotate') {
    const newRotation = (interaction.startRotation + dx) % 360;
    selectedHold.value.rotation = newRotation < 0 ? 360 + newRotation : newRotation;
  } else if (interaction.type === 'scale') {
    const newScale = Math.max(0.5, Math.min(2.0, interaction.startScale + dy * 0.01));
    selectedHold.value.scale = newScale;
  } else if (interaction.type === 'drag') {
    const wallFrame = document.querySelector('.wall-frame');
    if (!wallFrame) return;
    const wallRect = wallFrame.getBoundingClientRect();
    const maxColumnIndex = currentBoardSpec.value.columns - 1;
    const maxRowIndex = currentBoardSpec.value.rows - 1;
    const xIdx = Math.round((((event.clientX - wallRect.left) / wallRect.width * 100 - 8) / 84) * maxColumnIndex);
    const yIdx = Math.round(((100 - (event.clientY - wallRect.top) / wallRect.height * 100 - 8) / 84) * maxRowIndex);

    const safeXIdx = Math.max(0, Math.min(maxColumnIndex, xIdx));
    const safeYIdx = Math.max(1, Math.min(currentBoardSpec.value.rows, yIdx + 1));
    const newX = getColumnLabel(safeXIdx);
    const newId = `${newX}${safeYIdx}`;
    
    if (selectedHold.value.id !== newId) {
      const oldId = selectedHold.value.id;
      selectedHold.value.id = newId;
      selectedHold.value.x = newX;
      selectedHold.value.y = safeYIdx;

      if (currentBoard.value) {
        currentBoard.value.beta_sequence.forEach(step => {
          if (step.hold_id === oldId) step.hold_id = newId;
        });
        normalizeBetaSequence(currentIndex.value);
      }
      markUnsaved()
    }
  }
}

function onMouseUp() {
  interaction.type = null;
  window.removeEventListener('mousemove', onMouseMove);
  window.removeEventListener('mouseup', onMouseUp);
}

// --- Persistence --- 
const fetchMyBoards = async () => {
    try {
        const response = await boardService.listBoards();
        savedBoards.value = response.data;
    } catch (error) {
        console.error("无法加载已保存的岩板:", error);
    }
};

const saveBoard = async () => {
    if (!currentBoard.value?.placed_holds?.length) return;
    const boardToSave = currentBoard.value;
    syncCurrentBoardSpec();
    boardToSave.owner_id = currentUser.value?.id || boardToSave.owner_id || null;
    boardToSave.updated_at = new Date().toISOString();
    normalizeBetaSequence(currentIndex.value);
    try {
        if (boardToSave.saved_id) {
            await boardService.updateBoard(boardToSave.saved_id, boardToSave);
            alert('岩板更新成功!');
        } else {
            const response = await boardService.createBoard(boardToSave);
            if (response.data?.saved_id) {
                boardToSave.saved_id = response.data.saved_id;
            }
            alert('岩板保存成功!');
        }
        unsavedChanges.value = false;
        await fetchMyBoards(); // Refresh saved boards list
    } catch (error) {
        console.error("无法保存岩板:", error);
        alert(`保存失败: ${error.response?.data?.detail || error.message}`);
    }
};

const renameSavedBoard = async (board) => {
    if (!board?.saved_id) {
        alert('该收藏岩板缺少 saved_id，无法重命名。请重新保存后重试。');
        return;
    }

    const originalName = board.route_name || '';
    const inputName = prompt('请输入新的路线名称：', originalName);

    if (inputName === null) {
        return;
    }

    const newName = inputName.trim();
    if (!newName) {
        alert('路线名称不能为空。');
        return;
    }

    if (newName === originalName.trim()) {
        return;
    }

    try {
        await boardService.updateBoard(board.saved_id, {
            route_name: newName,
        });

        savedBoards.value = savedBoards.value.map((b) =>
            b.saved_id === board.saved_id ? { ...b, route_name: newName } : b
        );

        if (routeData.value?.saved_id === board.saved_id) {
            const activeBoard = allRoutes.value[activeRouteIndex.value];
            if (activeBoard) {
                activeBoard.route_name = newName;
            }
        }

        alert('重命名成功!');
    } catch (error) {
        console.error("无法重命名收藏岩板:", error);
        alert(`重命名失败: ${error.response?.data?.detail || error.message}`);
    }
};

const deleteSavedBoard = async (board) => {
    if (!board?.saved_id) {
        alert('该收藏岩板缺少 saved_id，无法删除。请重新保存后重试。');
        return;
    }

    if (!confirm(`确定要删除收藏岩板「${board.route_name}」吗？`)) {
        return;
    }

    try {
        await boardService.deleteBoard(board.saved_id);
        savedBoards.value = savedBoards.value.filter(b => b.saved_id !== board.saved_id);

        // 如果当前展示的就是被删除的收藏岩板，则清空当前路线展示
        if (routeData.value?.saved_id === board.saved_id) {
            allRoutes.value = [];
            activeRouteIndex.value = 0;
            currentIndex.value = 0;
        }

        alert('删除成功!');
    } catch (error) {
        console.error("无法删除收藏岩板:", error);
        alert(`删除失败: ${error.response?.data?.detail || error.message}`);
    }
};

const loadSavedBoard = (board) => {
    // Create a deep copy to avoid modifying the saved list
    const boardCopy = JSON.parse(JSON.stringify(board));
    if (!boardCopy.board_spec) {
      boardCopy.board_spec = createBoardSpecSnapshot(getBoardPresetById(LEGACY_BOARD_TEMPLATE_ID));
    }
    boardCopy.board_spec = normalizeBoardSpec(boardCopy.board_spec);
    activeBoardPresetId.value = boardCopy.board_spec.preset_id || LEGACY_BOARD_TEMPLATE_ID;
    allRoutes.value = [boardCopy];
    activeRouteIndex.value = 0;
    currentIndex.value = 0;
    selectedHold.value = null;
    if (autoPlayTimer) clearInterval(autoPlayTimer);
};

// Fetch saved boards on initial load
fetchMyBoards();
</script>

<style scoped>
.symbiosis-app {
  height: 100vh; width: 100vw; background: #0f172a; color: #f8fafc;
  font-family: 'Inter', -apple-system, sans-serif; overflow: hidden;
}

.workspace-topbar {
  height: 72px;
  display: grid;
  grid-template-columns: minmax(280px, 360px) 1fr minmax(260px, 360px);
  align-items: center;
  gap: 18px;
  padding: 0 22px;
  background: rgba(15, 23, 42, 0.88);
  border-bottom: 1px solid rgba(59, 130, 246, 0.22);
  box-shadow: 0 12px 28px rgba(0,0,0,0.22);
  backdrop-filter: blur(14px);
}
.topbar-brand-block { display: flex; align-items: center; gap: 14px; }
.topbar-logo {
  width: 44px; height: 44px; display: grid; place-items: center;
  background: linear-gradient(135deg, #2563eb, #10b981);
  border-radius: 14px; box-shadow: 0 12px 26px rgba(37, 99, 235, 0.28);
  font-size: 1.35rem;
}
.topbar-kicker { color: #60a5fa; font-size: 0.72rem; font-weight: 800; letter-spacing: 1.6px; text-transform: uppercase; }
.topbar-brand-block h1 { margin: 2px 0 0; font-size: 1.15rem; letter-spacing: 0.5px; }
.topbar-center { display: flex; justify-content: center; gap: 10px; flex-wrap: wrap; }
.status-pill {
  border: 1px solid rgba(59, 130, 246, 0.38);
  background: rgba(37, 99, 235, 0.16);
  color: #dbeafe;
  padding: 7px 11px;
  border-radius: 999px;
  font-size: 0.76rem;
  font-weight: 800;
}
.status-pill.manual { border-color: rgba(16, 185, 129, 0.45); background: rgba(16, 185, 129, 0.16); color: #d1fae5; }
.status-pill.generated { border-color: rgba(245, 158, 11, 0.48); background: rgba(245, 158, 11, 0.16); color: #fef3c7; }
.status-pill.subtle { border-color: rgba(148, 163, 184, 0.2); background: rgba(30, 41, 59, 0.72); color: #cbd5e1; }
.user-entry { display: flex; justify-content: flex-end; align-items: center; gap: 10px; min-width: 0; }
.user-avatar {
  width: 34px; height: 34px; display: grid; place-items: center;
  border-radius: 50%; background: #3b82f6; color: white; font-weight: 900;
}
.user-meta { display: flex; flex-direction: column; min-width: 0; }
.user-meta strong { font-size: 0.82rem; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.user-meta span { color: #94a3b8; font-size: 0.68rem; }
.login-btn, .ghost-btn, .login-submit {
  border: none; border-radius: 10px; cursor: pointer; font-weight: 900;
}
.login-btn, .login-submit {
  padding: 10px 14px; color: #fff; background: linear-gradient(135deg, #2563eb, #7c3aed);
  box-shadow: 0 10px 22px rgba(37, 99, 235, 0.28);
}
.ghost-btn { padding: 8px 10px; background: #334155; color: #cbd5e1; }
.login-dialog-backdrop {
  position: fixed; inset: 0; z-index: 10000;
  background: rgba(2, 6, 23, 0.68);
  display: grid; place-items: center; backdrop-filter: blur(8px);
}
.login-dialog {
  width: 390px; padding: 22px;
  background: linear-gradient(180deg, #1e293b, #0f172a);
  border: 1px solid rgba(96, 165, 250, 0.32);
  border-radius: 22px;
  box-shadow: 0 32px 80px rgba(0,0,0,0.5);
}
.login-dialog-header { display: flex; justify-content: space-between; align-items: flex-start; gap: 16px; }
.login-dialog-header span { color: #60a5fa; font-size: 0.72rem; font-weight: 900; letter-spacing: 1.5px; text-transform: uppercase; }
.login-dialog-header h2 { margin: 4px 0 0; }
.login-dialog-header button { background: #334155; color: #cbd5e1; border: none; border-radius: 50%; width: 30px; height: 30px; cursor: pointer; }
.login-note { color: #94a3b8; font-size: 0.82rem; line-height: 1.6; }
.login-submit { width: 100%; margin-top: 8px; }

.main-layout { display: flex; height: calc(100% - 72px); position: relative; }

.workspace-switcher {
  height: 82px;
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  gap: 12px;
  padding: 12px 22px;
  background: linear-gradient(180deg, rgba(15, 23, 42, 0.94), rgba(2, 6, 23, 0.9));
  border-bottom: 1px solid rgba(96, 165, 250, 0.16);
  box-sizing: border-box;
}
.workspace-switcher button {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
  padding: 10px 12px;
  border: 1px solid rgba(148, 163, 184, 0.16);
  border-radius: 16px;
  background: rgba(30, 41, 59, 0.46);
  color: #cbd5e1;
  cursor: pointer;
  transition: all 0.2s ease;
  text-align: left;
}
.workspace-switcher button:hover {
  border-color: rgba(96, 165, 250, 0.48);
  transform: translateY(-1px);
  background: rgba(30, 41, 59, 0.72);
}
.workspace-switcher button.active {
  color: #fff;
  border-color: rgba(96, 165, 250, 0.75);
  background: linear-gradient(135deg, rgba(37, 99, 235, 0.92), rgba(14, 165, 233, 0.42));
  box-shadow: 0 14px 30px rgba(37, 99, 235, 0.22);
}
.tab-icon {
  width: 36px;
  height: 36px;
  display: grid;
  place-items: center;
  flex-shrink: 0;
  border-radius: 12px;
  background: rgba(255, 255, 255, 0.08);
  font-size: 1.1rem;
}
.tab-copy {
  display: flex;
  flex-direction: column;
  min-width: 0;
  line-height: 1.18;
}
.tab-copy strong { font-size: 0.86rem; }
.tab-copy small {
  margin-top: 4px;
  color: rgba(203, 213, 225, 0.7);
  font-size: 0.68rem;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.main-layout {
  height: calc(100% - 154px);
  background:
    radial-gradient(circle at 12% 10%, rgba(37, 99, 235, 0.16), transparent 28%),
    radial-gradient(circle at 90% 85%, rgba(245, 158, 11, 0.1), transparent 30%),
    #07111f;
}
.main-layout.workspace-dashboard {
  display: block;
  overflow-y: auto;
  padding: 24px;
  box-sizing: border-box;
}
.main-layout.workspace-dashboard > :not(.dashboard-workspace) { display: none !important; }
.main-layout.workspace-ai-lab {
  display: block;
  overflow-y: auto;
  padding: 24px;
  box-sizing: border-box;
}
.main-layout.workspace-ai-lab > :not(.ai-lab-workspace) { display: none !important; }
.main-layout.workspace-library,
.main-layout.workspace-boards {
  display: block;
  overflow-y: auto;
  padding: 24px;
  box-sizing: border-box;
}
.main-layout.workspace-studio {
  display: flex;
  overflow: hidden;
}
.main-layout.workspace-library .brand,
.main-layout.workspace-library .sidebar .config-group:not(.library-panel),
.main-layout.workspace-boards .library-panel,
.main-layout.workspace-boards .brand,
.main-layout.workspace-boards .sidebar .config-group:nth-of-type(2),
.main-layout.workspace-boards .sidebar .config-group:nth-of-type(4),
.main-layout.workspace-boards .actions {
  display: none;
}
.main-layout.workspace-library .stage,
.main-layout.workspace-library .inspector-panel,
.main-layout.workspace-library .right-sidebar,
.main-layout.workspace-boards .stage,
.main-layout.workspace-boards .inspector-panel,
.main-layout.workspace-boards .right-sidebar {
  display: none;
}
.main-layout.workspace-library .sidebar,
.main-layout.workspace-boards .sidebar {
  width: min(460px, 38vw);
  border-right: 1px solid rgba(96, 165, 250, 0.16);
  background: rgba(15, 23, 42, 0.88);
}
.main-layout.workspace-library .sidebar-content,
.main-layout.workspace-boards .sidebar-content { width: 100%; }
.main-layout.workspace-library .hold-library { max-height: calc(100vh - 310px); }
.dashboard-workspace {
  max-width: 1440px;
  margin: 0 auto;
}
.workspace-page {
  width: min(1440px, 100%);
  margin: 0 auto;
}
.workspace-page-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 24px;
  margin-bottom: 22px;
  padding: 28px;
  border: 1px solid rgba(96, 165, 250, 0.2);
  border-radius: 28px;
  background:
    radial-gradient(circle at 92% 8%, rgba(37, 99, 235, 0.22), transparent 26%),
    linear-gradient(135deg, rgba(15, 23, 42, 0.92), rgba(30, 41, 59, 0.74));
  box-shadow: 0 24px 70px rgba(0,0,0,0.26);
}
.workspace-page-header h2 {
  margin: 8px 0 8px;
  font-size: 2rem;
  color: #fff;
}
.workspace-page-header p,
.panel-title-row p {
  margin: 0;
  color: #94a3b8;
  line-height: 1.65;
}
.module-jump-actions,
.asset-actions,
.panel-title-row {
  display: flex;
  align-items: center;
  gap: 10px;
}
.module-jump-actions { flex-wrap: wrap; justify-content: flex-end; }
.module-jump-actions button,
.panel-title-row button,
.asset-actions button,
.asset-empty-card button {
  border: 1px solid rgba(148, 163, 184, 0.18);
  background: rgba(30, 41, 59, 0.82);
  color: #e2e8f0;
  border-radius: 12px;
  padding: 10px 13px;
  cursor: pointer;
  font-weight: 900;
  transition: all 0.18s ease;
}
.module-jump-actions button.primary,
.asset-actions button.primary,
.asset-empty-card button {
  border-color: transparent;
  background: linear-gradient(135deg, #2563eb, #0891b2);
  color: white;
}
.asset-actions button.danger {
  border-color: rgba(239, 68, 68, 0.35);
  background: rgba(127, 29, 29, 0.72);
  color: #fecaca;
}
.module-jump-actions button:hover,
.panel-title-row button:hover,
.asset-actions button:hover,
.asset-empty-card button:hover {
  transform: translateY(-1px);
  border-color: rgba(96, 165, 250, 0.56);
}
.workspace-panel {
  padding: 22px;
  border-radius: 24px;
  border: 1px solid rgba(148, 163, 184, 0.14);
  background: rgba(15, 23, 42, 0.78);
  box-shadow: 0 24px 70px rgba(0,0,0,0.24);
}
.library-layout-grid {
  display: grid;
  grid-template-columns: minmax(280px, 360px) 1fr;
  gap: 18px;
  align-items: start;
}
.resource-upload-panel {
  position: sticky;
  top: 0;
}
.resource-library-panel,
.boards-asset-panel {
  min-width: 0;
}
.panel-title-row {
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 14px;
}
.panel-title-row .group-title { margin-bottom: 8px; }
.workspace-library-list {
  max-height: none;
  min-height: 420px;
  margin-top: 0;
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(230px, 1fr));
  align-content: start;
}
.workspace-library-list .library-item {
  min-width: 0;
  border: 1px solid rgba(51, 65, 85, 0.84);
  border-radius: 14px;
}
.asset-card-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: 16px;
}
.asset-card {
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  min-height: 245px;
  border: 1px solid rgba(51, 65, 85, 0.9);
  border-radius: 20px;
  background: linear-gradient(180deg, rgba(30, 41, 59, 0.92), rgba(15, 23, 42, 0.94));
  overflow: hidden;
}
.asset-card-main {
  flex: 1;
  padding: 18px;
  cursor: pointer;
}
.asset-card-main:hover h3 { color: #93c5fd; }
.asset-kicker {
  color: #60a5fa;
  font-size: 0.7rem;
  font-weight: 900;
  letter-spacing: 1.4px;
  text-transform: uppercase;
}
.asset-card h3 {
  margin: 9px 0 8px;
  color: #f8fafc;
  font-size: 1.1rem;
}
.asset-card p {
  margin: 0;
  color: #94a3b8;
  font-size: 0.82rem;
  line-height: 1.55;
  display: -webkit-box;
  -webkit-line-clamp: 3;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.asset-meta-row {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 16px;
}
.asset-meta-row span {
  padding: 5px 8px;
  border-radius: 999px;
  background: rgba(37, 99, 235, 0.16);
  border: 1px solid rgba(96, 165, 250, 0.2);
  color: #bfdbfe;
  font-size: 0.7rem;
  font-weight: 800;
}
.asset-actions {
  justify-content: flex-end;
  padding: 12px;
  border-top: 1px solid rgba(51, 65, 85, 0.74);
  background: rgba(2, 6, 23, 0.28);
}
.asset-empty-card {
  min-height: 320px;
  display: grid;
  place-items: center;
  align-content: center;
  gap: 12px;
  text-align: center;
  border: 1px dashed rgba(96, 165, 250, 0.3);
  border-radius: 22px;
  background: rgba(15, 23, 42, 0.52);
}
.asset-empty-card strong { color: #f8fafc; font-size: 1.15rem; }
.asset-empty-card span { color: #94a3b8; }
.ai-lab-workspace {
  max-width: 1080px;
  min-height: 100%;
  display: grid;
  place-items: center;
  margin: 0 auto;
}
.ai-sealed-card {
  padding: 38px;
  border-radius: 32px;
  background:
    radial-gradient(circle at 85% 12%, rgba(245, 158, 11, 0.22), transparent 28%),
    linear-gradient(135deg, rgba(15, 23, 42, 0.96), rgba(30, 41, 59, 0.88));
  border: 1px solid rgba(245, 158, 11, 0.32);
  box-shadow: 0 36px 90px rgba(0,0,0,0.42);
}
.ai-sealed-card h2 {
  margin: 10px 0 12px;
  color: #fff;
  font-size: 2.2rem;
}
.ai-sealed-card p {
  margin: 0;
  color: #cbd5e1;
  line-height: 1.85;
  max-width: 880px;
}
.sealed-roadmap {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 14px;
  margin-top: 24px;
}
.sealed-roadmap div {
  padding: 16px;
  border-radius: 18px;
  background: rgba(15, 23, 42, 0.72);
  border: 1px solid rgba(148, 163, 184, 0.16);
}
.sealed-roadmap strong {
  display: block;
  margin-bottom: 8px;
  color: #fef3c7;
}
.sealed-roadmap span {
  color: #94a3b8;
  font-size: 0.8rem;
  line-height: 1.6;
}
.dashboard-hero-card {
  display: grid;
  grid-template-columns: 1.25fr 0.85fr;
  gap: 28px;
  padding: 34px;
  border-radius: 30px;
  background: linear-gradient(135deg, rgba(37, 99, 235, 0.25), rgba(15, 23, 42, 0.88) 48%, rgba(245, 158, 11, 0.13));
  border: 1px solid rgba(96, 165, 250, 0.24);
  box-shadow: 0 30px 90px rgba(0,0,0,0.34);
}
.section-kicker {
  color: #60a5fa;
  text-transform: uppercase;
  letter-spacing: 1.8px;
  font-weight: 900;
  font-size: 0.7rem;
}
.dashboard-hero-card h2 {
  margin: 10px 0 12px;
  font-size: 2rem;
  color: #fff;
}
.dashboard-hero-card p {
  margin: 0;
  max-width: 760px;
  color: #b6c4d6;
  line-height: 1.75;
}
.dashboard-actions { display: flex; gap: 12px; margin-top: 24px; }
.dashboard-actions button,
.quick-action-grid button {
  border: 1px solid rgba(148, 163, 184, 0.18);
  background: #111c2f;
  color: #e2e8f0;
  border-radius: 14px;
  padding: 12px 16px;
  cursor: pointer;
  font-weight: 900;
  transition: all 0.2s ease;
}
.dashboard-actions button.primary,
.quick-action-grid button:hover {
  background: linear-gradient(135deg, #2563eb, #0891b2);
  color: white;
  border-color: transparent;
}
.dashboard-actions button:hover,
.quick-action-grid button:hover { transform: translateY(-1px); }
.dashboard-metrics {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 14px;
}
.dashboard-metrics div,
.dashboard-card,
.dashboard-panel {
  background: rgba(15, 23, 42, 0.72);
  border: 1px solid rgba(148, 163, 184, 0.14);
  border-radius: 22px;
  box-shadow: 0 20px 55px rgba(0,0,0,0.22);
}
.dashboard-metrics div { padding: 18px; }
.dashboard-metrics strong {
  display: block;
  color: #fff;
  font-size: 2rem;
}
.dashboard-metrics span { color: #94a3b8; font-size: 0.78rem; }
.dashboard-card-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 16px;
  margin: 18px 0;
}
.dashboard-card { padding: 20px; }
.dashboard-card span { color: #94a3b8; font-size: 0.78rem; }
.dashboard-card strong { display: block; margin: 8px 0; color: #fff; font-size: 1.32rem; }
.dashboard-card small { color: #64748b; }
.dashboard-lower-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 18px;
}
.dashboard-panel { padding: 20px; }
.dashboard-panel h3 { margin: 0 0 14px; color: #f8fafc; }
.quick-action-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
.saved-board-item.premium { margin-bottom: 10px; border-radius: 14px; border: 1px solid rgba(148, 163, 184, 0.12); }

@media (max-width: 1180px) {
  .workspace-switcher { grid-template-columns: repeat(2, minmax(0, 1fr)); height: auto; }
  .main-layout { height: calc(100% - 72px - 176px); }
  .dashboard-hero-card,
  .dashboard-card-grid,
  .dashboard-lower-grid,
  .sealed-roadmap,
  .library-layout-grid { grid-template-columns: 1fr; }
  .workspace-page-header { flex-direction: column; }
  .module-jump-actions { justify-content: flex-start; }
  .resource-upload-panel { position: static; }
}

.sidebar {
  width: 350px; background: #1e293b;
  transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
  overflow-y: auto; overflow-x: hidden; position: relative;
  flex-shrink: 0;
}
.studio-tools-sidebar {
  border-right: 1px solid rgba(96, 165, 250, 0.18);
  background: rgba(15, 23, 42, 0.94);
}
.sidebar.left-sidebar { border-right: 1px solid #334155; }
.sidebar.right-sidebar { 
  width: 320px; 
  border-left: 1px solid #334155;
}
.sidebar.is-collapsed { width: 0; border-right: none; }

.sidebar-content { width: 350px; padding: 20px; box-sizing: border-box; }

.sidebar-toggle-btn {
  position: absolute; left: 350px; top: 50%; transform: translateY(-50%);
  z-index: 50; width: 24px; height: 48px; background: #1e293b; border: 1px solid #334155;
  border-left: none; border-radius: 0 8px 8px 0; color: #94a3b8; cursor: pointer;
  display: flex; align-items: center; justify-content: center; transition: all 0.3s ease;
}
.sidebar-toggle-btn:hover { background: #334155; color: white; }
.sidebar-toggle-btn.is-closed { left: 0; }

.brand { display: flex; gap: 12px; align-items: center; margin-bottom: 30px; }
.logo { font-size: 2rem; }
.titles h1 { font-size: 1rem; margin: 0; color: #f1f5f9; }
.titles p { font-size: 0.7rem; color: #94a3b8; margin: 0; }

.config-group { 
  background: rgba(15, 23, 42, 0.6); padding: 18px; border-radius: 12px; margin-bottom: 24px; 
  border: 1px solid rgba(51, 65, 85, 0.4);
}
.group-title { 
  font-size: 0.85rem; text-transform: uppercase; letter-spacing: 1.5px; color: #94a3b8; 
  margin-bottom: 16px; border-bottom: 2px solid #3b82f6; display: inline-block; padding-bottom: 4px;
}

.input-row { display: flex; gap: 12px; width: 100%; box-sizing: border-box; }
.field { display: flex; flex-direction: column; gap: 5px; margin-bottom: 10px; flex: 1; min-width: 0; }
.field label { font-size: 0.75rem; font-weight: bold; color: #94a3b8; }
.field input, .field select { 
  width: 100%; box-sizing: border-box;
  background: #1e293b; border: 1px solid #334155; color: white; 
  padding: 8px; border-radius: 6px; outline: none; font-size: 0.85rem;
}
.field textarea {
  width: 100%;
  min-height: 88px;
  resize: vertical;
  box-sizing: border-box;
  background: #1e293b;
  border: 1px solid #334155;
  color: white;
  padding: 9px;
  border-radius: 8px;
  outline: none;
  font-size: 0.85rem;
  line-height: 1.5;
}
.compact-studio-panel .input-row { gap: 8px; }
.selected-hold-id {
  display: inline-flex;
  align-items: center;
  margin-bottom: 12px;
  padding: 7px 10px;
  border-radius: 999px;
  background: rgba(245, 158, 11, 0.16);
  color: #fef3c7;
  border: 1px solid rgba(245, 158, 11, 0.35);
  font-weight: 900;
  font-family: monospace;
}
.inspector-actions {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}
.inspector-actions button {
  border: 1px solid rgba(96, 165, 250, 0.28);
  background: rgba(37, 99, 235, 0.18);
  color: #dbeafe;
  border-radius: 9px;
  padding: 8px 10px;
  cursor: pointer;
  font-weight: 800;
}
.inspector-actions button.danger {
  border-color: rgba(239, 68, 68, 0.35);
  background: rgba(127, 29, 29, 0.72);
  color: #fecaca;
}

.board-preset-summary,
.simulation-note {
  border-radius: 12px;
  padding: 12px;
  line-height: 1.55;
}
.board-preset-summary {
  display: flex;
  flex-direction: column;
  gap: 5px;
  background: rgba(37, 99, 235, 0.12);
  border: 1px solid rgba(96, 165, 250, 0.28);
  margin-bottom: 10px;
}
.board-preset-summary strong { color: #dbeafe; font-size: 0.92rem; }
.board-preset-summary span { color: #cbd5e1; font-size: 0.78rem; }
.board-preset-summary small { color: #93c5fd; font-size: 0.72rem; }
.simulation-note {
  background: rgba(245, 158, 11, 0.12);
  border: 1px dashed rgba(245, 158, 11, 0.42);
  color: #fde68a;
  font-size: 0.76rem;
}

/* --- 岩点池重构样式 --- */
.hold-creator-console {
  background: #0f172a;
  border-radius: 8px;
  padding: 16px;
  box-shadow: inset 0 2px 8px rgba(0,0,0,0.4);
}
.creator-grid {
  display: grid;
  grid-template-columns: 1fr 100px;
  gap: 20px;
  align-items: center;
}
.creator-controls {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.creator-preview-wrapper {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
}
.creator-preview {
  width: 100px;
  height: 100px;
  background: #1e293b;
  border: 1px dashed #334155;
  border-radius: 8px;
  display: flex;
  align-items: center;
  justify-content: center;
}
.preview-visual-large {
  width: 60px;
  height: 60px;
  display: flex;
  align-items: center;
  justify-content: center;
}
.preview-visual-large .no-preview-text {
  font-size: 0.7rem;
  color: #64748b;
}
.preview-toggle {
    display: flex;
    width: 100%;
    border: 1px solid #334155;
    border-radius: 6px;
    overflow: hidden;
}
.preview-toggle button {
    flex: 1;
    background: transparent;
    border: none;
    color: #94a3b8;
    padding: 4px;
    font-size: 0.7rem;
    cursor: pointer;
    transition: background 0.2s;
}
.preview-toggle button.active {
    background: #3b82f6;
    color: white;
    font-weight: bold;
}
.preview-visual-large .vector-svg,
.preview-visual-large .hold-image {
  width: 100%; height: 100%; object-fit: contain;
}

.add-to-pool-btn {
  width: 100%;
  margin-top: 16px;
  padding: 10px;
  background: #2563eb;
  color: white;
  border: none;
  border-radius: 6px;
  font-weight: bold;
  cursor: pointer;
  transition: background 0.2s;
}
.add-to-pool-btn:hover {
  background: #3b82f6;
}

.hold-pool-roster {
  max-height: 300px;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 8px;
  background: #0f172a;
  padding: 10px;
  border-radius: 8px;
  border: 1px solid #334155;
}
.pool-empty-state {
  text-align: center;
  color: #64748b;
  padding: 20px;
  font-size: 0.8rem;
}

.pool-item-card {
  display: flex;
  align-items: center;
  gap: 12px;
  background: #1e293b;
  padding: 8px;
  border-radius: 6px;
  border: 1px solid transparent;
  transition: all 0.2s ease;
}
.pool-item-card:hover {
  border-color: #3b82f6;
  background: #334155;
}

.pool-item-thumbnail {
  width: 40px;
  height: 40px;
  background: #0f172a;
  border-radius: 4px;
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  overflow: hidden;
}
.thumbnail-visual {
  width: 30px;
  height: 30px;
}
.thumbnail-visual .vector-svg,
.thumbnail-visual .hold-image {
  width: 100%; height: 100%; object-fit: contain;
}

.pool-item-info {
  flex-grow: 1;
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.info-type {
  font-size: 0.8rem;
  font-weight: bold;
  color: #f1f5f9;
}
.info-params {
  font-size: 0.7rem;
  color: #94a3b8;
  font-family: monospace;
}

.pool-item-remove-btn {
  width: 24px;
  height: 24px;
  background: #ef4444;
  color: white;
  border: none;
  border-radius: 50%;
  cursor: pointer;
  flex-shrink: 0;
  opacity: 0.5;
  transition: all 0.2s;
}
.pool-item-card:hover .pool-item-remove-btn {
  opacity: 1;
}
.pool-item-remove-btn:hover {
  background: #dc2626;
  transform: scale(1.1);
}

/* --- 岩板旁快捷岩点池：独立于左侧配置池 --- */
.board-side-hold-pool {
  position: absolute;
  left: 24px;
  top: 96px;
  z-index: 120;
}
.board-pool-toggle {
  width: 58px;
  min-height: 74px;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 5px;
  background: linear-gradient(135deg, rgba(245, 158, 11, 0.95), rgba(217, 119, 6, 0.92));
  color: #fff7ed;
  border: 1px solid rgba(251, 191, 36, 0.7);
  border-radius: 16px;
  box-shadow: 0 14px 30px rgba(0,0,0,0.32), 0 0 24px rgba(245, 158, 11, 0.18);
  cursor: pointer;
  font-weight: 900;
  transition: transform 0.2s ease, filter 0.2s ease;
}
.board-pool-toggle span {
  writing-mode: vertical-rl;
  letter-spacing: 2px;
  font-size: 0.72rem;
}
.board-pool-toggle:hover {
  transform: translateY(-2px) scale(1.04);
  filter: brightness(1.08);
}
.board-pool-panel {
  width: 290px;
  max-height: calc(100vh - 190px);
  display: flex;
  flex-direction: column;
  gap: 12px;
  background: rgba(15, 23, 42, 0.94);
  border: 1px solid rgba(245, 158, 11, 0.45);
  border-radius: 18px;
  padding: 14px;
  box-shadow: 0 24px 50px rgba(0,0,0,0.45), inset 0 1px 0 rgba(255,255,255,0.06);
  backdrop-filter: blur(10px);
}
.board-pool-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 12px;
}
.board-pool-header h3 {
  margin: 0;
  font-size: 0.95rem;
  color: #fef3c7;
}
.board-pool-header p {
  margin: 4px 0 0;
  font-size: 0.72rem;
  color: #94a3b8;
}
.board-pool-close {
  width: 26px;
  height: 26px;
  border: none;
  border-radius: 50%;
  background: #334155;
  color: #cbd5e1;
  cursor: pointer;
  flex-shrink: 0;
}
.board-pool-close:hover { background: #ef4444; color: white; }
.board-pool-tabs {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 6px;
  background: #0f172a;
  border: 1px solid #334155;
  border-radius: 10px;
  padding: 4px;
}
.board-pool-tabs button,
.board-pool-filters button {
  border: none;
  border-radius: 8px;
  background: transparent;
  color: #94a3b8;
  cursor: pointer;
  transition: all 0.18s ease;
}
.board-pool-tabs button {
  padding: 8px 6px;
  font-size: 0.72rem;
  font-weight: 800;
}
.board-pool-tabs button.active {
  background: #f59e0b;
  color: #111827;
}
.board-pool-filters {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.board-pool-filters button {
  padding: 5px 8px;
  font-size: 0.7rem;
  border: 1px solid #334155;
  background: #1e293b;
}
.board-pool-filters button.active {
  background: rgba(59, 130, 246, 0.22);
  border-color: #3b82f6;
  color: #dbeafe;
}
.board-pool-list {
  display: grid;
  grid-template-columns: 1fr;
  gap: 8px;
  overflow-y: auto;
  padding-right: 4px;
}
.board-pool-list::-webkit-scrollbar { width: 6px; }
.board-pool-list::-webkit-scrollbar-thumb { background: #334155; border-radius: 999px; }
.board-pool-empty {
  color: #64748b;
  font-size: 0.78rem;
  text-align: center;
  line-height: 1.5;
  padding: 20px 12px;
  background: #0f172a;
  border: 1px dashed #334155;
  border-radius: 12px;
}
.board-pool-hold-card {
  display: grid;
  grid-template-columns: 44px 1fr auto;
  align-items: center;
  gap: 10px;
  min-height: 56px;
  padding: 8px;
  background: #1e293b;
  border: 1px solid rgba(51, 65, 85, 0.9);
  border-radius: 12px;
  cursor: grab;
  user-select: none;
  transition: transform 0.18s ease, border-color 0.18s ease, background 0.18s ease;
}
.board-pool-hold-card:hover {
  transform: translateX(3px);
  border-color: #f59e0b;
  background: #273449;
}
.board-pool-hold-card:active { cursor: grabbing; }
.board-pool-hold-thumb {
  width: 44px;
  height: 44px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: #0f172a;
  border-radius: 10px;
  overflow: hidden;
}
.board-pool-hold-thumb .hold-visual {
  width: 34px;
  height: 34px;
  display: flex;
  align-items: center;
  justify-content: center;
}
.board-pool-hold-info {
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.board-pool-hold-type {
  color: #f8fafc;
  font-weight: 900;
  font-size: 0.82rem;
}
.board-pool-hold-variant {
  color: #94a3b8;
  font-family: monospace;
  font-size: 0.68rem;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.board-pool-count {
  color: #fbbf24;
  font-weight: 900;
  font-size: 0.78rem;
}
/* --- 样式结束 --- */

.generate-btn {
  width: 100%; padding: 14px; background: linear-gradient(135deg, #3b82f6 0%, #2563eb 100%); 
  color: white; border: none; border-radius: 10px;
  font-weight: 800; font-size: 1rem; cursor: pointer; transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1); 
  margin-top: 10px; box-shadow: 0 4px 14px rgba(59, 130, 246, 0.4);
  text-transform: uppercase; letter-spacing: 1px;
}
.generate-btn:hover:not(:disabled) { 
  transform: translateY(-2px); 
  box-shadow: 0 6px 20px rgba(59, 130, 246, 0.6);
  filter: brightness(1.1);
}
.generate-btn:active:not(:disabled) { transform: translateY(0); }
.generate-btn:disabled { background: #475569; cursor: not-allowed; opacity: 0.6; box-shadow: none; }
.sealed-generate-btn,
.board-toolbar .sealed-tool {
  background: linear-gradient(135deg, #475569, #1e293b) !important;
  border: 1px solid rgba(148, 163, 184, 0.32) !important;
  color: #e2e8f0 !important;
  box-shadow: none !important;
}
.sealed-generate-btn:hover,
.board-toolbar .sealed-tool:hover {
  border-color: rgba(245, 158, 11, 0.65) !important;
  color: #fef3c7 !important;
}
.cancel-btn { background: #ef4444; }
.cancel-btn:hover:not(:disabled) { background: #dc2626; }

.upload-section { display: flex; flex-direction: column; gap: 12px; }
.upload-section input[type="file"] { font-size: 0.8rem; }
.upload-section input[type="text"] { margin-bottom: 0px; } /* 修正间距 */
.upload-section button {
  background: #3b82f6; color: white; border: none; padding: 10px; border-radius: 6px;
  font-weight: bold; cursor: pointer; transition: background 0.2s;
}
.upload-section button:hover:not(:disabled) { background: #2563eb; }
.upload-section button:disabled { background: #475569; cursor: not-allowed; }

.hold-library {
  margin-top: 20px;
  max-height: 250px;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 8px;
  background: #0f172a;
  padding: 10px;
  border-radius: 8px;
  border: 1px solid #334155;
}

.library-item {
  display: flex;
  align-items: center;
  gap: 12px;
  background: #1e293b;
  padding: 8px;
  border-radius: 6px;
}
.library-item-thumbnail {
  width: 32px; height: 32px; background: #0f172a; border-radius: 4px; flex-shrink: 0;
  display: flex; align-items: center; justify-content: center; overflow: hidden;
}
.library-item-thumbnail .thumbnail-visual { width: 26px; height: 26px; }
.library-item-thumbnail .vector-svg, .library-item-thumbnail .hold-image {
  width: 100%; height: 100%; object-fit: contain;
}
.library-item-info { flex-grow: 1; display: flex; flex-direction: column; gap: 2px; }
.info-type { font-size: 0.8rem; font-weight: bold; color: #f1f5f9; }
.info-variant { font-size: 0.7rem; color: #94a3b8; font-family: monospace; }

.library-item-delete-btn {
  width: 28px; height: 28px; background: #ef4444; color: white;
  border: none; border-radius: 50%; cursor: pointer; flex-shrink: 0;
  opacity: 0.6; transition: all 0.2s;
}
.library-item:hover .library-item-delete-btn { opacity: 1; }
.library-item-delete-btn:hover { background: #dc2626; transform: scale(1.1); }

/* 时间轴样式 */
.timeline-section { margin-top: 0; height: 100%; display: flex; flex-direction: column; }
.group-title { margin-top: 10px; }
.step-scroll-area { 
  flex-grow: 1; /* 占据剩余空间 */
  display: flex; flex-direction: column; gap: 10px; margin-top: 15px; 
  overflow-y: auto; padding-right: 10px;
  scrollbar-width: thin; scrollbar-color: #334155 transparent;
}
.step-scroll-area::-webkit-scrollbar { width: 6px; }
.step-scroll-area::-webkit-scrollbar-track { background: transparent; }
.step-scroll-area::-webkit-scrollbar-thumb { background: #334155; border-radius: 10px; }

.step-item { 
  display: flex; gap: 12px; background: #0f172a; padding: 14px; border-radius: 10px; 
  cursor: pointer; transition: all 0.2s ease; position: relative;
  border: 1px solid rgba(51, 65, 85, 0.5); opacity: 0.8;
}
.step-item:hover { background: #334155; transform: translateX(5px); }
.step-item.is-active { opacity: 1; border-color: #3b82f6; background: #334155; box-shadow: 0 4px 12px rgba(59, 130, 246, 0.2); }
.step-item.is-start { border-left: 4px solid #10b981; }
.step-item.is-top { border-left: 4px solid #ef4444; }
.step-item.is-edit-target { outline: 2px dashed #f59e0b; outline-offset: 2px; }

.beta-editor-panel {
  background: #0f172a;
  border: 1px solid #334155;
  border-radius: 10px;
  padding: 10px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.compact-field { margin-bottom: 0; }
.beta-editor-status {
  font-size: 0.75rem;
  color: #94a3b8;
  line-height: 1.4;
  padding: 6px 8px;
  border-radius: 6px;
  background: #1e293b;
}
.beta-editor-status.active {
  color: #fef3c7;
  background: rgba(245, 158, 11, 0.18);
  border: 1px solid rgba(245, 158, 11, 0.35);
}
.beta-editor-cancel {
  background: #475569;
  color: white;
  border: none;
  border-radius: 6px;
  padding: 6px 8px;
  cursor: pointer;
}
.step-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 8px;
}
.step-actions button {
  background: #334155;
  color: #cbd5e1;
  border: 1px solid #475569;
  border-radius: 5px;
  padding: 3px 6px;
  font-size: 0.7rem;
  cursor: pointer;
}
.step-actions button:hover { background: #3b82f6; color: white; }
.step-actions button.danger:hover { background: #ef4444; }

.step-indicator { display: flex; flex-direction: column; align-items: center; width: 20px; }
.step-line { width: 2px; height: 100%; background: #334155; position: absolute; left: 21px; top: 0; z-index: 1; }
.step-number { 
  width: 20px; height: 20px; background: #0f172a; border: 2px solid #475569; 
  border-radius: 50%; display: flex; align-items: center; justify-content: center; 
  font-size: 10px; font-weight: bold; color: #94a3b8; z-index: 2; position: relative;
}
.is-active .step-number { border-color: #3b82f6; color: #3b82f6; background: #1e293b; }

.step-content { flex: 1; }
.step-meta { display: flex; align-items: center; gap: 8px; margin-bottom: 4px; }
.limb-tag { 
  padding: 2px 8px; border-radius: 4px; font-size: 0.7rem; font-weight: 800; color: white;
  text-transform: uppercase;
}
.lh { background: #E91E63; }
.rh { background: #9C27B0; }
.lf { background: #3F51B5; }
.rf { background: #00BCD4; }

.hold-id { font-size: 0.85rem; font-weight: 800; color: #f1f5f9; }
.intent { font-size: 0.75rem; color: #94a3b8; margin: 0; line-height: 1.4; }
.top-medal { font-size: 1.2rem; }

/* 舞台样式 */
.stage { 
  flex: 1; display: flex; flex-direction: column; padding: 20px; 
  position: relative; overflow-y: auto; min-width: 0; /* 防止 flex item 溢出 */
}
.stage-header { display: flex; justify-content: center; text-align: center; align-items: flex-start; margin-bottom: 20px; gap: 20px; }

.board-toolbar {
  align-self: center;
  display: flex;
  flex-wrap: wrap;
  justify-content: center;
  gap: 10px;
  margin: -4px 0 14px;
  padding: 9px;
  background: rgba(15, 23, 42, 0.72);
  border: 1px solid rgba(51, 65, 85, 0.8);
  border-radius: 16px;
}
.board-toolbar button {
  border: 1px solid #334155;
  background: #1e293b;
  color: #cbd5e1;
  border-radius: 10px;
  padding: 9px 12px;
  font-size: 0.78rem;
  font-weight: 900;
  cursor: pointer;
  transition: all 0.18s ease;
}
.board-toolbar button:hover:not(:disabled) { transform: translateY(-1px); border-color: #60a5fa; color: #f8fafc; }
.board-toolbar button:disabled { opacity: 0.45; cursor: not-allowed; }
.board-toolbar .primary-tool { background: linear-gradient(135deg, #2563eb, #0891b2); color: white; border-color: transparent; }

.route-info { flex: 1; }
.route-info h2 { font-size: 1.8rem; margin: 0 0 15px 0; background: linear-gradient(90deg, #f8fafc, #3b82f6); -webkit-background-clip: text; -webkit-text-fill-color: transparent; font-weight: 800; }

.route-actions { display: flex; align-items: center; gap: 12px; margin-top: 12px; }
.route-switcher button { background: #334155; color: #94a3b8; border: none; padding: 8px 12px; border-radius: 6px; cursor: pointer; }
.route-switcher button.active { background: #3b82f6; color: white; font-weight: bold; }
.route-switcher button:disabled { background: #475569; cursor: not-allowed; }
.save-board-btn { background: #10b981; color: white; border: none; padding: 8px 12px; border-radius: 6px; cursor: pointer; font-weight: bold; }
.save-board-btn:disabled { background: #475569; cursor: not-allowed; }
.beta-edit-hint {
  font-size: 0.78rem;
  color: #fef3c7;
  background: rgba(245, 158, 11, 0.16);
  border: 1px solid rgba(245, 158, 11, 0.35);
  padding: 8px 10px;
  border-radius: 8px;
  line-height: 1.5;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}
.beta-edit-hint button {
  background: #ef4444;
  color: white;
  border: none;
  border-radius: 6px;
  padding: 5px 8px;
  cursor: pointer;
  font-size: 0.72rem;
  flex-shrink: 0;
}
.beta-edit-hint button:hover { background: #dc2626; }

.saved-boards-list { max-height: 200px; overflow-y: auto; display: flex; flex-direction: column; gap: 8px; }
.saved-board-item { background: #1e293b; padding: 10px; border-radius: 6px; cursor: pointer; transition: background 0.2s; display: flex; align-items: center; justify-content: space-between; gap: 10px; }
.saved-board-item:hover { background: #334155; }
.saved-board-info { min-width: 0; }
.saved-board-name { font-weight: bold; color: #f1f5f9; }
.saved-board-difficulty { font-size: 0.8rem; color: #94a3b8; }

.saved-board-actions { display: flex; gap: 6px; flex-shrink: 0; }
.saved-board-action-btn {
  width: 28px;
  height: 28px;
  border: none;
  border-radius: 50%;
  color: #fff;
  cursor: pointer;
  opacity: 0.7;
  transition: all 0.2s ease;
}

.saved-board-rename-btn { background: #3b82f6; }
.saved-board-rename-btn:hover { background: #2563eb; transform: scale(1.08); }

.saved-board-delete-btn { background: #ef4444; }
.saved-board-delete-btn:hover { background: #dc2626; transform: scale(1.08); }

.saved-board-item:hover .saved-board-action-btn { opacity: 1; }
.saved-board-delete-btn:hover { background: #dc2626; transform: scale(1.08); }

.commentary-card {
  background: rgba(30, 41, 59, 0.5); border: 1px solid rgba(51, 65, 85, 0.5); border-left: 4px solid #3b82f6;
  padding: 15px 20px; border-radius: 0 12px 12px 0; position: relative; max-width: 600px; margin: 0 auto;
}
.quote-icon { position: absolute; top: -10px; left: 10px; font-size: 3rem; color: #3b82f6; opacity: 0.2; font-family: serif; }
.commentary-card p { margin: 0; font-size: 0.95rem; line-height: 1.6; color: #cbd5e1; font-style: italic; }

.controls {
  background: #1e293b; padding: 15px 20px; border-radius: 16px; border: 1px solid #334155;
  width: 100%;
  display: flex; flex-direction: column; gap: 12px; box-shadow: 0 10px 25px rgba(0,0,0,0.2);
  margin-top: 20px; /* 与岩板间距 */
}
.control-labels { display: flex; justify-content: space-between; align-items: center; }
.step-counter { font-size: 0.85rem; color: #94a3b8; font-weight: 600; }
.difficulty-tag { background: #3b82f6; color: white; padding: 2px 8px; border-radius: 4px; font-size: 0.75rem; font-weight: bold; }

.modern-slider {
  -webkit-appearance: none; width: 100%; height: 6px; background: #0f172a; border-radius: 3px; outline: none;
}
.modern-slider::-webkit-slider-thumb {
  -webkit-appearance: none; width: 18px; height: 18px; background: #3b82f6; border-radius: 50%; cursor: pointer; border: 3px solid #1e293b; transition: 0.2s;
}
.modern-slider::-webkit-slider-thumb:hover { transform: scale(1.2); box-shadow: 0 0 15px rgba(59, 130, 246, 0.5); }

.wall-display { 
  flex: 1; display: flex; flex-direction: column; 
  justify-content: center; align-items: center; padding: 0;
}
.wall-frame {
  width: auto; height: auto; flex-shrink: 0; /* 实际尺寸由 boardFrameStyle 根据模板动态控制 */
  background: #2a1e12; /* 木纹底色 */
  background-image: 
    repeating-linear-gradient(45deg, rgba(0,0,0,0.05) 0px, rgba(0,0,0,0.05) 2px, transparent 2px, transparent 10px),
    radial-gradient(circle at 50% 50%, #3d2b1f 0%, #2a1e12 100%);
  border-radius: 15px; position: relative;
  box-shadow: 0 20px 50px rgba(0,0,0,0.5), inset 0 0 60px rgba(0,0,0,0.3); 
  border: 12px solid #1a120b;
}
.wall-frame.skin-wood-classic {
  background-image:
    repeating-linear-gradient(45deg, rgba(0,0,0,0.05) 0px, rgba(0,0,0,0.05) 2px, transparent 2px, transparent 10px),
    radial-gradient(circle at 50% 50%, #3d2b1f 0%, #2a1e12 100%);
}
.wall-frame.skin-birch-studio {
  background: #6b4a2f;
  background-image:
    linear-gradient(90deg, rgba(255,255,255,0.06) 0 1px, transparent 1px 46px),
    repeating-linear-gradient(6deg, rgba(245, 222, 179, 0.08) 0px, rgba(245, 222, 179, 0.08) 8px, transparent 8px, transparent 18px),
    radial-gradient(circle at 50% 35%, #8b623d 0%, #4b321f 100%);
  border-color: #27180e;
}
.wall-frame.skin-commercial-dark {
  background: #1f2937;
  background-image:
    radial-gradient(circle at 20% 20%, rgba(148, 163, 184, 0.16), transparent 18%),
    repeating-linear-gradient(135deg, rgba(255,255,255,0.035) 0px, rgba(255,255,255,0.035) 3px, transparent 3px, transparent 14px),
    linear-gradient(180deg, #374151, #111827);
  border-color: #020617;
}
.wall-frame.skin-competition-blue {
  background: #1e3a5f;
  background-image:
    radial-gradient(circle at 75% 18%, rgba(56, 189, 248, 0.25), transparent 26%),
    radial-gradient(circle at 15% 80%, rgba(14, 165, 233, 0.18), transparent 28%),
    repeating-linear-gradient(90deg, rgba(255,255,255,0.04) 0 2px, transparent 2px 18px),
    linear-gradient(180deg, #315b86, #172554);
  border-color: #0f172a;
}
.wall-frame.is-empty-board { box-shadow: 0 20px 50px rgba(0,0,0,0.5), inset 0 0 0 2px rgba(16, 185, 129, 0.18), inset 0 0 60px rgba(0,0,0,0.3); }
.blank-board-hint {
  position: absolute;
  left: 50%; top: 50%; transform: translate(-50%, -50%);
  z-index: 2;
  width: 260px;
  text-align: center;
  padding: 18px;
  background: rgba(15, 23, 42, 0.74);
  border: 1px dashed rgba(16, 185, 129, 0.55);
  border-radius: 18px;
  color: #d1fae5;
  pointer-events: none;
  backdrop-filter: blur(6px);
}
.blank-board-hint strong { display: block; margin-bottom: 8px; font-size: 1rem; }
.blank-board-hint span { color: #a7f3d0; font-size: 0.78rem; line-height: 1.55; }

/* 坐标轴样式 */
.axis-x, .axis-y {
  position: absolute; color: #846345; font-size: 10px; font-weight: bold; font-family: monospace;
}
.axis-x { bottom: -25px; left: 8%; right: 8%; display: flex; justify-content: space-between; }
.axis-y { left: -25px; bottom: 8%; top: 8%; display: flex; flex-direction: column-reverse; justify-content: space-between; }

.hole { 
  position: absolute; width: 8px; height: 8px; 
  background: #1a120b; border-radius: 50%; transform: translate(-50%, 50%); 
  box-shadow: inset 0 2px 4px rgba(0,0,0,0.8), 0 1px 1px rgba(255,255,255,0.1);
  cursor: copy;
  transition: background 0.15s ease, box-shadow 0.15s ease, width 0.15s ease, height 0.15s ease;
}
.hole:hover { width: 13px; height: 13px; background: #10b981; box-shadow: 0 0 16px rgba(16,185,129,0.85); }

.hold-entity { 
  position: absolute; transform: translate(-50%, 50%); z-index: 10; 
  cursor: help; transition: all 0.3s cubic-bezier(0.175, 0.885, 0.32, 1.275);
}
.hold-entity:hover { transform: translate(-50%, 50%) scale(1.3); z-index: 100; }
.hold-entity.is-selected { transform: translate(-50%, 50%) scale(1.3); z-index: 101; box-shadow: 0 0 20px #fef08a; border-radius: 50%; }
.hold-entity.is-beta-pick-target { cursor: crosshair; }
.hold-entity.is-beta-pick-target::before {
  content: '';
  position: absolute;
  inset: -14px;
  border: 2px dashed rgba(245, 158, 11, 0.8);
  border-radius: 50%;
  animation: circle-pulse 1.2s infinite;
  pointer-events: none;
}

.hold-image-container {
  width: 42px; height: 42px; display: flex; align-items: center; justify-content: center;
}
.hold-image {
  max-width: 100%; max-height: 100%; object-fit: contain; filter: drop-shadow(0 4px 6px rgba(0,0,0,0.5));
}

.hold-vector-container {
  width: 42px; height: 42px;
}
.vector-svg {
  width: 100%; height: 100%;
  filter: drop-shadow(3px 5px 5px rgba(0,0,0,0.5));
}

.hold-tooltip {
  position: absolute; bottom: 110%; left: 50%; transform: translateX(-50%) translateY(10px);
  background: rgba(15, 23, 42, 0.95); border: 1px solid #3b82f6; padding: 10px 14px; border-radius: 8px;
  font-size: 0.75rem; white-space: nowrap; opacity: 0; pointer-events: none;
  transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
  box-shadow: 0 10px 20px rgba(0,0,0,0.6); backdrop-filter: blur(4px);
  z-index: 1000;
}
.hold-entity:hover .hold-tooltip { opacity: 1; transform: translateX(-50%) translateY(0); }
.tooltip-row { margin-bottom: 2px; }
.tooltip-row .label { color: #64748b; font-weight: bold; margin-right: 4px; }

.geometric-shape { 
  width: 32px; height: 32px; background: currentColor; 
  box-shadow: 
    inset -4px -4px 8px rgba(0,0,0,0.4),
    inset 4px 4px 8px rgba(255,255,255,0.3),
    0 8px 15px rgba(0,0,0,0.4);
  opacity: 0.95; 
  display: flex; align-items: center; justify-content: center;
  position: relative;
}
.inner-shadow { position: absolute; inset: 0; background: radial-gradient(circle at 30% 30%, transparent 50%, rgba(0,0,0,0.2) 100%); pointer-events: none; }
.bolt-hole { width: 6px; height: 6px; background: #1a120b; border-radius: 50%; box-shadow: inset 0 1px 2px black; opacity: 0.6; }

.jug { border-radius: 35% 65% 65% 35% / 30% 30% 70% 70%; width: 38px; height: 32px; }
.crimp { height: 12px; width: 34px; border-radius: 4px; }
.sloper { border-radius: 50%; width: 40px; height: 40px; filter: contrast(1.1); }
.pinch { width: 14px; height: 36px; border-radius: 8px; }
.pocket { border-radius: 50%; background: transparent !important; border: 8px solid currentColor; box-shadow: 0 5px 10px rgba(0,0,0,0.3); }
.pocket .bolt-hole { display: none; }
.foot { width: 16px; height: 16px; clip-path: polygon(50% 0, 100% 50%, 50% 100%, 0 50%); }

.start-glow::after { content: ''; position: absolute; width: 60px; height: 60px; border: 3px solid #10b981; border-radius: 50%; top:-14px; left:-14px; animation: circle-pulse 2s infinite; box-shadow: 0 0 20px #10b981; pointer-events: none; }
.top-glow::after { content: ''; position: absolute; width: 60px; height: 60px; border: 3px solid #ef4444; border-radius: 50%; top:-14px; left:-14px; animation: circle-pulse 2s infinite; box-shadow: 0 0 20px #ef4444; pointer-events: none; }

@keyframes circle-pulse {
  0% { transform: scale(0.8); opacity: 0.8; }
  50% { transform: scale(1.1); opacity: 0.4; }
  100% { transform: scale(0.8); opacity: 0.8; }
}

@keyframes rotate { 100% { transform: rotate(360deg); } }

/* 🌟 核心修复：独立、鲜艳的四肢游标设计，拒绝黏连 */
.limb-cursor {
  position: absolute; width: 32px; height: 32px; border-radius: 50%; z-index: 20;
  display: flex; align-items: center; justify-content: center; font-size: 16px;
  transform: translate(-50%, 50%); 
  box-shadow: 0 5px 15px rgba(0,0,0,0.4); 
  border: 3px solid white; 
  transition: all 0.6s cubic-bezier(0.34, 1.56, 0.64, 1);
}
.limb-icon { filter: drop-shadow(0 2px 2px rgba(0,0,0,0.3)); }
.lh { background-color: #E91E63; color: white; } 
.rh { background-color: #9C27B0; color: white; } 
.lf { background-color: #3F51B5; color: white; } 
.rf { background-color: #00BCD4; color: white; }

.loading-overlay {
  position: fixed; inset: 0; background: rgba(15, 23, 42, 0.85); z-index: 9999;
  display: flex; justify-content: center; align-items: center; backdrop-filter: blur(5px);
}
.loading-content { text-align: center; }
.progress-circle { position: relative; width: 100px; height: 100px; margin: 0 auto 20px auto; }
.progress-circle svg { transform: rotate(-90deg); width: 100px; height: 100px;}
.progress-circle circle { fill: none; stroke-width: 6; }
.progress-circle .bg { stroke: #334155; }
.progress-circle .pulse { stroke: #3b82f6; stroke-dasharray: 283; stroke-dashoffset: 200; animation: spin-circle 1.5s linear infinite; }
.agent-avatar { position: absolute; inset: 0; display: flex; align-items: center; justify-content: center; font-weight: 900; font-size: 1.2rem; color: #3b82f6; }

@keyframes spin-circle { 0% { stroke-dashoffset: 283; } 100% { stroke-dashoffset: -283; } }
.reflection-log { color: #94a3b8; font-family: monospace; font-size: 0.9rem; }
.animate-pulse { animation: pulse 1.5s infinite; }
@keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.5; } }
</style>