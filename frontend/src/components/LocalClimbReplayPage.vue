<template>
  <section class="replay-page" :class="{ 'is-reviewing': reviewResult && !result, 'review-is-zoomed':reviewZoom>1 }" :style="reviewWorkbenchStyle" aria-labelledby="replay-title">
    <header class="replay-heading">
      <div>
        <h1 id="replay-title">AI 复盘</h1>
      </div>
      <nav class="replay-heading-actions" aria-label="复盘资料"><button type="button" @click="historyOpen=true">最近分析<span v-if="recentJobs.length"> · {{recentJobs.length}}</span></button></nav>
    </header>

    <div class="replay-workspace" :class="{ 'review-mode': reviewResult, 'is-empty': !selectedFile && !activeJob }">
      <div class="video-column">
        <div v-if="activeJob && (!reviewResult || result && !holdRepairOpen)" class="replay-record-toolbar">
          <span class="replay-record-name" :title="activeJob.original_name">{{ activeJob.original_name || '当前复盘记录' }}</span>
          <button v-if="result" type="button" @click="returnToStart"><ArrowLeft aria-hidden="true" />返回</button>
          <button type="button" class="delete-record-button" aria-label="删除整次记录" title="删除整次记录" :disabled="isDeleting || isJobDeleting" @click="deleteEntireReplay"><Delete aria-hidden="true" />{{ isJobDeleting ? '正在删除…' : '删除' }}</button>
        </div>
        <UnifiedReplayPlayer v-if="result && activeJob && !isJobDeleting" v-show="!holdRepairOpen" ref="unifiedPlayer" :key="`${activeJob.id}:${routeMapPlayerVersion}`" :job="activeJob" :legacy-url="replayVideoUrl" :fallback-actions="actionEvents" />
        <template v-if="!result && !selectedFile && !playbackUrl">
        <div
          v-if="!isBusy"
          class="video-drop"
          :class="{ dragging: isDragging }"
          role="button"
          tabindex="0"
          @click="openPicker"
          @keydown.enter="openPicker"
          @keydown.space.prevent="openPicker"
          @dragenter.prevent="isDragging = true"
          @dragover.prevent="isDragging = true"
          @dragleave.prevent="isDragging = false"
          @drop.prevent="onDrop"
        >
          <strong>导入视频</strong>
          <span>常见视频格式 · 最大 500 MB</span>
          <span class="upload-action">选择视频</span>
        </div>

        </template>

        <div v-if="reviewResult && !result" class="player-tools">
          <div class="review-filebar">
            <button type="button" class="review-file-trigger" :popovertarget="reviewMenuId" :aria-expanded="reviewMenuOpen" aria-label="视频与资料" :title="activeJob.original_name" @click="positionReviewMenu"><VideoCamera aria-hidden="true" /><span>{{activeJob.original_name || '当前复盘记录'}}</span><ArrowDown aria-hidden="true" /></button>
            <div class="review-display-tools">
              <div class="review-view-tools" role="group" aria-label="视频缩放与平移">
                <select aria-label="视频放大倍数" :value="reviewZoom" :disabled="holdReviewSaving || holdPreviewLoading" @change="setReviewZoom(Number($event.target.value))"><option v-for="n in [1,2,4,8]" :key="n" :value="n">{{ n }}×</option></select>
                <button type="button" aria-label="平移放大画面" title="平移放大画面；再次点击返回编辑" :aria-pressed="reviewPanning" :disabled="reviewZoom === 1 || holdReviewSaving || holdPreviewLoading" @click="reviewPanning=!reviewPanning"><Rank aria-hidden="true" /></button>
              </div>
              <label v-if="playerMode === 'interactive'" class="review-layer-toggle" title="显示或隐藏岩点轮廓"><input v-model="showHolds" type="checkbox" aria-label="显示岩点轮廓" /><View v-if="showHolds" aria-hidden="true" /><Hide v-else aria-hidden="true" /></label>
              <button v-if="result" type="button" class="review-return" aria-label="返回复盘" title="返回复盘" @click="closeHoldRepair"><ArrowLeft aria-hidden="true" /></button>
            </div>
          </div>
          <div class="review-toolrail" role="group" aria-label="视频编辑工具">
            <button v-if="canAddHoldAtPoint" type="button" :disabled="holdReviewSaving || !!holdPreview" :aria-pressed="holdReviewMode && !reviewPanning" :aria-label="holdReviewMode ? '结束补删点' : '补删点'" title="拖框补点，点选岩点删除" @click="activateHoldReview"><Crop aria-hidden="true" /><span>补删点</span></button>
            <button type="button" :disabled="!canAddHoldAtPoint || editorBusy" aria-label="放大单帧／手绘轮廓" title="单帧精修" @click="openHoldEditor()"><EditPen aria-hidden="true" /><span>精修</span></button>
          </div>
          <details v-if="holdReviewMode && !holdPreview && !selectedHoldId" ref="holdCoordinateDetails" class="hold-coordinate-entry">
            <summary title="无法拖框时输入画面百分比范围">输入范围</summary>
            <form @submit.prevent="previewHoldFromFields">
              <label>左侧 <input ref="holdCoordinateFirstInput" v-model.number="holdRegionForm.left" type="number" min="0" max="100" step="1" required /></label>
              <label>顶部 <input v-model.number="holdRegionForm.top" type="number" min="0" max="100" step="1" required /></label>
              <label>右侧 <input v-model.number="holdRegionForm.right" type="number" min="0" max="100" step="1" required /></label>
              <label>底部 <input v-model.number="holdRegionForm.bottom" type="number" min="0" max="100" step="1" required /></label>
              <button type="submit" :disabled="holdPreviewLoading || holdReviewSaving">预览轮廓</button>
            </form>
          </details>
          <div :id="reviewMenuId" ref="reviewMenu" class="review-file-popover" popover="auto" :style="reviewMenuPosition" aria-label="视频与资料菜单" @toggle="reviewMenuOpen=$event.newState==='open'">
            <p class="review-menu-filename"><span>{{activeJob.original_name || '当前复盘记录'}}</span></p>
            <button type="button" @click="reviewAssetAction('replace')"><RefreshRight aria-hidden="true" />更换视频</button>
            <button type="button" @click="reviewAssetAction('history')"><Clock aria-hidden="true" />最近分析<span v-if="recentJobs.length" class="review-menu-count">{{recentJobs.length}}</span></button>
            <button type="button" @click="reviewAssetAction('versions')"><Document aria-hidden="true" />记录与版本</button>
            <template v-if="result">
              <div class="review-menu-divider" />
              <div class="playback-switch" role="group" aria-label="播放版本">
                <button type="button" :disabled="!replayVideoAvailable" :aria-pressed="playbackKind==='overlay'" @click="switchPlayback('overlay')">复盘视频</button>
                <button type="button" :disabled="!sourcePlayable" :aria-pressed="playbackKind==='source'" @click="switchPlayback('source')">原视频</button>
              </div>
              <label><input v-model="showPose" type="checkbox" />骨架</label>
              <label><input v-model="showEvents" type="checkbox" />接触事件</label>
              <button v-if="visualState.ready && replayVideoAvailable" type="button" @click="reviewAssetAction('replay')">查看线路回放</button>
              <a v-if="replayVideoAvailable && !visualState.stale" class="export-action" :href="replayDownloadUrl">导出复盘视频</a>
            </template>
            <div class="review-menu-divider" />
            <button type="button" class="review-menu-delete" aria-label="删除整次记录" :disabled="isDeleting || isJobDeleting" @click="reviewAssetAction('delete')"><Delete aria-hidden="true" />删除这条记录</button>
          </div>
        </div>
        <div v-if="(playbackUrl || selectedFile) && !result" class="playback-review" :class="{ 'has-action-focus': activeAction }">
          <div ref="videoStage" class="video-stage">
            <div ref="reviewViewport" class="review-media-viewport" :class="{ 'is-zoomed':reviewZoom>1 }" :data-zoom-animating="reviewZoomAnimating" :style="reviewViewportStyle" @wheel="handleReviewWheel" @pointerdown.capture="startReviewTouchPan" @pointermove.capture="moveReviewTouchPan" @pointerup.capture="endReviewTouchPan" @pointercancel.capture="endReviewTouchPan" @keydown.esc="holdPreview=null;selectedHoldId=''">
            <div class="video-canvas" :style="reviewMediaStyle">
              <video
                ref="videoElement"
                :src="playbackUrl || undefined"
                :controls="reviewZoom === 1"
                playsinline
                preload="auto"
                @loadstart="handlePlaybackLoading"
                @loadeddata="handlePlaybackReady"
                @canplay="handlePlaybackReady"
                @playing="handlePlaybackReady"
                @waiting="handlePlaybackLoading"
                @stalled="handlePlaybackStalled"
                @timeupdate="updatePlaybackEvidence"
                @loadedmetadata="handlePlaybackLoaded"
                @seeked="updatePlaybackEvidence"
                @error="handlePlaybackError"
              />
              <canvas
                v-if="colorPicking"
                ref="colorSampleCanvas"
                class="color-sample-canvas"
                role="button"
                tabindex="0"
                aria-label="在暂停的视频画面中点击目标线路岩点取色"
                @click="pickColorFromFrame"
                @keydown.esc="cancelColorPicking"
              />
              <div v-if="colorPicking" class="color-sample-hint">点击一个清晰、少反光的目标岩点取色</div>
              <div v-if="playerMode === 'interactive' && reviewResult" class="hold-overlay">
                <svg v-if="showHolds" class="hold-contours" viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true">
                  <g v-for="hold in reviewResult.holds || []" :key="hold.id">
                    <polygon v-if="holdPolygon(hold).length" :points="contourPoints(holdPolygon(hold))" :class="{ selected: String(hold.id) === selectedHoldId }" @click.stop="selectCanvasHold(hold)" />
                  </g>
                </svg>
                <button v-for="hold in showHolds ? (reviewResult.holds || []) : []" :key="`label-${hold.id}`" class="hold-marker" :class="{ 'missing-contour': !holdPolygon(hold).length }" :style="{left:`${holdLabelPosition(hold)[0]}%`,top:`${holdLabelPosition(hold)[1]}%`}" :aria-label="`选择岩点 ${hold.id}${holdPolygon(hold).length ? '' : '，缺少轮廓'}`" :disabled="holdReviewSaving || holdPreviewLoading || !!holdPreview" @click.stop="selectCanvasHold(hold)"><span>{{hold.id}}</span></button>
                <svg v-if="showPose && currentPose" class="pose-overlay" viewBox="0 0 100 100" preserveAspectRatio="none">
                  <line
                    v-for="segment in skeletonSegments"
                    :key="segment.key"
                    :x1="segment.x1"
                    :y1="segment.y1"
                    :x2="segment.x2"
                    :y2="segment.y2"
                    vector-effect="non-scaling-stroke"
                  />
                  <circle
                    v-for="point in posePoints"
                    :key="point.key"
                    :cx="point.x"
                    :cy="point.y"
                    r="0.75"
                    vector-effect="non-scaling-stroke"
                  />
                </svg>
                <ReplayTorsoCenter v-if="showPose && currentPose" :point="torsoCenter(currentPose)" :frame="torsoSourceFrame" />
                <div v-if="showEvents && activeContactEvents.length" class="contact-badges">
                  <span v-for="event in activeContactEvents" :key="event.key">{{ limbNames[event.limb] }} → 岩点 {{ event.hold_id }}</span>
                </div>
                <span v-if="showPose && currentPose" class="pose-evidence" :class="{ nearby: !currentPoseExact }">{{ poseEvidenceLabel }}</span>
                <svg v-if="holdPreview" class="hold-preview-outline" viewBox="0 0 100 100" preserveAspectRatio="none" aria-label="待确认的岩点轮廓">
                  <polygon :points="holdPreviewPoints" />
                </svg>
                <span v-if="holdDraw" class="hold-draft-box" :style="holdDrawStyle" aria-hidden="true" />
                <button
                  v-if="holdReviewMode && !holdPreview && !reviewPanning"
                  class="hold-draw-surface"
                  type="button"
                  :disabled="holdReviewSaving || holdPreviewLoading"
                  aria-label="在视频画面上拖出单个漏检岩点的大概范围"
                  @pointerdown="startHoldDraw"
                  @pointermove="moveHoldDraw"
                  @pointerup="finishHoldDraw"
                  @pointercancel="cancelHoldDraw"
                  @keydown.esc="cancelHoldDraw"
                  @keydown.enter.prevent="focusHoldCoordinateInputs"
                  @keydown.space.prevent="focusHoldCoordinateInputs"
                />
              </div>
            </div>
              <button v-if="reviewPanning && reviewZoom>1" type="button" class="review-pan-surface" aria-label="拖动平移放大画面" @pointerdown="startReviewPan" @pointermove="moveReviewPan" @pointerup="endReviewPan" @pointercancel="endReviewPan" @keydown="panReviewByKey" />
                <div v-if="holdPreview" ref="holdPreviewActions" class="canvas-hold-actions" :style="canvasActionsStyle" role="group" aria-label="候选岩点操作">
                  <span v-if="holdPreview.supporting_frames <= 1" class="missing-contour-note">仅单帧，请核对轮廓</span>
                  <button ref="holdConfirmationButton" type="button" aria-label="轮廓正确，确认补入" :disabled="holdReviewSaving || editorOpen" @click="confirmHoldPreview">确认</button>
                  <button type="button" :disabled="holdReviewSaving || editorOpen" @click="openPreviewEditor">修改轮廓</button>
                  <button type="button" aria-label="取消候选岩点" :disabled="holdReviewSaving || editorOpen" @click="holdPreview=null">取消</button>
                </div>
                <div v-else-if="selectedHoldId" class="canvas-hold-actions" :style="canvasActionsStyle" role="group" aria-label="所选岩点操作">
                  <span v-if="!selectedCanvasHoldHasContour" class="missing-contour-note">此岩点缺少轮廓</span>
                  <button type="button" aria-label="修改所选轮廓" :disabled="!canAddHoldAtPoint || editorBusy" @click="openHoldEditor(Number(selectedHoldId))">修改轮廓</button>
                  <button type="button" aria-label="删除所选岩点" :disabled="!canAddHoldAtPoint || holdReviewSaving || holdPreviewLoading || editorOpen" @click="removeSelectedHold">删除</button>
                  <button type="button" aria-label="取消岩点选择" :disabled="holdReviewSaving" @click="selectedHoldId=''">取消</button>
                </div>
            </div>
            <div v-if="playbackStatus === 'loading' || playbackStatus === 'unavailable'" class="video-preview-state" :aria-busy="playbackStatus === 'loading'">
              <div v-if="playbackStatus === 'loading'" class="video-preview-message" role="status">
                <Loading class="video-preview-spinner" aria-hidden="true" />
                <strong>{{ preparingPreview ? '正在准备视频' : '正在加载视频画面' }}</strong>
                <p>{{ preparingPreview ? '正在本机转换为统一格式，原文件保留。' : '正在缓冲，请稍候。' }}</p>
              </div>
              <div v-else class="video-preview-message" role="alert">
                <Warning aria-hidden="true" />
                <strong>暂时无法预览视频</strong>
                <p>{{ playbackFailure }}</p>
                <button type="button" @click="retryPlayback">重新加载画面</button>
              </div>
            </div>
            <button v-if="!isBusy && !reviewResult" type="button" class="replace-video" @click="openPicker">更换视频</button>
          </div>

          <aside v-if="activeAction" class="action-focus" aria-label="当前动作">
            <div class="action-focus-head">
              <strong>当前动作</strong>
              <span><b>{{ String(activeAction.step).padStart(2, '0') }}</b> / {{ String(actionEvents.length).padStart(2, '0') }}</span>
            </div>
            <div class="action-focus-name">
              <span>{{ String(activeAction.step).padStart(2, '0') }}</span>
              <div>
                <strong>{{ limbNames[activeAction.limb] || '手脚' }}</strong>
                <p>{{ activeAction.supplementary_name }}</p>
                <small>{{ formatClock(activeAction.seek_time_seconds) }}</small>
              </div>
            </div>
            <div class="action-focus-actions">
              <button type="button" :disabled="activeActionIndex <= 0" @click="stepAction(-1)"><ArrowLeft /><span>上一个</span></button>
              <button type="button" class="primary" @click="replayActiveAction"><RefreshRight /><span>重看</span></button>
              <button type="button" :disabled="activeActionIndex >= actionEvents.length - 1" @click="stepAction(1)"><ArrowRight /><span>下一个</span></button>
            </div>
          </aside>
        </div>
        <div v-if="false" class="visual-replay-state" aria-live="polite">
          <p>{{ visualReplayError || visualState.message }}</p>
          <button v-if="visualState.canRetry" type="button" :disabled="visualReplaySubmitting || isJobDeleting" @click="retryVisualReplay">{{ visualReplaySubmitting ? '正在提交…' : visualState.stale ? '重新制作线路回放' : '重试线路回放' }}</button>
          <button v-if="visualState.busy" type="button" :disabled="visualReplaySubmitting || isJobDeleting" @click="cancelVisualReplay">停止制作</button>
        </div>
        <p v-if="false" class="visual-playback-note" role="status">线路回放 · 按本次用点顺序展示，动作时间仍以原视频为准。</p>
        <nav v-if="false" class="event-timeline" aria-label="动作顺序">
          <div class="event-timeline-heading">
            <strong>动作顺序</strong>
            <span>点一下定位</span>
          </div>
          <ol>
            <li v-for="event in actionEvents" :key="event.key">
              <button
                type="button"
                :class="{ current: event.key === activeActionKey, reached: playbackTime >= event.seek_time_seconds }"
                :aria-current="event.key === activeActionKey ? 'step' : undefined"
                :aria-label="actionAriaLabel(event)"
                @click="seekToEvent(event)"
              >
                <span>{{ String(event.step).padStart(2, '0') }}</span>
                <strong>{{ limbNames[event.limb] || '手脚' }}</strong>
                <small>{{ event.supplementary_name }}</small>
              </button>
            </li>
          </ol>
        </nav>
        <input ref="fileInput" class="visually-hidden" type="file" accept="video/*,.mp4,.mov,.m4v,.webm,.3gp,.3g2,.mkv,.avi,.mpg,.mpeg,.mpe,.ts,.mts,.m2ts,.m2t,.wmv,.asf,.flv,.f4v,.vob,.ogv,.ogg,.mxf,.divx" @change="onFileChange" />

        <div v-if="activeJob && (!result || isBusy) && activeJob.status !== 'awaiting_hold_review'" class="analysis-state" :class="activeJob.status" aria-live="polite">
          <div class="state-copy">
            <span class="state-mark"><Loading v-if="isBusy" /><CircleCheck v-else-if="activeJob.status === 'succeeded'" /><Warning v-else /></span>
            <div>
              <strong>{{ statusTitle }}</strong>
              <p>{{ statusDetail }}</p>
            </div>
            <b v-if="isBusy">{{ activeJob.progress || 0 }}%</b>
          </div>
          <div v-if="isBusy" class="progress-track"><i :style="{ transform: `scaleX(${(activeJob.progress || 0) / 100})` }" /></div>
          <div v-if="['failed', 'cancelled'].includes(activeJob.status) && !isJobDeleting" class="state-actions">
            <button v-if="sourceAvailable" type="button" class="secondary-button" :disabled="!consentPolicy" @click="retryJob">重试本地准备</button>
            <p v-else>原视频已删除，这次复盘不能重新分析。</p>
          </div>
          <button type="button" :disabled="!canSubmitSkeleton" @click="submit(true)">跳过岩点识别</button>
          <button v-if="isBusy" type="button" class="cancel-action" @click="cancelJob">取消任务</button>
        </div>


      </div>

      <TaskPanel v-if="!result && !reviewResult" class="setup-panel" title="线路取色" :paginate="false">
        <p v-if="!selectedFile" class="setup-empty">选择视频后，在画面中取色。</p>
        <fieldset v-if="selectedFile">
          <legend class="visually-hidden">线路颜色</legend>
          <p class="setup-note">暂停后，点选目标岩点。</p>
          <div class="color-sample-tools">
            <button type="button" aria-label="从画面点选样本岩点" :disabled="!videoMeta || playbackStatus !== 'ready' || isBusy || isSubmitting" @click="startColorPicking">从画面取色</button>
          </div>
          <p v-if="colorSample" class="color-sample-status" role="status">
            <i :style="{ background: colorSample.hex }" />
            {{ routeColor }} · {{ colorSample.hex.toUpperCase() }}
          </p>
        </fieldset>
        <p v-if="videoMeta?.duration > MAX_VIDEO_SECONDS" class="setup-note">本次分析前 90 秒。</p>
        <template #footer>
          <p v-if="playbackStatus === 'unavailable'">无法预览，请重新加载或更换视频。</p>
          <button type="button" class="primary-action" aria-label="识别岩点" :disabled="!canSubmit" @click="submit(false)">
            <Loading v-if="isBusy || isSubmitting" class="primary-spinner" />
            <span>{{ isSubmitting ? '正在开始识别…' : (isBusy ? '正在处理' : '识别岩点') }}</span>
          </button>
          <button type="button" :disabled="!canSubmitSkeleton" @click="submit(true)">跳过岩点识别</button>
          <button v-if="isBusy" type="button" class="cancel-action" @click="cancelJob">取消任务</button>
          <p v-if="formError" class="form-error" role="alert">{{ formError }}</p>
          <p v-if="formNotice" class="form-notice" role="status">{{ formNotice }}</p>
        </template>
      </TaskPanel>
    </div>

      <button v-if="!result && canStartSkeleton && !activeJob?.skeleton_only" type="button" @click="startAnalysis(true)">跳过岩点识别</button>
      <footer v-if="!result && reviewResult && !activeJob?.skeleton_only && !isJobDeleting && !isBusy" class="hold-global-actions">
        <div v-if="!repairDetailsOpen" class="hold-inline-feedback" aria-live="polite">
          <span v-if="holdPreviewLoading">正在描出岩点轮廓…</span>
          <span v-else-if="holdReviewSaving">{{ localHoldAnalysisRunning ? '正在分析…' : '正在保存岩点…' }}</span>
          <span v-else-if="holdReviewError" class="form-error" role="alert">{{holdReviewError}}</span>
          <span v-else-if="formError" class="form-error" role="alert">{{formError}}</span>
          <span v-else-if="holdReviewNotice" role="status">{{holdReviewNotice}}</span>
          <span v-else-if="!sourcePlayable">原视频已不可用，无法补充岩点；已有复盘仍可观看。</span>
          <span v-else-if="activeJob.segment_reviews?.length">已有动作段复核，请先撤销相关复核后再补充岩点。</span>
          <span v-else-if="result && activeJob.error" role="alert">{{activeJob.stage}}：{{activeJob.error}}</span>
          <span v-else-if="activeJob.holds_pending_local_analysis">岩点修改尚未分析，当前复盘仍为上一版。</span>
          <span v-else class="review-count">{{reviewResult.holds?.length || 0}} 个岩点<span>{{allHoldsConfirmed ? '已确认' : holdReviewMode ? '点击删点，拖框补点' : '待确认'}}</span></span>
        </div>
        <button type="button" class="primary-action" :aria-busy="holdReviewSaving" :disabled="!canAddHoldAtPoint || !reviewResult.holds?.length || holdReviewSaving || holdPreviewLoading || !!holdPreview || editorOpen || allHoldsConfirmed" @click="confirmAllHolds"><Loading v-if="holdReviewSaving" class="primary-spinner" aria-hidden="true" /><CircleCheck v-else aria-hidden="true" />{{ allHoldsConfirmed ? '全部岩点已确认' : activeJob.holds_pending_local_analysis ? '确认全部岩点并本地分析' : '确认全部岩点' }}</button>
        <button v-if="!result && allHoldsConfirmed" type="button" class="primary-action" :disabled="!canStartAnalysis" @click="startAnalysis(false)">开始复盘</button>
      </footer>

    <WorkspaceSheet v-if="repairDetailsOpen" title="岩点记录与版本" @close="repairDetailsOpen=false">
      <p v-if="holdReviewError" role="alert">{{holdReviewError}}</p>
      <p v-if="holdReviewNotice" role="status">{{holdReviewNotice}}</p>
      <button v-if="result && sourcePlayable" type="button" :disabled="routeMapRefreshing || holdReviewSaving || visualState.busy || editorOpen" @click="refreshRouteMap">{{ routeMapRefreshing ? '正在本地生成…' : '重新生成岩点图（本地）' }}</button>
      <button v-if="result" type="button" @click="repairDetailsOpen=false;reanalysisOpen=true">重新生成复盘</button>
          <details v-if="manualHoldOperations.length" class="manual-hold-history">
            <summary><span>补点记录 · {{ activeManualHoldCount }} 次有效</span><ArrowRight aria-hidden="true" /></summary>
            <div v-for="operation in manualHoldOperations" :key="operation.version" class="media-row">
              <span class="manual-hold-detail"><strong>第 {{ operation.ordinal }} 次补点<span v-if="!operation.active" class="hold-undone">已撤销</span></strong><small>{{ formatClock(operation.time_seconds) }}<template v-if="operation.active"> · {{ holdPositionLabel(operation.point_xy) }}</template></small></span>
              <div class="manual-hold-actions">
                <button type="button" :disabled="!operation.active || !sourcePlayable || holdReviewSaving" @click="inspectClickedHold(operation);repairDetailsOpen=false">查看补点</button>
                <button type="button" :disabled="!operation.active || !canUndoManualHold || holdReviewSaving || editorOpen" @click="undoClickedHold(operation)">撤销补点</button>
              </div>
            </div>
          </details>

    </WorkspaceSheet>
    <WorkspaceSheet v-if="historyOpen" title="最近分析" @close="historyOpen=false">

      <button v-for="job in pageJobs" :key="job.id" type="button" class="recent-row" @click="selectJob(job);historyOpen=false">
        <span class="recent-dot" :class="job.status" />
        <span><strong>{{ job.original_name }}</strong><small>{{ job.route_color }}线路 · {{ dateLabel(job.created_at) }}</small></span>
        <b>{{ jobStatusLabel(job) }}</b>
      </button>
    <template #footer><nav class="work-pagination" aria-label="分析历史分页"><button type="button" :disabled="historyPage===0" @click="historyPage--">上一页</button><output>{{historyPage+1}} / {{Math.max(1,Math.ceil(recentJobs.length/5))}}</output><button type="button" :disabled="(historyPage+1)*5>=recentJobs.length" @click="historyPage++">下一页</button></nav></template></WorkspaceSheet>

<EditorDialog v-if="editorOpen" @cancel="holdEditor?.requestClose()"><ReplayHoldEditor ref="holdEditor" :key="`${activeJob.id}:${editorSession}`" :job="activeJob" :initial-time="editorTime" :initial-hold-id="editorHoldId" :initial-polygon="editorSeed" @saved="holdEditorSaved" @busy="editorBusy = $event" @close="editorOpen = false" /></EditorDialog>

  </section>
</template>

<script setup>
const isDesktop = Boolean(window.__AI_CLIMBING_DESKTOP__)
import { computed, nextTick, onBeforeUnmount, onMounted, ref, useId, watch } from 'vue'
import { ArrowDown, ArrowLeft, ArrowRight, CircleCheck, Clock, Crop, Delete, Document, EditPen, FolderOpened, Hide, Loading, Plus, Rank, RefreshRight, VideoCamera, View, Warning } from '@element-plus/icons-vue'
import climbReplayService from '../services/climbReplayService'
import { useSmoothNumber } from '../services/useSmoothNumber.js'
import { analysisDuration, analysisSeekTime, visualReplayState } from '../services/visualReplayPresentation.js'
import { nearestRouteColor, rgbToHex } from '../constants/routeColors.js'
import UnifiedReplayPlayer from './LocalReplayPlayer.vue'

import ReplayTorsoCenter from './ReplayTorsoCenter.vue'
import { torsoDisplayFrame } from '../services/replayTorsoCenter.js'
import { centerOfMass as torsoCenter } from '../services/replayCenterOfMass.js'
import ReplayHoldEditor from './ReplayHoldEditor.vue'
import TaskPanel from './ui/TaskPanel.vue'
import WorkspaceSheet from './ui/WorkspaceSheet.vue'
import EditorDialog from './ui/EditorDialog.vue'

const limbNames = { left_hand: '左手', right_hand: '右手', left_foot: '左脚', right_foot: '右脚' }
const manualTechniqueNames = ['高抬脚', '锁臂', '旗式', '脚上方重心转移', '动态点', '跳跃', '主动摆荡换点', '抓点后制摆', '开门摆动']
const fileInput = ref(null)
const reanalysisOpen=ref(false)
const samplesOpen=ref(false), historyOpen=ref(false), samplePage=ref(0), historyPage=ref(0)
const pageJobs=computed(()=>recentJobs.value.slice(historyPage.value*5,(historyPage.value+1)*5))
const holdEditor = ref(null)
const editorOpen = ref(false), editorBusy = ref(false), editorTime = ref(0), editorHoldId = ref(0), editorSession = ref(0), editorSeed = ref([])
const repairDetailsOpen = ref(false)
const reviewMenuId = useId(), reviewMenu = ref(null), reviewMenuOpen = ref(false), reviewMenuPosition = ref({})
function positionReviewMenu(event) {
  const rect = event.currentTarget.getBoundingClientRect()
  const top = Math.max(12, Math.min(rect.bottom + 8, window.innerHeight - 340))
  reviewMenuPosition.value = { left:`${Math.max(12, Math.min(rect.left, window.innerWidth - 268))}px`, top:`${top}px`, maxHeight:`${window.innerHeight - top - 16}px` }
}
function reviewAssetAction(action) {
  reviewMenu.value?.hidePopover()
  if (action === 'replace') openPicker()
  else if (action === 'samples') samplesOpen.value = true
  else if (action === 'history') historyOpen.value = true
  else if (action === 'versions') repairDetailsOpen.value = true
  else if (action === 'replay') viewVisualReplay()
  else if (action === 'delete') deleteEntireReplay()
}
function openHoldEditor(holdId = 0, seed = []) {
  if (editorOpen.value && !window.confirm('重新打开精修会丢弃尚未保存的描边，是否继续？')) return
  const unifiedTime = unifiedPlayer.value?.pauseForHoldReview?.()
  videoElement.value?.pause()
  editorTime.value = Number(unifiedTime ?? videoElement.value?.currentTime ?? 0)
  editorHoldId.value = holdId
  editorSeed.value = seed.map(point => [...point])
  editorOpen.value = true
  editorSession.value++
  holdReviewMode.value = false
  if (!seed.length) holdPreview.value = null
}
function openPreviewEditor() {
  if (!holdPreview.value || editorBusy.value) return
  openHoldEditor(0, holdPreview.value.source_polygon || [])
}
function holdEditorSaved(job) {
  activeJob.value = job
  holdPreview.value = null
  holdReviewNotice.value = '轮廓已保存到草稿，全部补完后请确认全部岩点。'
  loadJobs()
}
const videoElement = ref(null)
const videoStage = ref(null), videoDimensions = ref({ width:0, height:0 }), stageDimensions = ref({ width:0, height:0 })
let videoStageObserver
watch(videoStage, element => {
  videoStageObserver?.disconnect()
  if (!element) return
  videoStageObserver = new ResizeObserver(() => {
    const page = element.closest('.replay-page'), style = page && getComputedStyle(page)
    const width = page ? page.clientWidth - (parseFloat(style.paddingLeft) || 0) - (parseFloat(style.paddingRight) || 0) : element.clientWidth
    stageDimensions.value = { width, height:element.clientHeight, toolSpace:Number.parseFloat(getComputedStyle(element).getPropertyValue('--review-tool-space')) || 0 }
  })
  videoStageObserver.observe(element)
  const page = element.closest('.replay-page')
  if (page) videoStageObserver.observe(page)
}, { flush:'post' })
onBeforeUnmount(() => videoStageObserver?.disconnect())
const videoFrameStyle = computed(() => {
  const { width, height } = videoDimensions.value, area = stageDimensions.value
  if (!width || !height || !area.width || !area.height) return {}
  const scale = Math.min(Math.max(0, area.width - (area.toolSpace || 0)) / width, area.height / height)
  return { width:`${width * scale}px`, height:`${height * scale}px`, minWidth:'0', flex:'none' }
})
const reviewWorkbenchStyle = computed(() => reviewView.value.viewportWidth ? { '--review-frame-width':`${reviewView.value.viewportWidth}px` } : {})
const reviewViewport = ref(null), reviewZoom = ref(1), reviewPanning = ref(false), reviewCenter = ref({ x:.5, y:.5 })
const { visible:reviewDisplayZoom, animating:reviewZoomAnimating, reset:resetReviewZoom } = useSmoothNumber(reviewZoom)
let reviewPanGesture = null
const reviewView = computed(() => {
  const width = Number.parseFloat(videoFrameStyle.value.width) || 0, height = Number.parseFloat(videoFrameStyle.value.height) || 0
  const zoom = reviewDisplayZoom.value
  const viewportWidth = zoom > 1 ? Math.min(width*zoom,Math.max(width,stageDimensions.value.width-(stageDimensions.value.toolSpace || 0))) : width
  const edgeX = viewportWidth / (2*width*zoom), edgeY = .5/zoom
  const centerX = Math.max(edgeX,Math.min(1-edgeX,reviewCenter.value.x)), centerY = Math.max(edgeY,Math.min(1-edgeY,reviewCenter.value.y))
  return { width, height, viewportWidth, x:viewportWidth / 2 - centerX * width * zoom, y:height / 2 - centerY * height * zoom }
})
const reviewViewportStyle = computed(() => ({ ...videoFrameStyle.value, width:reviewView.value.viewportWidth ? `${reviewView.value.viewportWidth}px` : undefined }))
const reviewMediaStyle = computed(() => {
  const { width, height, x, y } = reviewView.value
  return width && height ? { width:`${width * reviewDisplayZoom.value}px`, height:`${height * reviewDisplayZoom.value}px`, transform:`translate(${x}px,${y}px)` } : {}
})
function clampReviewCenter(center) {
  const { width, viewportWidth } = reviewView.value
  const edgeX = width ? viewportWidth/(2*width*reviewZoom.value) : .5, edgeY = .5/reviewZoom.value
  return { x:Math.max(edgeX,Math.min(1-edgeX,center.x)), y:Math.max(edgeY,Math.min(1-edgeY,center.y)) }
}
function setReviewZoom(value) {
  if (holdReviewSaving.value || holdPreviewLoading.value) return
  videoElement.value?.pause()
  reviewZoom.value = Math.max(1,Math.min(8,value))
  if (reviewZoom.value === 1) reviewPanning.value = false
}
watch(reviewZoomAnimating, moving => { if (!moving && reviewZoom.value === 1) reviewCenter.value = {x:.5,y:.5} })
function stepReviewZoom(event) {
  if (!reviewResult.value) return
  const levels = [1,2,4,8]
  setReviewZoom(event.deltaY < 0 ? levels.find(n=>n>reviewZoom.value) || 8 : [...levels].reverse().find(n=>n<reviewZoom.value) || 1)
}
function handleReviewWheel(event) {
  if (event.ctrlKey) { event.preventDefault();stepReviewZoom(event);return }
  if (reviewZoom.value<=1 || holdReviewSaving.value || holdPreviewLoading.value) return
  event.preventDefault()
  const { width, height } = reviewView.value, unit = event.deltaMode === 1 ? 16 : event.deltaMode === 2 ? height : 1
  reviewCenter.value = clampReviewCenter({ x:reviewCenter.value.x+(event.shiftKey && !event.deltaX ? event.deltaY : event.deltaX)*unit/(width*reviewZoom.value), y:reviewCenter.value.y+(event.shiftKey && !event.deltaX ? 0 : event.deltaY)*unit/(height*reviewZoom.value) })
}
// Two-finger touch panning leaves one-finger box drawing available in the same tool.
const reviewTouches = new Map()
let reviewTouchPan = null
function startReviewTouchPan(event) {
  if (event.pointerType!=='touch' || reviewZoom.value<=1 || holdReviewSaving.value || holdPreviewLoading.value || event.target.closest('.canvas-hold-actions')) return
  reviewTouches.set(event.pointerId,{x:event.clientX,y:event.clientY})
  if (reviewTouches.size<2) return
  event.preventDefault();event.stopPropagation();cancelHoldDraw();reviewPanGesture=null
  const points=[...reviewTouches.values()]
  reviewTouchPan={ x:(points[0].x+points[1].x)/2, y:(points[0].y+points[1].y)/2, center:clampReviewCenter(reviewCenter.value) }
  for (const id of reviewTouches.keys()) event.currentTarget.setPointerCapture(id)
}
function moveReviewTouchPan(event) {
  if (!reviewTouches.has(event.pointerId)) return
  reviewTouches.set(event.pointerId,{x:event.clientX,y:event.clientY})
  if (!reviewTouchPan || reviewTouches.size<2) return
  event.preventDefault();event.stopPropagation()
  const points=[...reviewTouches.values()],{width,height}=reviewView.value
  reviewCenter.value=clampReviewCenter({x:reviewTouchPan.center.x-((points[0].x+points[1].x)/2-reviewTouchPan.x)/(width*reviewZoom.value),y:reviewTouchPan.center.y-((points[0].y+points[1].y)/2-reviewTouchPan.y)/(height*reviewZoom.value)})
}
function endReviewTouchPan(event) {
  reviewTouches.delete(event.pointerId)
  if (!reviewTouchPan) return
  event.stopPropagation();cancelHoldDraw()
  if(event.currentTarget.hasPointerCapture(event.pointerId))event.currentTarget.releasePointerCapture(event.pointerId)
  if (!reviewTouches.size) reviewTouchPan=null
}
function startReviewPan(event) {
  if (reviewZoomAnimating.value || holdReviewSaving.value || holdPreviewLoading.value || (event.pointerType === 'mouse' && event.button !== 0)) return
  event.preventDefault()
  reviewPanGesture = { id:event.pointerId, x:event.clientX, y:event.clientY, center:clampReviewCenter(reviewCenter.value) }
  event.currentTarget.setPointerCapture(event.pointerId)
}
function moveReviewPan(event) {
  if (reviewPanGesture?.id !== event.pointerId) return
  const { width, height } = reviewView.value
  if (!width || !height) return
  reviewCenter.value = clampReviewCenter({ x:reviewPanGesture.center.x - (event.clientX-reviewPanGesture.x)/(width*reviewZoom.value), y:reviewPanGesture.center.y - (event.clientY-reviewPanGesture.y)/(height*reviewZoom.value) })
}
function endReviewPan(event) {
  if (reviewPanGesture?.id !== event.pointerId) return
  if (event.type === 'pointerup') moveReviewPan(event)
  const clicked = event.type==='pointerup' && Math.hypot(event.clientX-reviewPanGesture.x,event.clientY-reviewPanGesture.y)<6
  reviewPanGesture = null
  if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId)
  if (clicked) selectHoldAtClientPoint(event)
}
function panReviewByKey(event) {
  const delta = { ArrowLeft:[-1,0], ArrowRight:[1,0], ArrowUp:[0,-1], ArrowDown:[0,1] }[event.key]
  if (!delta) return
  event.preventDefault()
  reviewCenter.value = clampReviewCenter({ x:reviewCenter.value.x+delta[0]*.05/reviewZoom.value, y:reviewCenter.value.y+delta[1]*.05/reviewZoom.value })
}
function activateHoldReview() {
  if (reviewPanning.value) { reviewPanning.value = false; if (!holdReviewMode.value) toggleHoldReview() }
  else toggleHoldReview()
}
const unifiedPlayer = ref(null)
const holdRepairOpen = ref(false)
const comparisonFirstVideo = ref(null)
const comparisonSecondVideo = ref(null)
const comparisonPartnerId = ref('')
const sameClimberConfirmed = ref(false)
const segmentComparison = ref(null)
const comparisonError = ref('')
const comparisonLoading = ref(false)
const reviewingSegmentId = ref('')
const segmentForm = ref({})
const reviewSaving = ref(false)
const reviewError = ref('')
const selectedFile = ref(null)
const previewUrl = ref('')
const preparingPreview = ref(false)
const preparedPreviewId = ref('')
let previewController = null
const videoMeta = ref(null)
const playbackStatus = ref('idle')
const playbackFailure = ref('')
let playbackLoadTimer = null
const trimStartSeconds = ref(0)
const trimEndSeconds = ref(90)
const MAX_VIDEO_SECONDS = 90
const MAX_INPUT_BYTES = 500 * 1024 * 1024
const routeColor = ref('')
const colorSample = ref(null)
const colorPicking = ref(false)
const colorSampleCanvas = ref(null)
let sampledFrameRect = null
const retentionMode = ref('keep_private_original')
const consentPolicy = ref(null)
const testVideoCases = ref([])
const loadingTestCaseId = ref('')
const uploadProgress = ref(0)
const isSubmitting = ref(false)
const activeJob = ref(null)
const recentJobs = ref([])
const formError = ref('')
const formNotice = ref('')
const isDragging = ref(false)
const isDeleting = ref(false)
const deletionReceipt = ref(null)
const showHolds = ref(true)
const holdReviewMode = ref(false)
const holdReviewSaving = ref(false)
const holdPreviewLoading = ref(false)
const holdPreview = ref(null)
const holdPreviewActions = ref(null)
const holdConfirmationButton = ref(null)
const holdDraw = ref(null)
const holdCoordinateDetails = ref(null)
const holdCoordinateFirstInput = ref(null)
const holdRegionForm = ref({ left:null, top:null, right:null, bottom:null })
const holdDrawStyle = computed(() => {
  if (!holdDraw.value) return {}
  const [sx, sy] = holdDraw.value.start
  const [ex, ey] = holdDraw.value.end
  return { left:`${Math.min(sx, ex) * 100}%`, top:`${Math.min(sy, ey) * 100}%`,
    width:`${Math.abs(ex - sx) * 100}%`, height:`${Math.abs(ey - sy) * 100}%` }
})
const holdPreviewPoints = computed(() => (holdPreview.value?.source_polygon || [])
  .map(([x, y]) => `${x * 100},${y * 100}`).join(' '))
const holdReviewError = ref('')
const holdReviewNotice = ref('')
const inspectedHoldReviewVersion = ref(null)
const autoRefineAttempted = new Set()
const showPose = ref(true)
const showEvents = ref(true)
const playbackTime = ref(0)
const coachingClipEnd = ref(null)
const preferredPlaybackKind = ref('overlay')
const pendingPlaybackState = ref(null)
const visualReplaySubmitting = ref(false)
const visualReplayError = ref('')
const routeMapRefreshing = ref(false)
const routeMapPlayerVersion = ref(0)
let pollTimer = 0
let deletionTimer = 0

const poseEdges = [
  [5, 6], [5, 7], [7, 9], [6, 8], [8, 10],
  [5, 11], [6, 12], [11, 12], [11, 13], [13, 15], [12, 14], [14, 16],
]

const isBusy = computed(() => ['queued', 'running'].includes(activeJob.value?.status))
const isJobDeleting = computed(() => deletionReceipt.value
  ? deletionReceipt.value.state === 'queued'
  : activeJob.value?.deletion?.state === 'queued')
const result = computed(() => activeJob.value?.result || null)
const reviewResult = computed(() => activeJob.value?.hold_edit_draft || result.value || activeJob.value?.hold_draft || null)
const localHoldAnalysisRunning = ref(false)
const selectedHoldId = ref('')
const allHoldsConfirmed = computed(() => !!activeJob.value?.holds_revision
  && activeJob.value.holds_confirmation?.revision === activeJob.value.holds_revision)
const canStartSkeleton = computed(() => consentPolicy.value && sourcePlayable.value && !isBusy.value && !isSubmitting.value && !holdReviewSaving.value && !editorOpen.value && !isJobDeleting.value && ['succeeded','awaiting_hold_review','failed','cancelled'].includes(activeJob.value?.status))
const canStartAnalysis = computed(() => allHoldsConfirmed.value
  && !editorOpen.value
  && consentPolicy.value && sourcePlayable.value && !isBusy.value && !isSubmitting.value
  && !holdReviewSaving.value && !holdPreviewLoading.value && !holdPreview.value && !isJobDeleting.value
  && ['succeeded', 'awaiting_hold_review'].includes(activeJob.value?.status))
const visualState = computed(() => visualReplayState(activeJob.value))
const isVisualPlayback = computed(() => playbackKind.value === 'overlay'
  && visualState.value.start !== null && playbackTime.value >= visualState.value.start)
const canRefineSampledHolds = computed(() => activeJob.value?.status === 'succeeded'
  && !activeJob.value?.holds_confirmation
  && !isJobDeleting.value
  && !activeJob.value?.segment_reviews?.length
  && sourcePlayable.value
  && result.value?.hold_evidence?.selection === 'color_candidates_need_review'
  && !activeJob.value?.hold_review_history?.length)
const canAddHoldAtPoint = computed(() => !activeJob.value?.skeleton_only && ['succeeded', 'awaiting_hold_review'].includes(activeJob.value?.status)
  && sourcePlayable.value && !isSubmitting.value && !isJobDeleting.value && !activeJob.value?.segment_reviews?.length)
const canUndoManualHold = computed(() => canAddHoldAtPoint.value
  && (reviewResult.value?.holds || []).some((hold) => ['user_confirmed_video_click', 'user_confirmed_video_candidate'].includes(hold.identity_source)))
const manualHoldOperations = computed(() => {
  const holds = reviewResult.value?.holds || []
  const fps = Number(activeJob.value?.video?.fps)
  let ordinal = 0
  return (activeJob.value?.hold_review_history || [])
    .filter((entry) => ['add_hold_at_point', 'promote_candidate', 'edit_hold_contour'].includes(entry.operation))
    .map((entry) => {
      ordinal += 1
      const hold = holds.find((item) => ['user_confirmed_video_click', 'user_confirmed_video_candidate'].includes(item.identity_source)
        && item.review_version === entry.version)
      const box = entry.bbox || hold?.bbox
      const pointXy = entry.point_xy || (box ? [box[0] + box[2] / 2, box[1] + box[3] / 2] : null)
      const timeSeconds = entry.time_seconds != null ? Number(entry.time_seconds)
        : (hold?.source_frame != null && Number.isFinite(fps) && fps > 0 ? Number(hold.source_frame) / fps : null)
      return { ...entry, ordinal, active:Boolean(hold), point_xy:pointXy, time_seconds:timeSeconds }
    })
})
const activeManualHoldCount = computed(() => manualHoldOperations.value.filter((entry) => entry.active).length)
const confirmedSegmentCount = computed(() => (activeJob.value?.reviewed_segments || [])
  .filter((segment) => segment.source === 'user_confirmed').length)
const comparisonCandidates = computed(() => recentJobs.value.filter((job) => (
  job.id !== activeJob.value?.id && job.status === 'succeeded'
  && job.route_id && job.route_id === activeJob.value?.route_id
  && job.route_version_id && job.route_version_id === activeJob.value?.route_version_id
)))
const comparisonPartner = computed(() => recentJobs.value.find((job) => job.id === comparisonPartnerId.value))
function comparisonVideoUrl(job) {
  if (!job?.id) return ''
  if (job.media?.source_video?.status === 'available') return climbReplayService.mediaUrl(job.id, 'source-video')
  if (job.media?.reviewed_overlay_video?.status === 'available') return climbReplayService.mediaUrl(job.id, 'reviewed-overlay-video')
  if (job.media?.overlay_video?.status === 'available') return climbReplayService.mediaUrl(job.id, 'overlay-video')
  return ''
}
async function runSegmentComparison() {
  comparisonLoading.value = true
  comparisonError.value = ''
  segmentComparison.value = null
  try {
    segmentComparison.value = await climbReplayService.compare(activeJob.value.id, comparisonPartnerId.value, sameClimberConfirmed.value)
  } catch (error) {
    comparisonError.value = error.response?.data?.detail || '暂时无法完成对比'
  } finally {
    comparisonLoading.value = false
  }
}
function comparisonReason(reason) {
  return ({ unconfirmed_hold_identity: '岩点身份未确认', hold_match_weak: '照片与视频的岩点匹配证据不足', wall_alignment_insufficient: '镜头对齐不足',
    timestamps_unavailable: '时间戳不足', matching_segment_missing: '没有相同手脚和起终岩点的动作段' })[reason] || '证据不足'
}
function comparisonStatus(pair) {
  return ({ uncertain: '当前精度下无法确认变化', shorter: '第二次较短', longer: '第二次较长' })[pair.status] || '不可比'
}
function signedSeconds(value) { return `${value > 0 ? '+' : ''}${Number(value).toFixed(2)}` }
function seekComparisonVideo(which, seconds) {
  const player = which === 'first' ? comparisonFirstVideo.value : comparisonSecondVideo.value
  const job = which === 'first' ? activeJob.value : comparisonPartner.value
  if (player) { player.currentTime = analysisSeekTime(job, seconds); player.play().catch(() => {}) }
}
function limitComparisonPlayback(which) {
  const player = which === 'first' ? comparisonFirstVideo.value : comparisonSecondVideo.value
  const job = which === 'first' ? activeJob.value : comparisonPartner.value
  const end = analysisDuration(job)
  if (player && end !== null && player.currentTime >= end) {
    player.pause()
    player.currentTime = analysisSeekTime(job, end)
  }
}
function routeHoldLabel(id) {
  const hold = (result.value?.holds || []).find((item) => String(item.saved_object_id) === String(id))
  return hold ? `岩点 ${hold.id}` : `线路岩点 ${String(id).slice(0, 8)}`
}
function segmentHoldLabel(segment, end) {
  const routeId = segment?.[`${end}_route_hold_id`]
  return routeId ? routeHoldLabel(routeId) : `岩点 ${segment?.[`${end}_hold_id`] || '?'}（未确认）`
}
function beginSegmentReview(segment) {
  reviewError.value = ''
  reviewingSegmentId.value = segment.id
  segmentForm.value = {
    limb: segment.limb,
    source_route_hold_id: String(segment.source_route_hold_id || ''),
    target_route_hold_id: String(segment.target_route_hold_id || ''),
    start_time_seconds: segment.start_time_seconds,
    end_time_seconds: segment.end_time_seconds,
    technique_label: segment.technique_labels?.[0]?.name || '',
  }
}
function seekReviewTime(seconds) {
  if (videoElement.value && Number.isFinite(Number(seconds))) videoElement.value.currentTime = analysisSeekTime(activeJob.value, seconds)
}
async function saveSegmentReview() {
  reviewSaving.value = true
  reviewError.value = ''
  try {
    activeJob.value = await climbReplayService.reviewSegment(activeJob.value.id, reviewingSegmentId.value, {
      ...segmentForm.value, technique_label: segmentForm.value.technique_label || null,
    })
    reviewingSegmentId.value = ''
    segmentComparison.value = null
    await loadJobs()
  } catch (error) { reviewError.value = error.response?.data?.detail || '复核保存失败' }
  finally { reviewSaving.value = false }
}
async function revertSegmentReview(segmentId) {
  reviewError.value = ''
  try {
    activeJob.value = await climbReplayService.revertSegmentReview(activeJob.value.id, segmentId)
    segmentComparison.value = null
    reviewingSegmentId.value = ''
    await loadJobs()
  } catch (error) { reviewError.value = error.response?.data?.detail || '撤销失败' }
}
const sourceMedia = computed(() => activeJob.value?.media?.source_video || null)
const sourceAvailable = computed(() => sourceMedia.value?.status === 'available')
const sourcePlayable = computed(() => sourceAvailable.value &&
  (!activeJob.value?.preparation || activeJob.value.preparation.status === 'completed'))
const overlayMedia = computed(() => activeJob.value?.media?.overlay_video || null)
const overlayAvailable = computed(() => overlayMedia.value?.status === 'available')
const reviewedOverlayAvailable = computed(() => activeJob.value?.media?.reviewed_overlay_video?.status === 'available')
const comparisonCase = computed(() => testVideoCases.value.find((item) => (
  item.comparison_available
  && !visualState.value.visible
  && activeJob.value?.status === 'succeeded'
  && item.filename === activeJob.value?.original_name
  && item.comparison_route_color === activeJob.value?.route_color
  && Number(item.comparison_action_count) === actionEvents.value.length
)) || null)
const replayVideoAvailable = computed(() => reviewedOverlayAvailable.value || Boolean(comparisonCase.value) || overlayAvailable.value)
const replayVideoUrl = computed(() => {
  if (activeJob.value?.id && reviewedOverlayAvailable.value) return climbReplayService.mediaUrl(activeJob.value.id, 'reviewed-overlay-video')
  if (comparisonCase.value) return climbReplayService.comparisonVideoUrl(comparisonCase.value.id)
  if (activeJob.value?.id && overlayAvailable.value) {
    return climbReplayService.mediaUrl(activeJob.value.id, 'overlay-video')
  }
  return ''
})
const playbackKind = computed(() => {
  if (previewUrl.value) return 'preview'
  if (preferredPlaybackKind.value === 'overlay' && replayVideoAvailable.value) return 'overlay'
  if (preferredPlaybackKind.value === 'source' && sourcePlayable.value) return 'source'
  if (replayVideoAvailable.value) return 'overlay'
  if (sourcePlayable.value) return 'source'
  return 'none'
})
const playbackUrl = computed(() => {
  if (previewUrl.value) return previewUrl.value
  if (!activeJob.value?.id) return ''
  if (playbackKind.value === 'overlay') return replayVideoUrl.value
  if (playbackKind.value === 'source') return climbReplayService.mediaUrl(activeJob.value.id, 'source-video')
  return ''
})
const playerMode = computed(() => {
  if (['preview', 'source'].includes(playbackKind.value)) return 'interactive'
  if (playbackKind.value === 'overlay') return 'rendered'
  return 'none'
})
const storedOverlayDownloadUrl = computed(() => activeJob.value?.id && overlayAvailable.value
  ? climbReplayService.mediaUrl(activeJob.value.id, 'overlay-video', true)
  : '')
const replayDownloadUrl = computed(() => {
  if (activeJob.value?.id && reviewedOverlayAvailable.value) return climbReplayService.mediaUrl(activeJob.value.id, 'reviewed-overlay-video', true)
  if (comparisonCase.value) return climbReplayService.comparisonVideoUrl(comparisonCase.value.id, true)
  return storedOverlayDownloadUrl.value
})
const poseSamples = computed(() => (result.value?.pose_samples || []).filter((sample) => sample.observed))
const contactEvents = computed(() => (result.value?.attempt?.contacts || [])
  .filter((event) => Number.isFinite(Number(event.start_time_seconds)))
  .map((event, index) => ({ ...event, key: `${event.limb}-${event.hold_id}-${event.start_time_seconds}-${index}` })))
const actionEvents = computed(() => {
  const attempt = result.value?.attempt || {}
  const source = attempt.action_steps?.length ? attempt.action_steps : (attempt.contacts || [])
  const fps = Number(result.value?.video?.fps || 0)
  const limbOrder = { left_hand: 0, right_hand: 1, left_foot: 2, right_foot: 3 }
  const ordered = source
    .map((event, index) => {
      const sourceFrame = Number(event.start_source_frame)
      const eventTime = Number(event.start_time_seconds)
      const seekTime = Number.isFinite(sourceFrame) && sourceFrame >= 0 && fps > 0
        ? sourceFrame / fps
        : eventTime
      return {
        ...event,
        source_step: Number(event.step || index + 1),
        seek_time_seconds: seekTime,
      }
    })
    .filter((event) => Number.isFinite(event.seek_time_seconds))
    .sort((left, right) => (
      left.seek_time_seconds - right.seek_time_seconds
      || (limbOrder[left.limb] ?? 9) - (limbOrder[right.limb] ?? 9)
      || Number(left.hold_id || 0) - Number(right.hold_id || 0)
    ))
  const firstTime = ordered.length ? ordered[0].seek_time_seconds : 0
  const previousHoldByLimb = new Map()
  const namedEvents = []
  return ordered.map((event, index) => {
    const sourceHoldId = event.source_hold_id ?? previousHoldByLimb.get(event.limb)
    const activeSameHold = [...namedEvents].reverse().find((prior) => (
      prior.limb !== event.limb
      && Number(prior.hold_id) === Number(event.hold_id)
      && actionEndTime(prior) >= event.seek_time_seconds
    ))
    const supplementaryName = event.supplementary_name || inferSupplementaryActionName(
      event, sourceHoldId, activeSameHold, firstTime,
    )
    const namedEvent = {
      ...event,
      source_hold_id: sourceHoldId ?? null,
      supplementary_name: supplementaryName,
      step: index + 1,
      key: `动作-${index + 1}-${event.limb}-${event.seek_time_seconds}`,
    }
    namedEvents.push(namedEvent)
    previousHoldByLimb.set(event.limb, Number(event.hold_id))
    return namedEvent
  })
})
const activeActionKey = computed(() => {
  if (isVisualPlayback.value) return ''
  let active = null
  for (const event of actionEvents.value) {
    if (event.seek_time_seconds > playbackTime.value + .04) break
    active = event
  }
  return active?.key || ''
})
const activeActionIndex = computed(() => {
  const index = actionEvents.value.findIndex((event) => event.key === activeActionKey.value)
  return index >= 0 ? index : 0
})
const activeAction = computed(() => isVisualPlayback.value ? null : actionEvents.value[activeActionIndex.value] || null)
const currentPose = computed(() => {
  if (isVisualPlayback.value) return null
  if (!poseSamples.value.length) return null
  let nearest = poseSamples.value[0]
  let delta = Math.abs(Number(nearest.time_seconds) - playbackTime.value)
  for (const sample of poseSamples.value.slice(1)) {
    const nextDelta = Math.abs(Number(sample.time_seconds) - playbackTime.value)
    if (nextDelta < delta) { nearest = sample; delta = nextDelta }
  }
  const sampleFps = Number(analysisEvidence.value?.sampling?.effective_fps || 4)
  if (delta > Math.max(.18, .75 / Math.max(sampleFps, 1))) return null
  return { ...nearest, delta }
})
const currentPoseExact = computed(() => {
  if (!currentPose.value) return false
  const sampleFps = Number(analysisEvidence.value?.sampling?.effective_fps || 4)
  return currentPose.value.delta <= Math.max(.04, .25 / Math.max(sampleFps, 1))
})
const poseEvidenceLabel = computed(() => {
  if (!currentPose.value) return ''
  const confidence = `${Math.round(Number(currentPose.value.confidence || 0) * 100)}%`
  return currentPoseExact.value
    ? `实测采样 · 置信度 ${confidence}`
    : `邻近实测采样 · 非插值 · ${currentPose.value.delta.toFixed(1)} 秒`
})
const skeletonSegments = computed(() => {
  const pose = currentPose.value
  if (!pose) return []
  const points = pose.kpts_xy || []
  const scores = pose.kpts_score || []
  return poseEdges.flatMap(([start, end]) => {
    if (!points[start] || !points[end] || Number(scores[start] || 0) < .15 || Number(scores[end] || 0) < .15) return []
    return [{ key: `${start}-${end}`, x1: points[start][0] * 100, y1: points[start][1] * 100,
      x2: points[end][0] * 100, y2: points[end][1] * 100 }]
  })
})
const posePoints = computed(() => {
  const pose = currentPose.value
  if (!pose) return []
  return (pose.kpts_xy || []).flatMap((point, index) => Number(pose.kpts_score?.[index] || 0) >= .15
    ? [{ key: index, x: point[0] * 100, y: point[1] * 100 }]
    : [])
})
const torsoSourceFrame = computed(() => torsoDisplayFrame(reviewResult.value, false))
const activeContactEvents = computed(() => contactEvents.value.filter((event) => {
  const end = Number.isFinite(Number(event.end_time_seconds)) ? Number(event.end_time_seconds) : Number(event.start_time_seconds)
  return playbackTime.value >= Number(event.start_time_seconds) && playbackTime.value <= end + .08
}))
const currentRun = computed(() => {
  const attempt = activeJob.value?.attempt || 1
  return [...(activeJob.value?.analysis_runs || [])].reverse().find((run) => run.attempt === attempt)
})
const analysisEvidence = computed(() => result.value?.analysis || currentRun.value?.analysis || null)
function poseVersionLabel(value) {
  const spec = value?.models?.pose || value?.analysis?.models?.pose?.name || ''
  const model = typeof spec === 'string' ? spec : spec?.name || ''
  if (model.startsWith('rtmw-l-384x288')) return 'RTMW-L · 本地骨架'
  if (model.startsWith('aliyun-viapi')) return '阿里云骨架 · 历史版本'
  return model ? '历史骨架版本' : '待使用 RTMW-L 分析'
}
const analysisUsage = computed(() => analysisEvidence.value?.usage || {})
const analysisCost = computed(() => analysisEvidence.value?.cost || {})
const analysisTimings = computed(() => analysisEvidence.value?.timings_ms || {})
const trimDuration = computed(() => Math.max(0, Number(trimEndSeconds.value || 0) - Number(trimStartSeconds.value || 0)))
const trimIsValid = computed(() => !videoMeta.value || (trimStartSeconds.value >= 0 && trimEndSeconds.value > trimStartSeconds.value && trimDuration.value <= MAX_VIDEO_SECONDS + .05 && trimEndSeconds.value <= videoMeta.value.duration + .05))
const canSubmitSkeleton = computed(() => selectedFile.value && videoMeta.value && !preparingPreview.value && consentPolicy.value && trimIsValid.value && !isBusy.value && !isSubmitting.value && !isDeleting.value)
const canSubmit = computed(() => selectedFile.value && !preparingPreview.value && routeColor.value && colorSample.value?.source === 'video' && consentPolicy.value && trimIsValid.value && !isBusy.value && !isSubmitting.value && !isDeleting.value)
const statusTitle = computed(() => isJobDeleting.value ? '正在删除整次记录' : ({
  queued: '任务正在排队', running: activeJob.value?.stage || '正在分析视频',
  succeeded: '分析完成', failed: '分析未完成', cancelled: '任务已取消',
  awaiting_hold_review: '等待全部岩点确认',
}[activeJob.value?.status] || '准备中'))
const statusDetail = computed(() => {
  if (isJobDeleting.value) return '正在停止任务并删除原视频、复盘指标与派生文件。'
  if (activeJob.value?.status === 'failed') return activeJob.value.error || '请检查视频和本地骨架模型后重试。'
  if (activeJob.value?.status === 'cancelled') return sourceAvailable.value ? '原视频仍可用于重新分析。' : '原视频已删除，本次任务不能重新分析。'
  if (activeJob.value?.status === 'succeeded') return '结果为机器估算，请结合原视频复核。'
  if (activeJob.value?.status === 'awaiting_hold_review') return '检查岩点后点击“确认全部岩点”，再点击“开始复盘”。'
  if (activeJob.value?.status === 'queued') return uploadProgress.value < 100 ? `视频上传 ${uploadProgress.value}%` : '前方任务完成后会自动开始。'
  return '系统正在处理视频并识别动作；可以稍后在任务列表查看结果。'
})
const sourceRetentionLabel = computed(() => {
  const source = sourceMedia.value
  if (!source) return '未记录原视频保留状态'
  if (source.status === 'deleted') return `已于 ${dateLabel(source.deleted_at)} 删除，复盘指标仍保留`
  return '原片保留中，仅当前账号可见，可主动删除'
})
const overlayRetentionLabel = computed(() => {
  const overlay = overlayMedia.value
  if (!overlay) return '尚未生成'
  if (overlay.status === 'available') return '私密保留，可单独导出或删除'
  if (overlay.status === 'superseded') return '重新分析后旧叠加视频已替换'
  if (overlay.status === 'deleted') return `已于 ${dateLabel(overlay.deleted_at)} 删除`
  return '当前不可用'
})
const elapsedLabel = computed(() => {
  const seconds = result.value?.attempt?.elapsed_seconds
  return Number.isFinite(seconds) ? `${seconds.toFixed(1)} 秒` : '待复核'
})
const limbRows = computed(() => Object.entries(limbNames).map(([key, label]) => {
  const value = result.value?.attempt?.per_limb?.[key]
  return { key, label, seconds: `${Number(value?.contact_seconds || 0).toFixed(1)} 秒`,
    holds: value?.holds?.length ? `岩点 ${value.holds.join('、')}` : '未确认接触' }
}))

function openPicker() { if (editorOpen.value && !window.confirm('更换视频会放弃尚未保存的轮廓，是否继续？')) return; editorOpen.value=false; fileInput.value?.click() }
function applyColorSample(rgb, source, point = null) {
  const nearest = nearestRouteColor(rgb)
  const hex = rgbToHex(rgb)
  routeColor.value = nearest.value
  colorSample.value = {
    source,
    hex,
    rgb: rgb.map((value) => Math.max(0, Math.min(255, Math.round(value)))),
    time_seconds: source === 'video' ? Number((videoElement.value?.currentTime || 0).toFixed(3)) : null,
    point_xy: point,
  }
}
function clearColorSample() {
  routeColor.value = ''
  colorSample.value = null
  cancelColorPicking()
}
async function startColorPicking() {
  const video = videoElement.value
  if (!video || video.readyState < 2 || !video.videoWidth || !video.videoHeight) {
    formError.value = '视频画面尚未就绪，请等待画面出现后再取色。'
    return
  }
  formError.value = ''
  video.pause()
  colorPicking.value = true
  await nextTick()
  const canvas = colorSampleCanvas.value
  const bounds = canvas?.getBoundingClientRect()
  if (!canvas || !bounds?.width || !bounds?.height) return cancelColorPicking()
  const pixelRatio = Math.min(2, window.devicePixelRatio || 1)
  canvas.width = Math.max(1, Math.round(bounds.width * pixelRatio))
  canvas.height = Math.max(1, Math.round(bounds.height * pixelRatio))
  const scale = Math.min(canvas.width / video.videoWidth, canvas.height / video.videoHeight)
  const width = video.videoWidth * scale
  const height = video.videoHeight * scale
  const x = (canvas.width - width) / 2
  const y = (canvas.height - height) / 2
  const context = canvas.getContext('2d', { willReadFrequently:true })
  context.fillStyle = '#111'
  context.fillRect(0, 0, canvas.width, canvas.height)
  context.drawImage(video, x, y, width, height)
  sampledFrameRect = { x, y, width, height }
  canvas.focus()
}
function pickColorFromFrame(event) {
  const canvas = colorSampleCanvas.value
  if (!canvas || !sampledFrameRect) return
  const bounds = canvas.getBoundingClientRect()
  const x = (event.clientX - bounds.left) * canvas.width / bounds.width
  const y = (event.clientY - bounds.top) * canvas.height / bounds.height
  const frame = sampledFrameRect
  if (x < frame.x || x > frame.x + frame.width || y < frame.y || y > frame.y + frame.height) {
    formError.value = '请点击视频画面内的目标岩点。'
    return
  }
  const context = canvas.getContext('2d', { willReadFrequently:true })
  const radius = Math.max(2, Math.round(Math.min(canvas.width, canvas.height) * .004))
  const left = Math.max(0, Math.round(x - radius))
  const top = Math.max(0, Math.round(y - radius))
  const pixels = context.getImageData(left, top, Math.min(radius * 2 + 1, canvas.width - left), Math.min(radius * 2 + 1, canvas.height - top)).data
  const channels = [[], [], []]
  for (let index = 0; index < pixels.length; index += 4) {
    channels[0].push(pixels[index]); channels[1].push(pixels[index + 1]); channels[2].push(pixels[index + 2])
  }
  const median = (values) => values.sort((a, b) => a - b)[Math.floor(values.length / 2)]
  applyColorSample(channels.map(median), 'video', [
    Number(((x - frame.x) / frame.width).toFixed(6)),
    Number(((y - frame.y) / frame.height).toFixed(6)),
  ])
  colorPicking.value = false
  sampledFrameRect = null
  formNotice.value = ''
}
function cancelColorPicking() { colorPicking.value = false; sampledFrameRect = null }
let selectedFileToken = 0
function discardPreparedPreview(){
  const id=preparedPreviewId.value
  preparedPreviewId.value=''
  if(id)climbReplayService.discardVideoPreview(id).catch(()=>{})
}
async function inspectVideo(file) {
  const url = URL.createObjectURL(file)
  const probe = document.createElement('video')
  let timer
  try {
    const metadata = await new Promise((resolve, reject) => {
      timer = window.setTimeout(() => reject(new Error('视频信息读取超时')), 8000)
      probe.preload = 'metadata'
      probe.onloadedmetadata = () => { window.clearTimeout(timer); resolve({ width: probe.videoWidth, height: probe.videoHeight, duration: probe.duration }) }
      probe.onerror = () => { window.clearTimeout(timer); reject(new Error('浏览器无法预览此视频编码')) }
      probe.src = url
    })
    if (!metadata.width || !metadata.height || !Number.isFinite(metadata.duration)) throw new Error('无法读取视频尺寸或时长，请重新选择文件。')
    return metadata
  } finally {
    window.clearTimeout(timer)
    probe.onloadedmetadata = null
    probe.onerror = null
    probe.removeAttribute('src')
    probe.load()
    URL.revokeObjectURL(url)
  }
}
async function useFile(file) {
  formError.value = ''
  formNotice.value = ''
  if (!file) return
  const supportedTypes = new Set(['video/mp4', 'video/quicktime', 'video/x-m4v', 'video/webm', 'video/3gpp', 'video/3gpp2', 'video/x-matroska'])
  const supportedExtensions = ['.mp4','.mov','.m4v','.webm','.3gp','.3g2','.mkv','.avi','.mpg','.mpeg','.mpe','.ts','.mts','.m2ts','.m2t','.wmv','.asf','.flv','.f4v','.vob','.ogv','.ogg','.mxf','.divx']
  if (!file.type.toLowerCase().startsWith('video/') && !supportedTypes.has(file.type.toLowerCase()) && !supportedExtensions.some((extension) => file.name.toLowerCase().endsWith(extension))) {
    formError.value = '请选择常见视频文件，如 MP4、MOV、MKV、AVI、WebM、MTS、MPEG 或 WMV。'
    return
  }
  if (file.size > MAX_INPUT_BYTES) {
    formError.value = '视频不能超过 500 MB。'
    return
  }
  const token = ++selectedFileToken
  discardPreparedPreview()
  previewController?.abort()
  previewController = new AbortController()
  if (previewUrl.value) URL.revokeObjectURL(previewUrl.value)
  selectedFile.value = file
  previewUrl.value = ''
  preparingPreview.value = true
  playbackStatus.value = 'loading'
  playbackFailure.value = ''
  videoMeta.value = null
  trimStartSeconds.value = 0
  trimEndSeconds.value = MAX_VIDEO_SECONDS
  activeJob.value = null
  deletionReceipt.value = null
  playbackTime.value = 0
  preferredPlaybackKind.value = 'overlay'
  pendingPlaybackState.value = null
  window.clearTimeout(deletionTimer)
  clearColorSample()
  try {
    const {blob,sourceDuration,preparedId} = await climbReplayService.prepareVideoPreview(file,previewController.signal)
    if(token!==selectedFileToken){if(preparedId)climbReplayService.discardVideoPreview(preparedId).catch(()=>{});return}
    preparedPreviewId.value=preparedId
    const metadata = await inspectVideo(blob)
    if (token !== selectedFileToken) return
    previewUrl.value = URL.createObjectURL(blob)
    videoMeta.value = {...metadata,duration:Number.isFinite(sourceDuration) && sourceDuration>0 ? sourceDuration : metadata.duration}
    trimEndSeconds.value = Math.min(MAX_VIDEO_SECONDS, videoMeta.value.duration)
    formNotice.value = ''
  } catch (error) {
    if (token !== selectedFileToken) return
    failPlayback(error?.response?.data?.detail || error?.message || '本机未能准备视频，请重新选择后重试。')
  } finally { if(token===selectedFileToken)preparingPreview.value=false }
}
function onFileChange(event) { void useFile(event.target.files?.[0]); event.target.value = '' }
function onDrop(event) { isDragging.value = false; void useFile(event.dataTransfer.files?.[0]) }
async function loadTestVideoInfo() {
  try {
    const response = await climbReplayService.testVideos()
    testVideoCases.value = Array.isArray(response?.items) ? response.items : []
  } catch (_) { testVideoCases.value = [] }
}
async function useTestVideo(testCase) {
  if (loadingTestCaseId.value || !testCase?.id) return
  loadingTestCaseId.value = testCase.id
  formError.value = ''
  formNotice.value = ''
  try {
    const blob = await climbReplayService.testVideo(testCase.id)
    await useFile(new File([blob], testCase.filename || `${testCase.id}.mp4`, {
      type: 'video/mp4', lastModified: Date.now(),
    }))
    if(videoMeta.value)formNotice.value = `已载入${testCase.label}。请从画面取色后点击识别岩点。`
  } catch (error) {
    formError.value = error?.response?.status === 404
      ? '本机测试视频不可用，请重新启动本地服务后再试。'
      : errorText(error)
  } finally { loadingTestCaseId.value = '' }
}
function errorText(error) {
  if (error?.response?.status === 404) return '本地复盘服务尚未启用，请重新启动本地服务。'
  return error?.response?.data?.detail || error?.message || '操作失败，请稍后重试。'
}
async function submit(skipHolds = false) {
  if (skipHolds ? !canSubmitSkeleton.value : !canSubmit.value) return
  if (!skipHolds && colorSample.value?.source === 'video' && videoMeta.value?.duration > MAX_VIDEO_SECONDS &&
      (colorSample.value.time_seconds < Number(trimStartSeconds.value) ||
       colorSample.value.time_seconds > Number(trimEndSeconds.value))) {
    formError.value = '样本岩点不在保留的视频片段内，请调整裁剪范围或重新点选。'
    return
  }
  formError.value = ''
  uploadProgress.value = 0
  isSubmitting.value = true
  try {
    activeJob.value = await climbReplayService.create({
      video: selectedFile.value,
      preparedId: preparedPreviewId.value,
      skipHolds,
      routeColor: routeColor.value,
      routeColorSample: colorSample.value,
      consentVersion: consentPolicy.value.version,
      consentGranted: true,
      retentionMode: retentionMode.value,
      trimStartSeconds: videoMeta.value?.duration > MAX_VIDEO_SECONDS ? Number(trimStartSeconds.value) : 0,
      trimEndSeconds: videoMeta.value?.duration > MAX_VIDEO_SECONDS ? Number(trimEndSeconds.value) : null,
    }, (value) => { uploadProgress.value = value })
    preparedPreviewId.value=''
    if (previewUrl.value) URL.revokeObjectURL(previewUrl.value)
    previewUrl.value = ''
    selectedFile.value = null
    videoMeta.value = null
    colorSample.value = null
    await loadJobs()
    schedulePoll()
  } catch (error) { formError.value = errorText(error) }
  finally { isSubmitting.value = false }
}
function schedulePoll() {
  window.clearTimeout(pollTimer)
  if ((!isBusy.value && !visualState.value.busy) || !activeJob.value?.id || isJobDeleting.value) return
  const jobId = activeJob.value.id
  pollTimer = window.setTimeout(async () => {
    try {
      const updated = await climbReplayService.get(jobId)
      if (activeJob.value?.id !== jobId) return
      const wasMakingVisual = visualState.value.busy
      activeJob.value = updated
      if (wasMakingVisual && visualState.value.ready) {
        pendingPlaybackState.value = capturePlaybackState()
        nextTick(() => videoElement.value?.load())
      }
      if (!isBusy.value && !visualState.value.busy) await loadJobs()
    } catch (error) { formError.value = errorText(error) }
    schedulePoll()
  }, 1200)
}
async function retryVisualReplay() {
  if (!activeJob.value?.id || !visualState.value.canRetry || visualReplaySubmitting.value) return
  const jobId = activeJob.value.id
  visualReplaySubmitting.value = true
  visualReplayError.value = ''
  try {
    const updated = await climbReplayService.retryVisualReplay(jobId)
    if (activeJob.value?.id !== jobId) return
    activeJob.value = updated
    schedulePoll()
  } catch (error) {
    if (activeJob.value?.id === jobId) visualReplayError.value = errorText(error) || '线路回放暂时无法开始，请稍后重试。'
  } finally { visualReplaySubmitting.value = false }
}
async function cancelVisualReplay() {
  if (!activeJob.value?.id || !visualState.value.busy || visualReplaySubmitting.value) return
  const jobId = activeJob.value.id
  visualReplaySubmitting.value = true
  visualReplayError.value = ''
  try {
    const updated = await climbReplayService.cancel(jobId)
    if (activeJob.value?.id !== jobId) return
    activeJob.value = updated
    schedulePoll()
  } catch (error) {
    if (activeJob.value?.id === jobId) visualReplayError.value = errorText(error) || '暂时无法停止制作，请稍后重试。'
  } finally { visualReplaySubmitting.value = false }
}
function clearDeletedReplay() {
  discardPreparedPreview()
  selectedFileToken += 1
  previewController?.abort()
  preparingPreview.value = false
  activeJob.value = null
  selectedFile.value = null
  videoMeta.value = null
  if (previewUrl.value) URL.revokeObjectURL(previewUrl.value)
  previewUrl.value = ''
  playbackTime.value = 0
  preferredPlaybackKind.value = 'overlay'
  pendingPlaybackState.value = null
}
function returnToStart() {
  unifiedPlayer.value?.pauseForHoldReview?.()
  window.clearTimeout(pollTimer)
  window.clearTimeout(deletionTimer)
  selectedFileToken++
  clearDeletedReplay()
  clearColorSample()
  deletionReceipt.value = null
  holdRepairOpen.value = false
  holdReviewMode.value = false
  holdPreview.value = null
  editorOpen.value = false
  formError.value = ''
  formNotice.value = ''
  historyOpen.value = false
  window.scrollTo({ top: 0, behavior: 'smooth' })
}
function scheduleDeletionPoll(jobId) {
  window.clearTimeout(deletionTimer)
  if (!jobId || deletionReceipt.value?.state !== 'queued') return
  deletionTimer = window.setTimeout(async () => {
    try {
      deletionReceipt.value = await climbReplayService.deletion(jobId)
      if (deletionReceipt.value.state === 'completed') {
        clearDeletedReplay()
        formNotice.value = '整次复盘已删除，删除回执已生成。本机原始文件不受影响。'
        await loadJobs()
        return
      }
      if (deletionReceipt.value.state === 'failed') {
        formError.value = deletionReceipt.value.error || '删除未完成，请稍后重试。'
        return
      }
    } catch (error) {
      formError.value = errorText(error)
      return
    }
    scheduleDeletionPoll(jobId)
  }, 800)
}
async function cancelJob() {
  if (!activeJob.value?.id) return
  try { activeJob.value = await climbReplayService.cancel(activeJob.value.id); await loadJobs() }
  catch (error) { formError.value = errorText(error) }
}
async function retryJob() {
  if (!activeJob.value?.id) return
  if (!consentPolicy.value) {
    formError.value = '请等待本次处理说明加载完成。'
    return
  }
  formError.value = ''
  formNotice.value = ''
  try {
    activeJob.value = await climbReplayService.retry(activeJob.value.id, consentPolicy.value.version)
    schedulePoll()
    await loadJobs()
  }
  catch (error) { formError.value = errorText(error) }
}
async function deleteSourceVideo() {
  if (!activeJob.value?.id || isDeleting.value) return
  if (!window.confirm('将永久删除原视频，保留复盘指标。删除后该任务不能重新分析。确认删除？')) return
  isDeleting.value = true
  formError.value = ''
  formNotice.value = ''
  try {
    activeJob.value = await climbReplayService.deleteSource(activeJob.value.id)
    formNotice.value = '原视频已删除，复盘指标和处理记录仍保留。'
    await loadJobs()
  } catch (error) { formError.value = errorText(error) }
  finally { isDeleting.value = false }
}
async function deleteOverlayVideo() {
  if (!activeJob.value?.id || isDeleting.value || !overlayAvailable.value) return
  if (!window.confirm('将永久删除可导出的叠加视频，原视频、姿态数据和复盘指标仍会保留。确认删除？')) return
  isDeleting.value = true
  formError.value = ''
  formNotice.value = ''
  try {
    activeJob.value = await climbReplayService.deleteOverlay(activeJob.value.id)
    formNotice.value = '叠加视频已删除，原视频和复盘指标仍保留。'
    await loadJobs()
  } catch (error) { formError.value = errorText(error) }
  finally { isDeleting.value = false }
}
async function deleteEntireReplay() {
  if (!activeJob.value?.id || isDeleting.value || isJobDeleting.value) return
  if (!window.confirm('将永久删除原视频、姿态、事件、指标和派生文件。此操作不可恢复。确认删除整次记录？')) return
  const jobId = activeJob.value.id
  isDeleting.value = true
  formError.value = ''
  formNotice.value = ''
  window.clearTimeout(pollTimer)
  try {
    deletionReceipt.value = await climbReplayService.deleteJob(jobId)
    if (deletionReceipt.value.state === 'completed') {
      clearDeletedReplay()
      await loadJobs()
      formNotice.value = '整次复盘已删除，删除回执已生成。本机原始文件不受影响。'
    } else {
      scheduleDeletionPoll(jobId)
    }
  } catch (error) { formError.value = errorText(error) }
  finally { isDeleting.value = false }
}
async function refreshRouteMap() {
  if (!activeJob.value || routeMapRefreshing.value) return
  const jobId = activeJob.value.id
  routeMapRefreshing.value = true
  formError.value = ''
  unifiedPlayer.value?.pauseForHoldReview()
  try {
    const updated = await climbReplayService.refreshRouteMap(jobId)
    if (activeJob.value?.id === jobId) {
      activeJob.value = updated
      routeMapPlayerVersion.value++
      holdReviewNotice.value = '岩点图已本地重新生成：只高亮当前四肢所在岩点，旧视频保留，未新增识别费用。'
    }
    await loadJobs()
  } catch (error) {
    if (activeJob.value?.id === jobId) formError.value = errorText(error)
  } finally {
    routeMapRefreshing.value = false
  }
}

function selectJob(job) {
  if (editorOpen.value && !window.confirm('切换记录会放弃尚未保存的轮廓，是否继续？')) return
  selectedFileToken += 1
  discardPreparedPreview()
  previewController?.abort()
  preparingPreview.value = false
  editorOpen.value = false
  selectedHoldId.value = ''
  holdRepairOpen.value = false
  visualReplayError.value = ''
  coachingClipEnd.value = null
  holdReviewMode.value = false
  holdPreview.value = null
  holdDraw.value = null
  holdRegionForm.value = { left:null, top:null, right:null, bottom:null }
  holdReviewError.value = ''
  holdReviewNotice.value = ''
  inspectedHoldReviewVersion.value = null
  reviewingSegmentId.value = ''
  reviewError.value = ''
  comparisonPartnerId.value = ''
  sameClimberConfirmed.value = false
  segmentComparison.value = null
  comparisonError.value = ''
  if (previewUrl.value) URL.revokeObjectURL(previewUrl.value)
  previewUrl.value = ''
  selectedFile.value = null
  videoMeta.value = null
  playbackTime.value = 0
  preferredPlaybackKind.value = 'overlay'
  pendingPlaybackState.value = null
  activeJob.value = job
  deletionReceipt.value = job.deletion || null
  formError.value = ''
  formNotice.value = ''
  if (isJobDeleting.value) scheduleDeletionPoll(job.id)
  else schedulePoll()
  window.scrollTo({ top: 0, behavior: 'smooth' })
}
async function loadConsentPolicy() {
  try { consentPolicy.value = await climbReplayService.consentPolicy() }
  catch (error) { formError.value = errorText(error) || '暂时无法加载数据处理告知。' }
}
async function loadJobs() {
  try { recentJobs.value = await climbReplayService.list() }
  catch (error) { if (error?.response?.status !== 404) formError.value = errorText(error) }
}
function holdPolygon(hold) {
  return Array.isArray(hold.polygon) && hold.polygon.length >= 3 && hold.polygon.every(p => Array.isArray(p) && p.length >= 2 && p.every(Number.isFinite)) ? hold.polygon : []
}
const contourPoints = polygon => polygon.map(p => `${p[0] * 100},${p[1] * 100}`).join(' ')
function holdLabelPosition(hold) {
  const polygon = holdPolygon(hold)
  if (polygon.length) return [polygon.reduce((n,p) => n+p[0],0)/polygon.length*100, Math.min(...polygon.map(p=>p[1]))*100]
  const [x,y,w,h] = hold.bbox || [0,0,0,0]
  return [(x+w/2)*100,(y+h/2)*100]
}
const selectedCanvasHoldHasContour = computed(() => holdPolygon((reviewResult.value?.holds || []).find(h => String(h.id) === selectedHoldId.value) || {}).length > 0)
const canvasActionsStyle = computed(() => {
  const selected = (reviewResult.value?.holds || []).find(h => String(h.id) === selectedHoldId.value)
  const polygon = holdPreview.value?.source_polygon || holdPolygon(selected || {})
  const bottom = polygon.length ? Math.max(...polygon.map(p => p[1])) : selected?.bbox ? selected.bbox[1] + selected.bbox[3] : 0
  const projectedBottom = reviewView.value.height ? (reviewView.value.y + bottom * reviewView.value.height * reviewDisplayZoom.value) / reviewView.value.height : bottom
  return projectedBottom > .7 ? { top:'12px', bottom:'auto' } : {}
})
function selectCanvasHold(hold) {
  if (holdReviewSaving.value || holdPreviewLoading.value || holdPreview.value) return
  videoElement.value?.pause()
  selectedHoldId.value = String(hold.id)
}
function selectHoldAtClientPoint(event) {
  if (!showHolds.value || !videoElement.value) return
  const rect=videoElement.value.getBoundingClientRect(), x=(event.clientX-rect.left)/rect.width, y=(event.clientY-rect.top)/rect.height
  const hold=[...(reviewResult.value?.holds || [])].reverse().find(hold=>{
    const polygon=holdPolygon(hold)
    if (!polygon.length) { const [left,top,width,height]=hold.bbox || [];return x>=left && x<=left+width && y>=top && y<=top+height }
    let inside=false
    for(let i=0,j=polygon.length-1;i<polygon.length;j=i++){
      const [xi,yi]=polygon[i], [xj,yj]=polygon[j]
      if ((yi>y)!==(yj>y) && x<(xj-xi)*(y-yi)/(yj-yi)+xi) inside=!inside
    }
    return inside
  })
  if(hold)selectCanvasHold(hold)
}
function updatePlaybackEvidence() {
  playbackTime.value = Number(videoElement.value?.currentTime || 0)
  if (visualState.value.stale && isVisualPlayback.value && videoElement.value) {
    videoElement.value.pause()
    videoElement.value.currentTime = analysisSeekTime(activeJob.value, visualState.value.start)
    playbackTime.value = videoElement.value.currentTime
  }
  if (coachingClipEnd.value !== null && playbackTime.value >= coachingClipEnd.value) {
    videoElement.value?.pause()
    coachingClipEnd.value = null
  }
  if (holdPreview.value && Math.abs(playbackTime.value - holdPreview.value.time_seconds) > .1) holdPreview.value = null
}
function capturePlaybackState() {
  const video = videoElement.value
  return {
    time: Number(video?.currentTime || playbackTime.value || 0),
    shouldPlay: Boolean(video && !video.paused && !video.ended),
  }
}
function switchPlayback(kind) {
  if (kind === playbackKind.value) return
  if (kind === 'overlay' && !replayVideoAvailable.value) return
  if (kind === 'source' && !sourcePlayable.value) return
  if (kind !== 'source') { holdPreview.value = null; holdDraw.value = null; holdReviewMode.value = false }
  pendingPlaybackState.value = capturePlaybackState()
  preferredPlaybackKind.value = kind
  formNotice.value = ''
  nextTick(() => videoElement.value?.load())
}
function viewVisualReplay() {
  if (!visualState.value.ready || !replayVideoAvailable.value || !videoElement.value) return
  coachingClipEnd.value = null
  holdPreview.value = null
  holdDraw.value = null
  holdReviewMode.value = false
  if (playbackKind.value !== 'overlay') {
    pendingPlaybackState.value = { time: visualState.value.start, shouldPlay: true }
    preferredPlaybackKind.value = 'overlay'
    nextTick(() => videoElement.value?.load())
  } else {
    videoElement.value.currentTime = visualState.value.start
    updatePlaybackEvidence()
    videoElement.value.play().catch(() => {})
  }
  videoElement.value.focus()
}
function openHoldRepair() {
  if (!canAddHoldAtPoint.value) return
  const time = unifiedPlayer.value?.pauseForHoldReview() || 0
  holdRepairOpen.value = true
  preferredPlaybackKind.value = 'source'
  pendingPlaybackState.value = { time, shouldPlay:false }
  holdReviewMode.value = true
  holdPreview.value = null
  holdDraw.value = null
  showHolds.value = true
  showPose.value = false
  showEvents.value = false
  nextTick(() => videoElement.value?.load())
}
function inspectSelectedHold() {
  if (!selectedHoldId.value || !sourcePlayable.value) return
  const fps = Number(activeJob.value?.video?.fps) || 1
  const time = Number(reviewResult.value?.hold_evidence?.reference_frame || 0) / fps
  holdRepairOpen.value = true
  holdReviewMode.value = false
  holdPreview.value = null
  showHolds.value = true
  showPose.value = false
  showEvents.value = false
  preferredPlaybackKind.value = 'source'
  pendingPlaybackState.value = { time, shouldPlay:false }
  nextTick(() => videoElement.value?.load())
}
async function removeSelectedHold() {
  if (!selectedHoldId.value || !canAddHoldAtPoint.value || holdReviewSaving.value) return
  const jobId = activeJob.value.id
  holdReviewSaving.value = true
  holdReviewError.value = ''
  try {
    const updated = await climbReplayService.removeHold(jobId, selectedHoldId.value)
    if (activeJob.value?.id !== jobId) return
    activeJob.value = updated
    selectedHoldId.value = ''
    holdReviewNotice.value = '已删除岩点并保存草稿，请继续检查并确认全部岩点。'
    await loadJobs()
  } catch (error) { holdReviewError.value = errorText(error) }
  finally { holdReviewSaving.value = false }
}
async function confirmAllHolds() {
  if (!canAddHoldAtPoint.value || holdReviewSaving.value || holdPreview.value) return
  const jobId = activeJob.value.id
  holdReviewSaving.value = true
  holdReviewError.value = ''
  const needsLocalAnalysis = !!activeJob.value.holds_pending_local_analysis
  localHoldAnalysisRunning.value = needsLocalAnalysis
  try {
    const updated = await climbReplayService.confirmAllHolds(jobId, activeJob.value.holds_revision)
    if (activeJob.value?.id !== jobId) return
    activeJob.value = updated
    holdReviewMode.value = false
    holdReviewNotice.value = needsLocalAnalysis ? '全部岩点已确认，本地分析已完成，未新增姿态请求。' : '全部岩点已确认，点击“开始复盘”。'
    await loadJobs()
  } catch (error) { holdReviewError.value = errorText(error) }
  finally { holdReviewSaving.value = false; localHoldAnalysisRunning.value = false }
}
async function startAnalysis(skipHolds = false) {
  if (skipHolds ? !canStartSkeleton.value : !canStartAnalysis.value) return
  const jobId = activeJob.value.id
  isSubmitting.value = true
  formError.value = ''
  try {
    const updated = await climbReplayService.startAnalysis(jobId, consentPolicy.value.version, { pose_fps: 10, focus_windows: [], skip_holds: skipHolds })
    if (activeJob.value?.id !== jobId) return
    activeJob.value = updated
    holdRepairOpen.value = false
    holdReviewMode.value = false
    holdPreview.value = null
    schedulePoll()
    await loadJobs()
  } catch (error) { formError.value = errorText(error) }
  finally { isSubmitting.value = false }
}
function closeHoldRepair() {
  videoElement.value?.pause()
  holdReviewMode.value = false
  holdPreview.value = null
  holdDraw.value = null
  preferredPlaybackKind.value = 'overlay'
  holdRepairOpen.value = false
}
function toggleHoldReview() {
  holdReviewError.value = ''
  holdReviewNotice.value = ''
  holdReviewMode.value = !holdReviewMode.value
  holdPreview.value = null
  holdDraw.value = null
  if (holdReviewMode.value) {
    selectedHoldId.value = ''
    videoElement.value?.pause()
    showPose.value = false
    showEvents.value = false
    switchPlayback('source')
  }
}
function holdPointerPosition(event) {
  const rect = event.currentTarget.getBoundingClientRect()
  return [Math.max(0, Math.min(1, (event.clientX - rect.left) / rect.width)),
    Math.max(0, Math.min(1, (event.clientY - rect.top) / rect.height))]
}
function startHoldDraw(event) {
  if (reviewZoomAnimating.value || !holdReviewMode.value || holdReviewSaving.value || holdPreviewLoading.value || !activeJob.value?.id) return
  if (event.pointerType === 'mouse' && event.button !== 0) return
  event.preventDefault()
  const position = holdPointerPosition(event)
  selectedHoldId.value = ''
  holdDraw.value = { pointerId:event.pointerId, start:position, end:position }
  holdReviewError.value = ''
  event.currentTarget.setPointerCapture(event.pointerId)
}
function moveHoldDraw(event) {
  if (holdDraw.value?.pointerId !== event.pointerId) return
  holdDraw.value = { ...holdDraw.value, end:holdPointerPosition(event) }
}
function cancelHoldDraw() { holdDraw.value = null }
function focusHoldCoordinateInputs() {
  if (holdCoordinateDetails.value) holdCoordinateDetails.value.open = true
  nextTick(() => holdCoordinateFirstInput.value?.focus())
}
function previewHoldFromFields() {
  const { left, top, right, bottom } = holdRegionForm.value
  const values = [left, top, right, bottom].map(Number)
  if (values.some((value) => !Number.isFinite(value) || value < 0 || value > 100)
      || values[2] - values[0] < 1.5 || values[3] - values[1] < 1.5
      || values[2] - values[0] > 35 || values[3] - values[1] > 35) {
    holdReviewError.value = '请填写单个岩点的左、上、右、下范围（百分比）。'
    return
  }
  previewHoldRegion(values.map((value) => value / 100))
}
function finishHoldDraw(event) {
  if (holdDraw.value?.pointerId !== event.pointerId) return
  const start = holdDraw.value.start
  const end = holdPointerPosition(event)
  holdDraw.value = null
  if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId)
  const region = [Math.min(start[0], end[0]), Math.min(start[1], end[1]),
    Math.max(start[0], end[0]), Math.max(start[1], end[1])]
  const rect=event.currentTarget.getBoundingClientRect()
  if(Math.hypot((end[0]-start[0])*rect.width,(end[1]-start[1])*rect.height)<6){selectHoldAtClientPoint(event);return}
  if (region[2] - region[0] < .015 || region[3] - region[1] < .015) {
    holdReviewError.value = '请拖动框住整个岩点，单击不足以确定范围。'
    return
  }
  previewHoldRegion(region)
}
async function previewHoldRegion(region) {
  if (!holdReviewMode.value || holdReviewSaving.value || holdPreviewLoading.value || !activeJob.value?.id) return
  const point = [(region[0] + region[2]) / 2, (region[1] + region[3]) / 2]
  const previousTime = Number(videoElement.value?.currentTime || 0)
  const jobId = activeJob.value.id
  holdPreviewLoading.value = true
  holdReviewError.value = ''
  holdReviewNotice.value = ''
  try {
    const proposal = await climbReplayService.previewHoldAtPoint(jobId, point, previousTime, region)
    if (activeJob.value?.id !== jobId || !holdReviewMode.value) return
    holdPreview.value = { ...proposal, point_xy:point, region_xyxy:region, time_seconds:previousTime }
    await nextTick()
    holdConfirmationButton.value?.focus({ preventScroll:true })
  } catch (error) {
    holdReviewError.value = error.response?.data?.detail || errorText(error) || '框内没有找到可靠岩点，请框紧一些或换帧。'
  } finally { holdPreviewLoading.value = false }
}
async function confirmHoldPreview() {
  if (!holdPreview.value || holdReviewSaving.value || !activeJob.value?.id) return
  const { point_xy:point, region_xyxy:region, time_seconds:previousTime, proposal_id:proposalId } = holdPreview.value
  const jobId = activeJob.value.id
  holdReviewSaving.value = true
  holdReviewError.value = ''
  try {
    const updated = await climbReplayService.addHoldAtPoint(jobId, point, previousTime, region, proposalId)
    if (activeJob.value?.id !== jobId) return
    activeJob.value = updated
    holdPreview.value = null
    holdReviewMode.value = false
    inspectedHoldReviewVersion.value = activeJob.value.hold_review_history?.at(-1)?.version || null
    pendingPlaybackState.value = { time:previousTime, shouldPlay:false }
    holdReviewNotice.value = '已补入岩点并保存草稿，可继续补点；全部补完后再确认并分析。'
    await loadJobs()
    nextTick(() => videoElement.value?.load())
  } catch (error) {
    holdReviewError.value = error.response?.data?.detail || errorText(error) || '补点失败，请重选画面再试。'
  } finally { holdReviewSaving.value = false }
}
function holdPositionLabel(point) {
  const x = Number(point?.[0])
  const y = Number(point?.[1])
  if (!Number.isFinite(x) || !Number.isFinite(y)) return '画面位置未记录'
  const horizontal = x < .33 ? '左' : x > .67 ? '右' : '中'
  const vertical = y < .33 ? '上' : y > .67 ? '下' : '部'
  return `画面${horizontal}${vertical} · 横向 ${Math.round(x * 100)}% / 纵向 ${Math.round(y * 100)}%`
}
function inspectClickedHold(operation) {
  if (!operation.active || !sourcePlayable.value) return
  unifiedPlayer.value?.pauseForHoldReview()
  holdRepairOpen.value = true
  holdReviewMode.value = false
  inspectedHoldReviewVersion.value = operation.version
  const time = Number(operation.time_seconds || 0)
  pendingPlaybackState.value = { time, shouldPlay:false }
  preferredPlaybackKind.value = 'source'
  nextTick(() => {
    videoElement.value?.pause()
    videoElement.value?.load()
    videoElement.value?.scrollIntoView({ behavior:'smooth', block:'center' })
  })
}
async function undoClickedHold(operation) {
  if (!operation?.active || !canUndoManualHold.value || holdReviewSaving.value || !activeJob.value?.id) return
  const jobId = activeJob.value.id
  const previousTime = Number(videoElement.value?.currentTime || 0)
  holdReviewSaving.value = true
  holdReviewError.value = ''
  holdReviewNotice.value = ''
  try {
    const updated = await climbReplayService.undoClickedHold(jobId, operation.version)
    if (activeJob.value?.id !== jobId) return
    activeJob.value = updated
    holdReviewMode.value = false
    inspectedHoldReviewVersion.value = null
    pendingPlaybackState.value = { time:previousTime, shouldPlay:false }
    holdReviewNotice.value = `已撤销第 ${operation.ordinal} 次补点并保存草稿；其他补点保留，全部补完后再确认并分析。`
    await loadJobs()
    nextTick(() => videoElement.value?.load())
  } catch (error) {
    if (activeJob.value?.id !== jobId) return
    if (error.response?.status === 409) {
      try { activeJob.value = await climbReplayService.get(jobId); await loadJobs() } catch (_) {}
    }
    holdReviewError.value = error.response?.data?.detail || errorText(error) || '撤销补点失败，请刷新后重试。'
  } finally { holdReviewSaving.value = false }
}
async function refineSampledHolds() {
  if (!canRefineSampledHolds.value || holdReviewSaving.value || !activeJob.value?.id) return
  const jobId = activeJob.value.id
  holdReviewSaving.value = true
  holdReviewError.value = ''
  holdReviewNotice.value = ''
  try {
    const previousTime = Number(videoElement.value?.currentTime || 0)
    const updated = await climbReplayService.refineSampledHolds(jobId)
    if (activeJob.value?.id !== jobId) return
    activeJob.value = updated
    holdReviewMode.value = false
    pendingPlaybackState.value = { time:previousTime, shouldPlay:false }
    holdReviewNotice.value = `草稿保留 ${reviewResult.value.hold_refinement.after} 个岩点（原为 ${reviewResult.value.hold_refinement.before} 个）。请补齐漏点后确认全部岩点，再本地分析。`
    await loadJobs()
    nextTick(() => videoElement.value?.load())
  } catch (error) {
    if (activeJob.value?.id !== jobId) return
    if (error.response?.status === 409) {
      try {
        activeJob.value = await climbReplayService.get(jobId)
        await loadJobs()
      } catch (_) { /* Keep the original failure message if refresh is unavailable. */ }
    }
    holdReviewError.value = error.response?.data?.detail || errorText(error) || '清理杂点失败，请刷新后重试。'
  } finally { holdReviewSaving.value = false }
}
function handlePlaybackLoaded(event) {
  if (!isCurrentPlayback(event)) return
  const video = videoElement.value
  if (video?.videoWidth && video?.videoHeight) videoDimensions.value = { width:video.videoWidth, height:video.videoHeight }
  if (video && (!video.videoWidth || !video.videoHeight)) {
    failPlayback('当前浏览器未能读取视频画面，可能不支持此文件的编码。可换用 H.264 MP4 视频。')
  } else handlePlaybackReady()
  if (video && result.value) video.playbackRate = .75
  const state = pendingPlaybackState.value
  if (video && state) {
    const duration = Number(video.duration)
    const maxTime = Number.isFinite(duration) ? Math.max(0, duration - .05) : state.time
    video.currentTime = Math.max(0, Math.min(state.time, maxTime))
    pendingPlaybackState.value = null
    if (state.shouldPlay) video.play().catch(() => {})
  }
  updatePlaybackEvidence()
}
function isCurrentPlayback(event) {
  return !event || (event.target === videoElement.value && playbackUrl.value &&
    event.target.currentSrc === new URL(playbackUrl.value, window.location.href).href)
}
function failPlayback(message) {
  window.clearTimeout(playbackLoadTimer)
  playbackStatus.value = 'unavailable'
  playbackFailure.value = message
  cancelColorPicking()
}
function handlePlaybackLoading(event) {
  if(preparingPreview.value){window.clearTimeout(playbackLoadTimer);playbackStatus.value='loading';return}
  if (!playbackUrl.value || !isCurrentPlayback(event)) return
  window.clearTimeout(playbackLoadTimer)
  playbackStatus.value = 'loading'
  playbackFailure.value = ''
  const url = playbackUrl.value
  playbackLoadTimer = window.setTimeout(() => {
    if (url !== playbackUrl.value) return
    const video = videoElement.value
    if (video?.readyState >= 2 && video.videoWidth && video.videoHeight) handlePlaybackReady()
    else failPlayback('画面加载超时。请重新加载；如果仍无画面，可换用 H.264 MP4 视频。')
  }, 12000)
}
function handlePlaybackReady(event) {
  if (!isCurrentPlayback(event)) return
  const video = videoElement.value
  if (!video || video.readyState < 2 || !video.videoWidth || !video.videoHeight) return
  window.clearTimeout(playbackLoadTimer)
  playbackStatus.value = 'ready'
  playbackFailure.value = ''
}
function handlePlaybackStalled(event) {
  // A stalled download can also mean the browser has already buffered enough.
  if (event.target.readyState < 2) handlePlaybackLoading(event)
}
function retryPlayback() {
  if(selectedFile.value && !previewUrl.value){void useFile(selectedFile.value);return}
  handlePlaybackLoading()
  videoElement.value?.load()
}
function handlePlaybackError(event) {
  if (!isCurrentPlayback(event)) return
  if (playbackKind.value !== 'overlay' || !sourcePlayable.value) {
    const code = videoElement.value?.error?.code
    failPlayback(code === 2
      ? '视频读取中断，请检查连接后重新加载。'
      : code === 1
        ? '视频读取已中断，请重新加载画面。'
        : '当前浏览器无法解码此视频，或文件内容不完整。可换用 H.264 MP4 视频。')
    return
  }
  pendingPlaybackState.value = capturePlaybackState()
  preferredPlaybackKind.value = 'source'
  formNotice.value = '复盘视频暂时无法加载，已自动切换到原视频。'
  nextTick(() => videoElement.value?.load())
}
function seekToEvent(event) {
  if (!videoElement.value) return
  coachingClipEnd.value = null
  videoElement.value.pause()
  videoElement.value.currentTime = analysisSeekTime(activeJob.value, event.seek_time_seconds)
  updatePlaybackEvidence()
  videoElement.value.focus()
}
function seekCoachingClip({ start_seconds, end_seconds }) {
  if (!videoElement.value || !Number.isFinite(start_seconds)) return
  seekToEvent({ seek_time_seconds: start_seconds })
  coachingClipEnd.value = Number.isFinite(end_seconds) && end_seconds > start_seconds
    ? Math.min(end_seconds, analysisDuration(activeJob.value) ?? end_seconds) : analysisDuration(activeJob.value)
  videoElement.value.scrollIntoView({ block: 'center', behavior: 'auto' })
  videoElement.value.play().catch(() => {})
}
function stepAction(offset) {
  const target = actionEvents.value[activeActionIndex.value + offset]
  if (target) seekToEvent(target)
}
function replayActiveAction() {
  if (!activeAction.value || !videoElement.value) return
  seekToEvent(activeAction.value)
  videoElement.value.play().catch(() => {})
}
function actionAriaLabel(event) {
  return `跳转到第 ${event.step} 个动作，${limbNames[event.limb] || '手脚'}，${event.supplementary_name}，${formatClock(event.seek_time_seconds)}`
}
function actionEndTime(event) {
  const endTime = Number(event.end_time_seconds)
  if (Number.isFinite(endTime)) return endTime
  const endFrame = Number(event.end_source_frame)
  const fps = Number(result.value?.video?.fps || 0)
  return Number.isFinite(endFrame) && fps > 0 ? endFrame / fps : event.seek_time_seconds
}
function inferSupplementaryActionName(event, sourceHoldId, activeSameHold, firstTime) {
  const holdId = Number(event.hold_id)
  if (Math.abs(event.seek_time_seconds - firstTime) < .001) return `起步接触 ${holdId}`
  if (activeSameHold) {
    const limbKind = event.limb?.endsWith('hand') ? 'hand' : 'foot'
    const otherKind = activeSameHold.limb?.endsWith('hand') ? 'hand' : 'foot'
    if (limbKind === otherKind) return `${limbKind === 'hand' ? '双手' : '双脚'}匹配 ${holdId}`
    return `手脚同点 ${holdId}`
  }
  if (sourceHoldId == null) return `上点 ${holdId}`
  if (Number(sourceHoldId) === holdId) return `原点调整 ${holdId}`
  return `换点 ${sourceHoldId}→${holdId}`
}
function formatClock(value) {
  const seconds = Math.max(0, Number(value || 0))
  const minutes = Math.floor(seconds / 60)
  return `${minutes}:${String(Math.floor(seconds % 60)).padStart(2, '0')}.${Math.floor((seconds % 1) * 10)}`
}
function formatNumber(value) {
  return Number.isFinite(Number(value)) ? Number(value).toLocaleString('zh-CN', { maximumFractionDigits: 2 }) : '—'
}
function formatCost(value) {
  return Number.isFinite(Number(value)) ? `¥${Number(value).toFixed(4)}` : '待计算'
}
function formatDuration(milliseconds) {
  const value = Number(milliseconds)
  if (!Number.isFinite(value)) return '待计算'
  if (value < 1000) return `${Math.max(0, Math.round(value))} 毫秒`
  const seconds = value / 1000
  if (seconds < 60) return `${seconds.toFixed(seconds < 10 ? 1 : 0)} 秒`
  const minutes = Math.floor(seconds / 60)
  return `${minutes} 分 ${Math.round(seconds % 60)} 秒`
}
function formatBytes(value) {
  const bytes = Number(value)
  if (!Number.isFinite(bytes) || bytes <= 0) return '大小未知'
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}
function formatSeconds(value) {
  const seconds = Number(value)
  if (!Number.isFinite(seconds)) return '待计算'
  return `${seconds.toFixed(seconds < 10 ? 1 : 0)} 秒`
}
function jobStatusLabel(job) {
  if (job.deletion?.state === 'queued') return '删除中'
  return ({ queued: '排队中', running: '处理中', awaiting_hold_review: '待确认岩点', succeeded: '已完成', failed: '失败', cancelled: '已取消' })[job.status] || job.status
}
function dateLabel(value) {
  if (!value) return ''
  return new Intl.DateTimeFormat('zh-CN', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' }).format(new Date(value))
}

watch(() => activeJob.value?.id, () => { reviewZoom.value=1;resetReviewZoom(1);reviewCenter.value={x:.5,y:.5};reviewPanning.value=false;reviewPanGesture=null;reviewTouches.clear();reviewTouchPan=null })
watch([() => activeJob.value?.id, canRefineSampledHolds, holdReviewSaving], ([jobId, eligible, saving]) => {
  if (jobId && eligible && !saving && !autoRefineAttempted.has(jobId)) {
    autoRefineAttempted.add(jobId)
    refineSampledHolds()
  }
})
watch(() => visualState.value.stale, () => updatePlaybackEvidence())
watch(() => activeJob.value?.status, (status) => {
  if (status !== 'awaiting_hold_review') return
  const fps = Number(activeJob.value?.video?.fps) || 1
  preferredPlaybackKind.value = 'source'
  showHolds.value = true
  pendingPlaybackState.value = { time: Number(reviewResult.value?.hold_evidence?.reference_frame || 0) / fps, shouldPlay:false }
  nextTick(() => videoElement.value?.load())
})
watch(playbackUrl, (url) => {
  window.clearTimeout(playbackLoadTimer)
  if (url) handlePlaybackLoading()
  else { playbackStatus.value = 'idle'; playbackFailure.value = '' }
}, { flush: 'sync' })
onMounted(async () => {
  loadConsentPolicy()
  const requestedReplay = new URLSearchParams(window.location.search).get('replay')
  await loadJobs()
  const requestedJob = requestedReplay && recentJobs.value.find(job => job.id === requestedReplay)
  if (requestedJob) {
    // Opening an existing record is read-only; don't start automatic hold cleanup.
    autoRefineAttempted.add(requestedJob.id)
    selectJob(requestedJob)
  }
})
onBeforeUnmount(() => {
  discardPreparedPreview()
  selectedFileToken += 1
  previewController?.abort()
  window.clearTimeout(playbackLoadTimer)
  window.clearTimeout(pollTimer)
  window.clearTimeout(deletionTimer)
  if (previewUrl.value) URL.revokeObjectURL(previewUrl.value)
})
</script>

<style scoped>
.review-filebar{display:flex;align-items:center;justify-content:space-between;gap:12px;min-height:44px;min-width:0}
.review-file-trigger{display:flex;align-items:center;gap:8px;min-width:0;max-width:calc(100% - 56px);height:44px;padding:0 8px;border:0;border-radius:6px;background:transparent;color:var(--ui-ink);font:inherit;font-size:14px;text-align:left;cursor:pointer}
.review-file-trigger>span{min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.review-file-trigger>svg:first-child{color:var(--ui-ink-muted)}.review-file-trigger>svg:last-child{width:12px;height:12px;color:var(--ui-ink-muted)}
.review-file-trigger:hover,.review-file-trigger[aria-expanded=true]{background:var(--ui-surface-subtle)}
.review-filebar svg,.review-toolrail svg,.review-file-popover svg{flex:none;width:18px;height:18px}
.review-display-tools{display:flex;align-items:center;gap:4px;flex:none}
.review-layer-toggle,.review-return{position:relative;width:44px;height:44px;padding:0;border:0;border-radius:6px;background:transparent;color:var(--ui-ink-muted);display:grid;place-items:center;cursor:pointer}
.review-layer-toggle input{position:absolute;inset:0;width:100%;height:100%;margin:0;opacity:0;cursor:pointer}
.review-layer-toggle:has(input:checked){color:var(--ui-ink)}.review-layer-toggle:has(input:not(:checked)){color:var(--ui-ink-faint);text-decoration:line-through}
.review-layer-toggle:has(input:focus-visible){outline:2px solid #806000;outline-offset:2px}.review-layer-toggle:hover,.review-return:hover{background:var(--ui-surface-subtle)}
.review-toolrail{display:flex;align-items:center;gap:4px}.review-toolrail button{display:flex;align-items:center;justify-content:center;gap:6px;min-height:44px;padding:8px 12px;border:0;border-radius:6px;background:transparent;color:var(--ui-ink-muted);font:inherit;cursor:pointer}.review-toolrail button[aria-pressed=true]{background:var(--ui-ink);color:var(--ui-surface)}
.review-view-tools{display:flex;align-items:center;gap:4px}.review-view-tools select{width:64px;min-height:44px;padding:8px;border:0;border-radius:6px;background:var(--ui-surface-subtle);color:var(--ui-ink);font:inherit;font-size:14px}.review-view-tools button{display:grid;place-items:center;width:44px;min-height:44px;padding:10px;border:0;border-radius:6px;background:transparent;color:var(--ui-ink)}.review-view-tools svg{width:18px;height:18px}.review-view-tools button[aria-pressed=true]{background:var(--ui-ink);color:var(--ui-surface)}
.review-media-viewport{position:relative;overflow:hidden;flex:none;max-width:100%;max-height:100%;width:100%;height:100%;isolation:isolate}.review-media-viewport>.video-canvas{position:absolute;top:0;left:0;max-width:none;max-height:none;display:block;transform-origin:0 0}.review-pan-surface{position:absolute;inset:0;z-index:6;touch-action:none;border:0;background:transparent;cursor:grab}.review-pan-surface:active{cursor:grabbing}
.review-file-popover{position:fixed;inset:auto;margin:0;width:256px;max-width:calc(100vw - 24px);max-height:calc(100dvh - 40px);overflow:auto;padding:8px;border:0;border-radius:10px;background:var(--ui-surface);color:var(--ui-ink);box-shadow:0 10px 32px #20202026;font:inherit;font-size:14px}
.review-file-popover:popover-open{display:flex;flex-direction:column;gap:2px}.review-file-popover button,.review-file-popover>a{display:flex;align-items:center;gap:10px;min-height:44px;padding:8px 10px;border:0;border-radius:6px;background:transparent;color:var(--ui-ink);font:inherit;text-align:left;text-decoration:none;cursor:pointer}
.review-file-popover button:hover:not(:disabled),.review-file-popover>a:hover{background:var(--ui-surface-subtle)}.review-file-popover .review-menu-delete{color:#a9322d}.review-menu-filename{margin:0;padding:8px 10px 12px;font-size:12px;line-height:1.5;color:var(--ui-ink-muted);overflow-wrap:anywhere}.review-menu-count{margin-left:auto;font-size:12px;color:var(--ui-ink-muted)}.review-menu-divider{height:1px;flex:none;margin:6px 2px;background:var(--ui-line)}
.review-menu-filename>span{display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
.review-file-popover>label{display:flex;align-items:center;gap:8px;padding:8px 10px;min-height:44px}.review-file-popover .playback-switch{display:flex;gap:2px;border-radius:6px;background:var(--ui-surface-subtle);padding:2px}.review-file-popover .playback-switch button{flex:1;font-size:12px;white-space:nowrap;justify-content:center}.review-file-popover .playback-switch button[aria-pressed=true]{background:var(--ui-surface)}
.review-count{display:flex;align-items:center;flex-wrap:wrap;gap:12px;font-size:13px;color:var(--ui-ink)}.review-count>span{font-size:12px;color:var(--ui-ink-muted)}
.visual-replay-action,.visual-replay-state button{min-height:44px;padding:8px 14px;border:1px solid var(--ui-line-strong);border-radius:8px;background:var(--ui-surface);color:var(--ui-ink);font:inherit;font-size:13px;font-weight:650;cursor:pointer}
.visual-replay-action{border-color:#f4c430;background:#f4c430;color:#2d2500}
.visual-replay-action:hover{background:#e7b821;border-color:#e7b821}
.visual-replay-action:focus-visible,.visual-replay-state button:focus-visible{outline:3px solid var(--ui-brand);outline-offset:3px}
.visual-replay-state{display:flex;align-items:center;flex-wrap:wrap;gap:8px 14px;padding:12px 16px;background:var(--ui-surface-subtle)}
.visual-replay-state p,.visual-playback-note{margin:0;font-size:13px;line-height:1.6;color:var(--ui-ink-muted)}
.visual-replay-state p{flex:1 1 220px}
.visual-replay-state button:hover:not(:disabled){background:var(--ui-ground)}
.visual-replay-state button:disabled{opacity:.6;cursor:wait}
.visual-playback-note{padding:10px 16px;background:var(--ui-surface-subtle)}
.hold-draw-surface{position:absolute;inset:0;z-index:4;width:100%;height:100%;border:0;background:transparent;cursor:crosshair;pointer-events:auto;touch-action:none}
.hold-draw-surface:focus-visible{outline:3px solid #ffcc4d;outline-offset:-4px}
.hold-draw-surface:disabled{cursor:wait}
.hold-draft-box{position:absolute;z-index:5;border:2px dashed #ffcc4d;background:rgba(255,204,77,.18);box-shadow:0 2px 10px rgba(0,0,0,.35);pointer-events:none}
.hold-preview-outline{position:absolute;inset:0;z-index:5;width:100%;height:100%;pointer-events:none}
.hold-preview-outline polygon{fill:rgba(255,203,74,.28);stroke:#ffcc4d;stroke-width:.65;vector-effect:non-scaling-stroke;paint-order:stroke;filter:drop-shadow(0 0 3px #101414)}
.hold-set-review{margin-top:14px;padding-top:14px;border-top:1px solid var(--ui-border);display:grid;gap:10px}
.hold-set-review p{margin:0;line-height:1.6}
.hold-set-review select{max-width:100%;padding:8px;font:inherit}
.paid-analysis-options summary{cursor:pointer;padding:10px 0}
.paid-analysis-options .primary-action{margin-top:10px}
.hold-review-hint{flex-basis:100%;font-size:12px;line-height:1.5;color:#f0e3ad;margin:0}
.hold-coordinate-entry{padding:8px 14px;background:#17201b;color:#f3f5f1;font-size:12px}
.hold-coordinate-entry summary{width:max-content;max-width:100%;cursor:pointer;text-underline-offset:3px}
.hold-coordinate-entry summary:hover{text-decoration:underline}
.hold-coordinate-entry summary:focus-visible,.hold-coordinate-entry button:focus-visible,.hold-coordinate-entry input:focus-visible{outline:2px solid #ffcc4d;outline-offset:2px}
.hold-coordinate-entry form{display:flex;align-items:end;flex-wrap:wrap;gap:8px 12px;padding-top:10px}
.hold-coordinate-entry label{display:grid;gap:4px;color:#f3f5f1}
.hold-coordinate-entry input{width:62px;min-height:44px;padding:6px;border:1px solid #91a99a;border-radius:6px;background:#fff;color:#17201b;font:inherit}
.hold-coordinate-entry button{min-height:44px;padding:7px 11px;border:1px solid #a8d6a9;border-radius:7px;background:#e9f8e9;color:#17351f;font-weight:700;cursor:pointer}
.hold-coordinate-entry button:disabled{opacity:.6;cursor:wait}
.hold-review-feedback{flex-basis:100%;margin:0;padding:9px 12px;border-radius:8px;background:#e8f4ed;color:#17472f;font-size:12px;line-height:1.5}
.hold-review-feedback--error{background:#fff0dc;color:#593b15}
.setup-note,.hold-evidence-note{font-size:12px;line-height:1.55;color:var(--ui-ink-muted)}
.replay-page{max-width:1120px;margin:0 auto;padding:24px 28px 80px;color:var(--ui-ink)}
.replay-page ::selection{background:var(--ui-brand-soft);color:var(--ui-brand-ink)}
.replay-page :is(button,input,select,a,summary):focus-visible{outline:3px solid var(--ui-focus-halo);outline-offset:2px}
.replay-heading{display:flex;align-items:center;justify-content:space-between;gap:24px;margin-bottom:18px}
.replay-heading>div{display:flex;align-items:baseline;flex-wrap:wrap;gap:8px 16px}
.replay-heading h1{margin:0;font-size:26px;font-weight:650;letter-spacing:-.02em;line-height:1.3}
.replay-heading p{max-width:65ch;margin:0;color:var(--ui-ink-muted);font-size:13px}
.prototype-badge{flex:none;padding:5px 9px;border:1px solid var(--ui-line);border-radius:999px;background:rgba(255,255,255,.56);color:var(--ui-ink-muted);font-size:11px;font-weight:600}
.replay-workspace{display:grid;grid-template-columns:minmax(0,1fr) 330px;gap:22px;align-items:start}
.replay-record-toolbar{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:12px 16px 0;margin-bottom:12px}
.replay-record-name{min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:var(--ui-ink-muted);font-size:13px;line-height:1.5}
.delete-record-button{flex:none;display:inline-flex;align-items:center;justify-content:center;gap:8px;min-height:44px;padding:10px 16px;border:0;border-radius:var(--ui-radius-control);background:var(--ui-danger);color:var(--ui-surface);font:inherit;font-size:14px;font-weight:650;line-height:1.4;cursor:pointer}
.delete-record-button svg{width:18px;height:18px}
.delete-record-button:hover:not(:disabled){background:color-mix(in srgb,var(--ui-danger) 85%,var(--ui-ink))}
.delete-record-button:disabled{cursor:not-allowed;opacity:.45}
.replay-workspace.review-mode{grid-template-columns:minmax(0,1fr)}
.video-column,.setup-panel,.recent-section{border:1px solid var(--ui-line);border-radius:16px;background:var(--ui-surface)}
.video-column{min-width:0;overflow:hidden}
.hold-repair-controls{padding:20px 24px;border-bottom:1px solid var(--ui-line);background:var(--ui-surface)}
.hold-repair-buttons{display:flex;flex:none;flex-wrap:wrap;justify-content:flex-end;gap:8px}
.hold-repair-heading{display:flex;align-items:center;justify-content:space-between;gap:16px}
.hold-repair-heading h2{margin:0 0 5px;font-size:14px;font-weight:600}
.hold-repair-heading span{color:var(--ui-ink-muted);font-size:12px;line-height:1.6}
.hold-repair-heading .secondary-button{flex:none;min-height:44px;display:inline-flex;align-items:center;gap:7px;border-color:var(--ui-brand);background:var(--ui-brand);color:var(--ui-brand-ink);font-size:13px;font-weight:600}
.hold-repair-heading .secondary-button:hover:not(:disabled){border-color:var(--ui-brand-hover);background:var(--ui-brand-hover)}
.hold-repair-heading .hold-repair-back{border-color:var(--ui-line-strong);background:var(--ui-surface);color:var(--ui-ink)}
.hold-repair-heading .hold-repair-back:hover:not(:disabled){border-color:var(--ui-line-strong);background:var(--ui-ground)}
.hold-repair-heading svg{width:16px;height:16px}
.hold-repair-controls>p{margin:12px 0 0;font-size:12px;line-height:1.6;color:var(--ui-ink-muted)}
.manual-hold-history{margin-top:16px;border-top:1px solid var(--ui-line)}
.manual-hold-history>summary{min-height:48px;display:flex;align-items:center;justify-content:space-between;gap:12px;cursor:pointer;font-size:13px;list-style:none}
.manual-hold-history>summary::-webkit-details-marker{display:none}
.manual-hold-history>summary svg{width:14px;height:14px;color:var(--ui-ink-muted);transition:transform .2s ease-out}
.manual-hold-history[open]>summary svg{transform:rotate(90deg)}
.manual-hold-history .media-row{align-items:center;padding:12px 0;gap:16px}
.manual-hold-detail{min-width:0;display:grid;gap:5px}
.manual-hold-detail strong{font-size:13px;font-weight:500}
.manual-hold-detail small{font-size:12px;color:var(--ui-ink-muted);font-variant-numeric:tabular-nums;line-height:1.5}
.hold-undone{margin-left:8px;color:var(--ui-ink-muted);font-size:12px;font-weight:400}
.manual-hold-actions{display:flex;flex:none;gap:8px}
.manual-hold-actions button{min-height:44px;padding:8px 12px;border:1px solid var(--ui-line);border-radius:8px;background:var(--ui-surface);color:var(--ui-ink);font:inherit;font-size:12px;cursor:pointer}
.manual-hold-actions button:hover:not(:disabled){border-color:var(--ui-line-strong);background:var(--ui-surface-subtle)}
.manual-hold-actions button:disabled{opacity:.5;cursor:not-allowed}
.video-drop{min-height:540px;padding:40px;display:grid;place-items:center;align-content:center;gap:12px;background:#242629;color:#fff;text-align:center;cursor:pointer;transition:background .18s ease-out}
.video-drop.dragging,.video-drop:hover{background:#2d3033}.drop-icon{width:42px;height:42px;color:var(--ui-brand)}
.video-drop strong{font-size:21px}.video-drop>span{color:#bfc2c4;font-size:13px}
.secondary-button,.replace-video,.cancel-action{min-height:38px;padding:0 15px;border:1px solid var(--ui-line-strong);border-radius:var(--ui-radius-small);background:var(--ui-surface);color:var(--ui-ink);font:inherit;font-size:13px;font-weight:600;cursor:pointer}.secondary-button:disabled{cursor:not-allowed;opacity:.45}
.video-drop .secondary-button{margin-top:8px;border-color:#696c70;background:transparent;color:#fff}
.test-video-cases{padding:16px 20px 18px;border-top:1px solid var(--ui-line);background:var(--ui-surface-subtle);display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px}.test-video-heading{grid-column:1/-1;min-width:0;margin-bottom:3px;display:grid;grid-template-columns:36px minmax(0,1fr);align-items:center;gap:12px}.test-video-mark{width:34px;height:34px;border-radius:10px;background:var(--ui-brand-soft);color:var(--ui-brand-ink);display:grid;place-items:center}.test-video-mark svg{width:18px}.test-video-heading strong{font-size:13px}.test-video-heading p{margin:3px 0 0;color:var(--ui-ink-muted);font-size:12px}.test-video-case{min-width:0;padding:11px 12px;border:1px solid var(--ui-line);border-radius:var(--ui-radius-small);background:var(--ui-surface);color:var(--ui-ink);display:flex;align-items:center;justify-content:space-between;gap:10px;text-align:left;font:inherit;cursor:pointer}.test-video-case:hover:not(:disabled){border-color:var(--ui-line-strong);background:var(--ui-surface-subtle)}.test-video-case:disabled{cursor:not-allowed;opacity:.55}.test-video-case>span{min-width:0;display:grid;gap:3px}.test-video-case strong{font-size:12px}.test-video-case small{color:var(--ui-ink-muted);font-size:11px;line-height:1.4;overflow-wrap:anywhere}.test-video-case b{flex:none;color:var(--ui-ink-muted);font-size:11px}.test-video-case svg{flex:none;width:15px;animation:spin 1s linear infinite}
.playback-review{display:grid;min-width:0;background:#0e100f}
.playback-review.has-action-focus{grid-template-columns:minmax(0,1fr) 280px}
.video-stage{position:relative;min-width:0;height:clamp(440px,calc(100dvh - 230px),820px);min-height:0;background:#0e100f;display:flex;align-items:center;justify-content:center;overflow:hidden}
.video-canvas{position:relative;max-width:100%;max-height:100%;display:inline-flex}
.video-stage video{display:block;width:100%;height:100%;max-width:100%;max-height:100%;object-fit:contain}
.video-preview-state{position:absolute;inset:0;z-index:6;display:flex;align-items:center;justify-content:center;padding:48px 20px 20px;background:rgba(14,16,15,.94);color:#fff;text-align:center}
.video-preview-message{display:flex;flex-direction:column;align-items:center;gap:10px;max-width:400px}
.video-preview-message>svg{width:28px;height:28px;color:#f4c430}
.video-preview-message strong{font-size:17px;line-height:1.4}
.video-preview-message p{margin:0;color:#d9ddd9;font-size:13px;line-height:1.6}
.video-preview-message button{min-height:44px;margin-top:4px;padding:8px 16px;border:1px solid #a5aaa5;border-radius:8px;background:#242824;color:#fff;font:inherit;font-size:13px;cursor:pointer}
.video-preview-message button:hover{background:#363c36}
.video-preview-message button:focus-visible{outline:3px solid #f4c430;outline-offset:3px}
.video-preview-spinner{animation:spin 1s linear infinite}
@media(max-width:520px){.video-stage:has(.video-preview-state){min-height:260px}}
.color-sample-canvas{position:absolute;inset:0;width:100%;height:100%;cursor:crosshair;background:#111;z-index:6}.color-sample-hint{position:absolute;z-index:7;left:50%;top:14px;max-width:calc(100% - 28px);padding:7px 11px;border-radius:9px;background:rgba(14,16,15,.88);color:#fff;font-size:12px;line-height:1.35;transform:translateX(-50%);pointer-events:none;box-shadow:0 4px 16px rgba(0,0,0,.28)}
.hold-overlay{position:absolute;inset:0;margin:auto;width:100%;height:100%;pointer-events:none}
.hold-contours{position:absolute;inset:0;width:100%;height:100%;pointer-events:none}
.hold-contours polygon{fill:rgba(237,203,82,.09);stroke:var(--ui-brand);stroke-width:2;vector-effect:non-scaling-stroke;pointer-events:visiblePainted;cursor:pointer}
.hold-contours polygon.selected{stroke:#fff;stroke-width:3;fill:rgba(237,203,82,.28)}
.hold-marker{position:absolute;z-index:3;transform:translate(-50%,-70%);width:44px;height:44px;min-height:44px;padding:0;border:0;background:transparent;pointer-events:auto;display:grid;place-items:center}
.hold-marker>span{min-width:20px;padding:3px;border-radius:6px;background:var(--ui-brand);color:var(--ui-brand-ink);font-family:inherit;font-size:12px;font-weight:600;line-height:1.2}
.hold-marker.missing-contour>span{background:var(--ui-surface);color:var(--ui-ink);border:1px dashed var(--ui-ink-muted)}
.canvas-hold-actions{position:absolute;z-index:8;left:50%;bottom:60px;transform:translateX(-50%);display:flex;flex-wrap:wrap;justify-content:center;gap:4px;max-width:calc(100% - 12px);width:max-content;padding:4px;border-radius:10px;background:var(--ui-surface);color:var(--ui-ink);pointer-events:auto;box-shadow:0 6px 24px rgba(0,0,0,.22)}
.canvas-hold-actions button{min-width:44px;min-height:44px;padding:8px 10px;border:0;border-radius:6px;background:var(--ui-surface);color:var(--ui-ink);font:inherit;cursor:pointer}
.missing-contour-note{flex-basis:100%;font-size:12px;text-align:center}
.hold-global-actions{display:flex;flex-wrap:wrap;align-items:center;justify-content:flex-end;gap:8px;padding:8px 0;border-top:1px solid var(--ui-line)}
.hold-inline-feedback{flex:1;min-width:0;font-size:12px}
.pose-overlay{position:absolute;inset:0;width:100%;height:100%;overflow:visible}.pose-overlay line{stroke:#6ce0d2;stroke-width:3;stroke-linecap:round}.pose-overlay circle{fill:#d6fff9;stroke:#155d55;stroke-width:1.5}.pose-evidence{position:absolute;left:12px;top:12px;padding:6px 9px;border-radius:8px;background:rgba(17,92,83,.9);color:#fff;font-size:11px;font-weight:650;box-shadow:0 3px 12px rgba(0,0,0,.24)}.pose-evidence.nearby{background:rgba(47,50,52,.9);border:1px dashed rgba(255,255,255,.7)}.contact-badges{position:absolute;left:12px;bottom:12px;display:flex;flex-wrap:wrap;gap:6px}.contact-badges span{padding:5px 8px;border-radius:7px;background:rgba(21,76,132,.92);color:#fff;font-size:11px;font-weight:650;box-shadow:0 3px 12px rgba(0,0,0,.24)}
.replace-video{position:absolute;z-index:7;right:16px;top:16px;min-height:34px;padding:0 13px;border-color:rgba(255,255,255,.18);border-radius:999px;background:rgba(14,16,15,.76);color:#fff;backdrop-filter:blur(8px)}
.action-focus{min-width:0;padding:24px 22px 22px;background:#171917;color:#f7f6f1;display:flex;flex-direction:column;border-left:1px solid rgba(255,255,255,.08)}
.action-focus-head{display:flex;align-items:center;justify-content:space-between;gap:12px;color:#8f948f;font-size:11px}.action-focus-head strong{color:#c7cac5;font-size:11px;font-weight:500}.action-focus-head span{font-variant-numeric:tabular-nums}.action-focus-head b{color:#f4c430;font-size:13px}
.action-focus-name{margin-top:30px;display:grid;grid-template-columns:48px minmax(0,1fr);align-items:start;gap:15px}.action-focus-name>span{width:48px;height:48px;border:1px solid rgba(244,196,48,.52);border-radius:50%;color:#f4c430;display:grid;place-items:center;font-size:13px;font-weight:700;font-variant-numeric:tabular-nums}.action-focus-name>div{min-width:0;display:grid;gap:2px}.action-focus-name strong{font-size:22px;font-weight:600;letter-spacing:-.02em;line-height:1.2}.action-focus-name p{margin:2px 0 0;color:#d9dbd7;font-size:14px;line-height:1.4}.action-focus-name small{margin-top:8px;color:#858a85;font-size:11px;font-variant-numeric:tabular-nums}
.action-focus-actions{margin-top:auto;display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:7px}.action-focus-actions button{min-height:42px;padding:0 8px;border:1px solid transparent;border-radius:999px;background:rgba(255,255,255,.07);color:#d7dad5;display:flex;align-items:center;justify-content:center;gap:6px;font:inherit;font-size:11px;font-weight:600;cursor:pointer;transition:background .18s ease-out,color .18s ease-out,transform .18s ease-out}.action-focus-actions button svg{width:14px;height:14px}.action-focus-actions button.primary{background:var(--ui-brand);color:var(--ui-brand-ink)}.action-focus-actions button:hover:not(:disabled){background:rgba(255,255,255,.13);color:#fff;transform:translateY(-1px)}.action-focus-actions button.primary:hover{background:var(--ui-brand-hover);color:var(--ui-brand-ink)}.action-focus-actions button:disabled{cursor:not-allowed;opacity:.28}
.player-tools{min-height:50px;padding:9px 18px;border-top:1px solid rgba(255,255,255,.07);background:#171917;color:#f7f6f1;display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:9px 16px}.player-options{min-width:0;display:flex;align-items:center;flex-wrap:wrap;gap:9px 16px}.player-options>p{margin:0;color:#bfc3bd;font-size:12px}.player-options .hold-tool-action{min-height:40px;padding:0 14px;border:1px solid #f4c430;border-radius:8px;background:#f4c430;color:#2d2500;font:inherit;font-size:13px;font-weight:700;cursor:pointer}.player-options .hold-tool-action:hover:not(:disabled){background:#e7b821;border-color:#e7b821;color:#2d2500}.player-options .hold-tool-action--secondary{border-color:#bfc3bd;background:#171917;color:#f7f6f1}.player-options .hold-tool-action--secondary:hover:not(:disabled){border-color:#fff;background:#303330;color:#fff}.player-options .hold-tool-action:disabled{background:#777970;border-color:#777970;color:#191b19;cursor:wait}.playback-switch{padding:3px;border:0;border-radius:999px;background:rgba(255,255,255,.08);display:flex;gap:2px}.playback-switch button{min-height:29px;padding:0 12px;border:0;border-radius:999px;background:transparent;color:#bfc3bd;font:inherit;font-size:11px;font-weight:600;cursor:pointer}.playback-switch button.active{background:#f2f1ec;color:#181a18}.playback-switch button:disabled{cursor:not-allowed;opacity:.35}.layer-controls{display:flex;align-items:center;flex-wrap:wrap;gap:8px 16px}.layer-controls label{display:flex;align-items:center;gap:6px;color:#c3c7c1;font-size:11px;font-weight:500;cursor:pointer}.layer-controls input{width:14px;height:14px;margin:0;accent-color:var(--ui-brand)}.export-action{flex:none;min-height:32px;padding:0 12px;border:1px solid rgba(255,255,255,.13);border-radius:999px;color:#f2f3ef;display:inline-flex;align-items:center;font-size:11px;font-weight:600;text-decoration:none}.export-action:hover{background:rgba(255,255,255,.08)}
.hold-operation-list ol{max-height:260px;margin:12px 0 0;padding:0;overflow-y:auto;list-style:none;scrollbar-color:var(--ui-line-strong) transparent}.hold-operation-list li{min-width:0;min-height:56px;padding:8px 0;border-top:1px solid var(--ui-line);display:grid;grid-template-columns:28px minmax(0,1fr) auto;align-items:center;gap:8px 12px}.hold-operation-list__number{width:28px;height:28px;border-radius:8px;background:var(--ui-brand-soft);color:var(--ui-brand-ink);display:grid;place-items:center;font-size:12px;font-weight:700;font-variant-numeric:tabular-nums}.hold-operation-list__detail{min-width:0;display:grid;gap:3px}.hold-operation-list__detail strong{font-size:12px;font-weight:650}.hold-operation-list__detail small{color:var(--ui-ink-muted);font-size:11px;line-height:1.4;overflow-wrap:anywhere;font-variant-numeric:tabular-nums}.hold-operation-list__actions{display:flex;align-items:center;flex-wrap:wrap;gap:6px}.hold-operation-list__actions button{min-height:36px;padding:0 11px;border:1px solid var(--ui-line-strong);border-radius:8px;background:var(--ui-surface);color:var(--ui-ink);font:inherit;font-size:12px;font-weight:600;cursor:pointer}.hold-operation-list__actions button:hover:not(:disabled){border-color:var(--ui-ink-muted);background:var(--ui-surface-subtle)}.hold-operation-list__actions .hold-operation-list__undo{border-color:#bf887e;color:#8a281d}.hold-operation-list__actions .hold-operation-list__undo:hover:not(:disabled){border-color:#8a281d;background:#fff0ed}.hold-operation-list__actions button:disabled{opacity:.5;cursor:not-allowed}.hold-operation-list__removed .hold-operation-list__number{background:var(--ui-surface-subtle);color:var(--ui-ink-muted)}.hold-operation-list__status{color:var(--ui-ink-muted);font-size:12px}
@media(max-width:650px){.hold-operation-list li{grid-template-columns:28px minmax(0,1fr)}.hold-operation-list__actions,.hold-operation-list__status{grid-column:2}.hold-operation-list__actions button{min-height:40px}}
.event-timeline{padding:17px 20px 18px;border-top:1px solid var(--ui-line);background:var(--ui-surface)}
.event-timeline-heading{display:flex;align-items:baseline;justify-content:space-between;gap:10px;margin-bottom:12px}.event-timeline-heading strong{font-size:12px;font-weight:600}.event-timeline-heading span{color:var(--ui-ink-faint);font-size:10px}
.event-timeline ol{margin:0;padding:0 0 7px;list-style:none;display:flex;gap:0;overflow-x:auto;scroll-snap-type:x proximity;scrollbar-color:var(--ui-line-strong) transparent;scrollbar-width:thin}
.event-timeline li{position:relative;flex:none;scroll-snap-align:center}.event-timeline li:not(:last-child)::after{content:"";position:absolute;z-index:0;left:52px;top:14px;width:28px;height:1px;background:var(--ui-line)}
.event-timeline button{position:relative;z-index:1;width:80px;min-height:66px;padding:0 5px;border:0;background:transparent;color:var(--ui-ink-muted);display:flex;flex-direction:column;align-items:center;gap:4px;text-align:center;font:inherit;cursor:pointer}
.event-timeline button>span{width:28px;height:28px;border:1px solid var(--ui-line);border-radius:50%;background:var(--ui-surface);display:grid;place-items:center;font-size:10px;font-weight:700;font-variant-numeric:tabular-nums;transition:background .18s ease-out,border-color .18s ease-out,color .18s ease-out,transform .18s ease-out}.event-timeline button>strong{font-size:10px;font-weight:600;white-space:nowrap}.event-timeline button>small{max-width:72px;color:var(--ui-ink-faint);font-size:9px;line-height:1.2;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.event-timeline button.reached>span{border-color:#4d514c;background:#4d514c;color:#fff}.event-timeline button.reached>small,.event-timeline button.current>small{color:var(--ui-ink-muted)}
.event-timeline button.current>span{border-color:var(--ui-brand);background:var(--ui-brand);color:var(--ui-brand-ink);transform:scale(1.08)}
.event-timeline button:hover>span{border-color:var(--ui-ink);transform:translateY(-1px)}
.analysis-state{padding:18px 20px;border-top:1px solid var(--ui-line);background:var(--ui-surface-subtle)}
.state-copy{display:grid;grid-template-columns:34px minmax(0,1fr) auto;align-items:center;gap:11px}.state-copy p{margin:3px 0 0;color:var(--ui-ink-muted);font-size:12px}.state-copy>b{font-variant-numeric:tabular-nums}.state-mark{width:32px;height:32px;border-radius:10px;background:var(--ui-surface);display:grid;place-items:center}.state-mark svg{width:18px}.running .state-mark svg,.queued .state-mark svg{animation:spin 1s linear infinite}.succeeded .state-mark{color:var(--ui-success)}.failed .state-mark{color:var(--ui-danger)}
.progress-track{height:5px;margin-top:14px;border-radius:5px;background:var(--ui-line);overflow:hidden}.progress-track i{display:block;width:100%;height:100%;border-radius:inherit;background:var(--ui-brand);transform-origin:left center;transition:transform .35s ease-out}.state-actions{margin-top:12px}
.state-actions p{margin:0;color:var(--ui-ink-muted);font-size:12px}.media-row{min-width:0;padding:10px 0;border-bottom:1px solid var(--ui-line);display:flex;align-items:flex-start;justify-content:space-between;gap:18px}.media-row>div:first-child{min-width:0}.media-retention strong{font-size:12px}.media-retention p{margin:4px 0 0;color:var(--ui-ink-muted);font-size:12px;line-height:1.5}.media-actions{display:flex;flex:none;align-items:center;gap:14px}.media-record-actions{padding-top:10px;display:flex;justify-content:flex-end}.text-action{padding:3px 0;border:0;background:transparent;color:var(--ui-ink-muted);font:inherit;font-size:12px;text-decoration:underline;text-underline-offset:3px;cursor:pointer}.text-action:hover:not(:disabled){color:var(--ui-ink)}a.text-action{display:inline-flex}.text-action.destructive{color:var(--ui-danger)}.text-action:disabled{cursor:not-allowed;opacity:.45}
.run-summary{margin-top:13px;padding-top:12px;border-top:1px solid var(--ui-line);display:flex;flex-wrap:wrap;gap:7px 18px;color:var(--ui-ink-muted);font-size:12px;font-variant-numeric:tabular-nums}.run-summary span{white-space:nowrap}
.analysis-evidence dl{margin:16px 0 0;display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:0 24px}.analysis-evidence dl>div{min-width:0;padding:10px 0;border-top:1px solid var(--ui-line);display:grid;grid-template-columns:76px minmax(0,1fr);gap:10px;font-size:12px;line-height:1.55}.analysis-evidence dt{color:var(--ui-ink-muted)}.analysis-evidence dd{margin:0;color:var(--ui-ink);overflow-wrap:anywhere;font-variant-numeric:tabular-nums}.analysis-evidence>p{max-width:72ch;margin:12px 0 0;color:var(--ui-ink-muted);font-size:11px;line-height:1.6}
.setup-panel{position:sticky;top:86px;padding:24px;align-self:start}.setup-panel h2,.result-report h2{margin:0;font-size:20px}.setup-panel>div>p{margin:7px 0 0;color:var(--ui-ink-muted);font-size:13px;line-height:1.6}.setup-panel fieldset{margin:26px 0 0;padding:0;border:0}.setup-panel legend{margin-bottom:10px;font-size:13px;font-weight:600}
@media(min-width:901px){.replay-workspace:has(.setup-panel) .video-column{min-height:min(620px,calc(100dvh - 180px))}}
.color-sample-tools{margin-top:9px;display:grid;gap:7px}.color-sample-tools button{min-height:44px;padding:8px 10px;border:1px solid var(--ui-line-strong);border-radius:var(--ui-radius-small);background:var(--ui-surface);color:var(--ui-ink);display:flex;align-items:center;justify-content:center;gap:8px;font:inherit;font-size:12px;font-weight:600;cursor:pointer}.color-sample-tools button:hover:not(:disabled){background:var(--ui-surface-subtle)}.color-sample-tools button:disabled{cursor:not-allowed;opacity:.45}.color-sample-status{margin:9px 0 0;color:var(--ui-ink-muted);font-size:11px;line-height:1.55;display:grid;grid-template-columns:14px minmax(0,1fr);gap:7px;align-items:start}.color-sample-status i{width:14px;height:14px;margin-top:2px;border:1px solid rgba(0,0,0,.28);border-radius:50%}
.primary-action{width:100%;min-height:48px;margin-top:16px;border:0;border-radius:var(--ui-radius-control);background:var(--ui-brand);color:var(--ui-brand-ink);display:flex;align-items:center;justify-content:center;gap:8px;font:inherit;font-weight:700;cursor:pointer}.primary-action:hover:not(:disabled){background:var(--ui-brand-hover)}.primary-action:disabled{cursor:not-allowed;opacity:.45}.primary-action svg{width:17px}.primary-action .primary-spinner{animation:spin 1s linear infinite}.cancel-action{width:100%;margin-top:8px}.form-error,.form-notice{margin:12px 0 0;font-size:12px;line-height:1.5}.form-error{color:var(--ui-danger)}.form-notice{color:var(--ui-success)}
.result-report{padding:24px 24px 0;border-top:1px solid var(--ui-line)}.result-summary{margin-bottom:20px;display:flex;align-items:flex-start;justify-content:space-between;gap:16px}.result-summary p{margin:5px 0 0;color:var(--ui-ink-muted);font-size:13px}.result-summary>strong{font-size:26px;font-variant-numeric:tabular-nums}.sequence-block{margin-top:25px}.hold-sequence{margin-top:11px;display:flex;align-items:center;gap:7px;flex-wrap:wrap}.hold-sequence span{width:32px;height:32px;border-radius:9px;background:var(--ui-brand);color:var(--ui-brand-ink);display:grid;place-items:center;font-weight:700}.hold-sequence svg{width:14px;color:var(--ui-ink-faint)}.empty-result{color:var(--ui-ink-muted);font-size:13px}
.segment-comparison>p{color:var(--ui-ink-muted);font-size:13px;line-height:1.6}.comparison-controls{display:grid;gap:12px;margin:18px 0}.comparison-controls select{max-width:100%;padding:10px;border:1px solid var(--ui-line);border-radius:8px;background:var(--ui-surface)}.comparison-controls label{display:flex;gap:8px;align-items:center;font-size:13px}.comparison-controls button{justify-self:start}.comparison-error{color:#b42318}.comparison-videos{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}.comparison-videos>div{min-width:0}.comparison-videos strong{display:block;margin-bottom:8px}.comparison-videos video{width:100%;max-height:240px;background:#111;border-radius:8px}.comparison-videos p,.comparison-limit{font-size:12px;color:var(--ui-ink-muted)}.comparison-list{display:grid;gap:0;padding:0;list-style:none}.comparison-list li{display:grid;gap:5px;padding:16px 0;border-top:1px solid var(--ui-line);font-size:13px}.comparison-list li>div{display:flex;gap:10px}.comparison-list button{padding:5px 0;border:0;background:none;color:var(--ui-ink);text-decoration:underline;text-underline-offset:3px;cursor:pointer}@media(max-width:650px){.comparison-videos{grid-template-columns:1fr}}
.segment-review>p{font-size:13px;line-height:1.6;color:var(--ui-ink-muted)}.segment-review>ol{display:grid;gap:0;padding:0;list-style:none}.segment-review>ol>li{padding:16px 0;border-top:1px solid var(--ui-line)}.segment-review-row{display:flex;align-items:center;flex-wrap:wrap;gap:8px;font-size:13px}.segment-review-row span{color:var(--ui-ink-muted);margin-right:auto}.segment-review-row button,.segment-review-form button{border:0;background:none;min-height:40px;color:var(--ui-ink);text-decoration:underline;text-underline-offset:3px;cursor:pointer}.segment-review-form{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px;margin-top:14px}.segment-review-form label{display:grid;gap:4px;font-size:12px}.segment-review-form input,.segment-review-form select{min-width:0;padding:8px;border:1px solid var(--ui-line);border-radius:6px;background:var(--ui-surface)}.segment-review-form>div{grid-column:1/-1;display:flex;flex-wrap:wrap;gap:12px}@media(max-width:650px){.segment-review-form{grid-template-columns:1fr}}
.limb-table{margin-top:22px;border-top:1px solid var(--ui-line)}.limb-table>div{min-height:50px;border-bottom:1px solid var(--ui-line);display:grid;grid-template-columns:70px 80px 1fr;align-items:center;gap:10px;font-size:13px}.limb-table strong{font-variant-numeric:tabular-nums}.limb-table small{color:var(--ui-ink-muted);text-align:right}.review-notes{margin-top:0;color:var(--ui-ink-muted);font-size:12px}.review-notes summary{color:var(--ui-ink);cursor:pointer;font-weight:600}.review-notes ul{margin:9px 0 0;padding-left:18px;line-height:1.7}
.recent-section{margin-top:16px;}.recent-row{width:100%;min-height:58px;padding:9px 4px;border:0;border-top:1px solid var(--ui-line);background:transparent;color:var(--ui-ink);display:grid;grid-template-columns:10px minmax(0,1fr) auto;align-items:center;gap:12px;text-align:left;cursor:pointer}.recent-row>span:nth-child(2){min-width:0;display:grid;gap:3px}.recent-row strong,.recent-row small{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.recent-row small{color:var(--ui-ink-muted)}.recent-row>b{font-size:12px}.recent-dot{width:8px;height:8px;border-radius:50%;background:var(--ui-warning)}.recent-dot.succeeded{background:var(--ui-success)}.recent-dot.failed{background:var(--ui-danger)}.recent-dot.cancelled{background:var(--ui-ink-faint)}
.replay-detail-sections{padding:0 24px;border-top:1px solid var(--ui-line)}
.replay-disclosure{min-width:0}
.replay-detail-sections>.replay-disclosure+.replay-disclosure,.result-details,.review-notes{border-top:1px solid var(--ui-line)}
.replay-disclosure>summary{min-height:56px;box-sizing:border-box;padding:12px 0;display:grid;grid-template-columns:auto minmax(0,1fr) 16px;align-items:center;gap:8px 16px;color:var(--ui-ink);cursor:pointer;list-style:none}
.replay-disclosure>summary::-webkit-details-marker{display:none}
.replay-disclosure>summary::marker{content:""}
.replay-disclosure>summary:hover{background:var(--ui-surface-subtle)}
.replay-disclosure>summary:active{background:var(--ui-brand-soft)}
.replay-disclosure>summary:focus-visible{outline:2px solid var(--ui-ink);outline-offset:2px}
.replay-disclosure>summary :is(h2,h3),.disclosure-title{margin:0;font-size:14px;font-weight:600;line-height:1.5}
.replay-disclosure>summary .disclosure-meta{min-width:0;justify-self:end;color:var(--ui-ink-muted);font-size:12px;line-height:1.5;text-align:right;font-variant-numeric:tabular-nums;overflow-wrap:anywhere}
.disclosure-chevron{grid-column:3;width:16px;height:16px;color:var(--ui-ink-muted);transition:transform .18s ease-out}
.replay-disclosure[open]>summary .disclosure-chevron{transform:rotate(90deg)}
.replay-detail-sections>.replay-disclosure[open],.result-details[open],.review-notes[open]{padding-bottom:18px}
.disclosure-description{margin:0 0 12px;color:var(--ui-ink-muted);font-size:12px;line-height:1.6}
.recent-section{padding:0 24px}
.recent-section[open]{padding-bottom:16px}
.replay-disclosure .comparison-error{color:var(--ui-danger)}
.visually-hidden{position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap;border:0}
@keyframes spin{to{transform:rotate(360deg)}}
@media(max-width:900px){.replay-page{padding:18px 16px 88px}.replay-heading{gap:12px;margin-bottom:14px}.replay-heading h1{font-size:22px}.replay-workspace{grid-template-columns:1fr}.setup-panel{position:static}.video-drop{min-height:340px}.video-stage{height:min(56vw,390px);min-height:0;max-height:390px}.video-canvas{height:100%;max-height:100%}.video-stage video{max-height:100%}.color-options{grid-template-columns:repeat(2,minmax(0,1fr))}}
@media(max-width:600px){.replay-heading{display:none}.hold-repair-controls{padding:18px 16px}.hold-repair-heading{align-items:flex-start;gap:12px}.hold-repair-heading>div{min-width:0}.hold-repair-heading span{display:block;max-width:20ch}.manual-hold-history .media-row{display:grid;gap:10px}.manual-hold-actions{justify-content:flex-start}}
@media(max-width:720px){.playback-review.has-action-focus{grid-template-columns:1fr}.action-focus{min-height:156px;padding:17px 16px 16px;border-top:1px solid rgba(255,255,255,.08);border-left:0}.action-focus-name{margin-top:14px;grid-template-columns:40px minmax(0,1fr);gap:12px}.action-focus-name>span{width:40px;height:40px}.action-focus-name strong{font-size:18px}.action-focus-name p{font-size:13px}.action-focus-name small{margin-top:4px}.action-focus-actions{margin-top:16px}.player-tools{align-items:flex-start;flex-wrap:wrap}}
@media(max-width:650px){.test-video-cases{grid-template-columns:1fr}}
@media(max-width:520px){.video-column{border-radius:14px}.video-stage{height:58vw;max-height:260px}.action-focus{min-height:154px}.action-focus-head{position:absolute;right:16px;margin-top:2px}.action-focus-head>strong{display:none}.action-focus-name strong{font-size:18px}.action-focus-actions button{min-height:40px}.test-video-cases{padding:14px 16px}.color-options{grid-template-columns:repeat(4,1fr)}.limb-table>div{grid-template-columns:58px 64px 1fr}.result-report{padding:20px 16px 0}.result-summary>strong{font-size:21px}.run-summary{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:7px 12px}.analysis-evidence dl{grid-template-columns:1fr}.analysis-evidence dl>div{grid-template-columns:70px minmax(0,1fr)}.layer-controls{gap:8px 12px}.event-timeline{padding:15px 14px 16px}.event-timeline button{width:68px}.event-timeline li:not(:last-child)::after{left:46px;width:22px}.media-row{display:grid;gap:7px}.media-actions{justify-content:flex-start;flex-wrap:wrap}.media-record-actions{justify-content:flex-start}}
.video-stage:not(.is-reviewing .video-stage){height:clamp(360px,calc(100dvh - 230px),820px);max-height:none}
@media(max-width:520px){.replay-detail-sections,.recent-section{padding-right:16px;padding-left:16px}.replay-disclosure>summary{grid-template-columns:minmax(0,1fr) 16px;gap:3px 12px}.replay-disclosure>summary .disclosure-meta{grid-column:1;justify-self:start;text-align:left}.disclosure-chevron{grid-column:2;grid-row:1 / 3;align-self:center}.replay-disclosure>summary :is(h2,h3),.disclosure-title{font-size:14px}}
@media(prefers-reduced-motion:reduce){.progress-track i,.video-drop,.disclosure-chevron{transition:none}.running .state-mark svg,.queued .state-mark svg,.primary-action svg,.test-video-case svg,.video-preview-spinner{animation:none}}
.review-command-bar{display:flex;flex-wrap:wrap;align-items:center;gap:8px;padding:8px 12px;background:var(--ui-surface);color:var(--ui-ink)}
.review-command-bar button{min-width:0;max-width:100%;min-height:44px;padding:8px 10px;border:1px solid var(--ui-line);border-radius:8px;background:var(--ui-surface);color:var(--ui-ink);font:inherit;overflow-wrap:anywhere}
.hold-repair-controls.task-panel{padding:0}.hold-repair-heading{display:grid}.hold-repair-heading .hold-repair-buttons{min-width:0;max-width:100%;flex-shrink:1}.hold-repair-buttons button{max-width:100%;white-space:normal}
</style>

