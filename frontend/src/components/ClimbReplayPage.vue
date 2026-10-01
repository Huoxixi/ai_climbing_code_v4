<template>
  <section class="replay-page" aria-labelledby="replay-title">
    <header class="replay-heading">
      <div>
        <h1 id="replay-title">AI 复盘</h1>
        <p>看清动作，按段重看。</p>
      </div>
      <span class="prototype-badge">技术验证</span>
    </header>

    <div class="replay-workspace" :class="{ 'review-mode': result }">
      <div class="video-column">
        <UnifiedReplayPlayer v-if="result && activeJob && !isJobDeleting" :key="activeJob.id" :job="activeJob" :legacy-url="replayVideoUrl">
          <template #more>
            <button type="button" class="secondary-button" @click="openPicker">更换视频</button>
        <section v-if="result" class="result-report" aria-labelledby="result-title">
          <div class="result-summary">
            <div>
              <h2 id="result-title">本次复盘</h2>
              <p>{{ result.attempt?.topped_out ? '识别到双手稳定控制顶点' : '暂未确认完攀' }}</p>
            </div>
            <strong>{{ elapsedLabel }}</strong>
          </div>
          <details :key="activeJob.id" class="replay-disclosure result-details">
            <summary>
              <span class="disclosure-title">岩点与接触统计</span>
              <span class="disclosure-meta">{{ result.holds?.length || 0 }} 个岩点</span>
              <ArrowRight class="disclosure-chevron" aria-hidden="true" />
            </summary>
            <p v-if="result.hold_evidence" class="hold-evidence-note">
            岩点：{{ result.holds?.length || 0 }} 个用于复盘；
            {{ result.hold_evidence.frames_aligned }}/{{ result.hold_evidence.frames_decoded }} 帧成功对齐。
            <span v-if="result.hold_evidence.confirmed_members_matched">其中 {{ result.hold_evidence.confirmed_members_matched }} 个复用了已确认线路岩点。</span>
            <span v-if="result.hold_evidence.confirmed_members_projected">另有 {{ result.hold_evidence.confirmed_members_projected }} 个来自照片对齐投影，需重点复核。</span>
            <span v-else-if="result.hold_refinement">已将 {{ result.hold_refinement.before }} 个自动点收敛为 {{ result.hold_refinement.after }} 个；漏点可在画面中补入，接触结果仍需复核。</span>
            <span v-else-if="result.hold_review_version">已人工修订 {{ result.hold_review_version }} 次岩点，接触结果仍需复核。</span>
            <span v-else>当前为颜色筛出的候选，接触结果仍需复核。</span>
          </p>

          <div class="sequence-block">
            <h3>岩点使用顺序</h3>
            <div v-if="result.attempt?.sequence?.length" class="hold-sequence">
              <template v-for="(hold, index) in result.attempt.sequence" :key="`${hold}-${index}`">
                <span>{{ hold }}</span><ArrowRight v-if="index < result.attempt.sequence.length - 1" />
              </template>
            </div>
            <p v-else class="empty-result">没有识别到稳定的手脚接触。</p>
          </div>

          <div class="limb-table">
            <div v-for="item in limbRows" :key="item.key">
              <span>{{ item.label }}</span>
              <strong>{{ item.seconds }}</strong>
              <small>{{ item.holds }}</small>
            </div>
          </div>
          </details>

          <details v-if="result.warnings?.length" :key="`notes-${activeJob.id}`" class="replay-disclosure review-notes">
            <summary><span class="disclosure-title">查看识别说明</span><span class="disclosure-meta">{{ result.warnings.length }} 条</span><ArrowRight class="disclosure-chevron" aria-hidden="true" /></summary>
            <ul><li v-for="warning in result.warnings" :key="warning">{{ warning }}</li></ul>
          </details>
        </section>
        <div v-if="activeJob" :key="activeJob.id" class="replay-detail-sections">
        <details class="replay-disclosure media-retention" aria-label="视频与记录管理">
          <summary><h2>视频与记录管理</h2><span class="disclosure-meta">保留、导出与删除</span><ArrowRight class="disclosure-chevron" aria-hidden="true" /></summary>
          <div class="media-row">
            <div><strong>原视频</strong><p>{{ sourceRetentionLabel }}</p></div>
            <button v-if="sourceAvailable && !isBusy" type="button" class="text-action" :disabled="isDeleting || isJobDeleting" @click="deleteSourceVideo">仅删除原视频</button>
          </div>
          <div v-if="overlayMedia" class="media-row">
            <div><strong>{{ reviewedOverlayAvailable ? '修订前自动视频' : '叠加视频' }}</strong><p>{{ overlayRetentionLabel }}</p></div>
            <div v-if="overlayAvailable" class="media-actions">
              <a v-if="!visualState.stale" class="text-action" :href="storedOverlayDownloadUrl">导出</a>
              <button type="button" class="text-action" :disabled="isDeleting || isJobDeleting" @click="deleteOverlayVideo">删除叠加视频</button>
            </div>
          </div>
          <div v-if="reviewedOverlayAvailable" class="media-row">
            <div><strong>岩点修订复盘视频</strong><p>已重新计算岩点接触，仅当前账号可见</p></div>
            <a v-if="!visualState.stale" class="text-action" :href="replayDownloadUrl">导出修订版</a>
          </div>
          <div class="media-record-actions">
            <button type="button" class="text-action destructive" :disabled="isDeleting || isJobDeleting" @click="deleteEntireReplay">{{ isJobDeleting ? '正在删除整次记录' : '删除整次记录' }}</button>
          </div>
        </details>
        <details v-if="analysisEvidence" class="replay-disclosure analysis-evidence">
          <summary><h2>处理记录与费用估算</h2><span class="disclosure-meta">{{ formatDuration(analysisTimings.total) }} · {{ formatCost(analysisCost.estimated_amount) }}</span><ArrowRight class="disclosure-chevron" aria-hidden="true" /></summary>
          <dl>
            <div><dt>处理链路</dt><dd>本地岩点 · {{ analysisEvidence.provider?.service || '人体姿态服务' }}（{{ analysisEvidence.provider?.region || '地域待确认' }}）</dd></div>
            <div><dt>抽帧计划</dt><dd>{{ formatNumber(analysisEvidence.sampling?.effective_fps) }} FPS · 计划 {{ analysisUsage.planned_requests || 0 }} 帧</dd></div>
            <div><dt>接口请求</dt><dd>实际 {{ analysisUsage.actual_requests || 0 }} 次 · 成功 {{ analysisUsage.successful_requests || 0 }} · 失败 {{ analysisUsage.failed_requests || 0 }}</dd></div>
            <div><dt>姿态结果</dt><dd>有效 {{ analysisUsage.successful_pose_frames || 0 }} 帧 · 无姿态 {{ analysisUsage.responses_without_pose || 0 }} · 解码失败 {{ analysisUsage.decode_failed_frames || 0 }} · 未处理 {{ analysisUsage.unprocessed_frames || 0 }}</dd></div>
            <div><dt>费用估算</dt><dd>{{ formatCost(analysisCost.estimated_amount) }}（{{ formatCost(analysisCost.unit_price) }}/成功请求）</dd></div>
            <div><dt>总耗时</dt><dd>{{ formatDuration(analysisTimings.total) }} · 姿态 {{ formatDuration(analysisTimings.pose) }} · 叠加视频 {{ formatDuration(analysisTimings.overlay) }}</dd></div>
            <div><dt>版本</dt><dd>{{ analysisEvidence.pipeline_version }} · 岩点 {{ analysisEvidence.models?.holds?.version || '尚未完成' }} · API {{ analysisEvidence.provider?.api_version || '待确认' }}</dd></div>
          </dl>
          <p>{{ analysisCost.basis }}</p>
        </details>
        </div>
    <details v-if="recentJobs.length" :key="activeJob?.id || 'recent-jobs'" :open="!activeJob && !selectedFile" class="replay-disclosure recent-section" aria-labelledby="recent-title">
      <summary><h2 id="recent-title">最近分析</h2><span class="disclosure-meta">{{ recentJobs.length }} 次 · 仅当前账号可见</span><ArrowRight class="disclosure-chevron" aria-hidden="true" /></summary>
      <button v-for="job in recentJobs" :key="job.id" type="button" class="recent-row" @click="selectJob(job)">
        <span class="recent-dot" :class="job.status" />
        <span><strong>{{ job.original_name }}</strong><small>{{ job.route_color }}线路 · {{ dateLabel(job.created_at) }}</small></span>
        <b>{{ jobStatusLabel(job) }}</b>
      </button>
    </details>
          </template>
        </UnifiedReplayPlayer>
        <template v-if="!result && !playbackUrl">
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
          <VideoCamera class="drop-icon" />
          <strong>选择攀爬视频</strong>
          <span>MP4、MOV 等常见视频 · 系统自动转码和压缩 · 单文件不超过 500 MB</span>
          <button type="button" class="secondary-button">浏览文件</button>
        </div>

        <div v-if="!isBusy && testVideoCases.length" class="test-video-cases">
          <div class="test-video-heading">
            <span class="test-video-mark" aria-hidden="true"><VideoCamera /></span>
            <div><strong>本地测试案例</strong><p>仅用于本机验收，不会随生产发布。</p></div>
          </div>
          <button
            v-for="item in testVideoCases"
            :key="item.id"
            type="button"
            class="test-video-case"
            :disabled="Boolean(loadingTestCaseId)"
            @click="useTestVideo(item)"
          >
            <span><strong>{{ item.label }}</strong><small>{{ item.description }} · {{ formatBytes(item.size_bytes) }}</small></span>
            <Loading v-if="loadingTestCaseId === item.id" />
            <b v-else>载入</b>
          </button>
        </div>
        </template>

        <div v-else-if="!result" class="playback-review" :class="{ 'has-action-focus': activeAction }">
          <div class="video-stage">
            <div class="video-canvas">
              <video
                ref="videoElement"
                :src="playbackUrl"
                controls
                playsinline
                preload="metadata"
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
              <div v-if="playerMode === 'interactive' && result" class="hold-overlay" :aria-hidden="!holdReviewMode">
                <span
                  v-for="hold in showHolds ? (result.holds || []) : []"
                  :key="hold.id"
                  class="hold-box"
                  :class="{ 'hold-box--inspected': hold.review_version === inspectedHoldReviewVersion }"
                  :style="holdStyle(hold)"
                ><b>{{ hold.id }}</b></span>
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
                <div v-if="showEvents && activeContactEvents.length" class="contact-badges">
                  <span v-for="event in activeContactEvents" :key="event.key">{{ limbNames[event.limb] }} → 岩点 {{ event.hold_id }}</span>
                </div>
                <span v-if="showPose && currentPose" class="pose-evidence" :class="{ nearby: !currentPoseExact }">{{ poseEvidenceLabel }}</span>
                <svg v-if="holdPreview" class="hold-preview-outline" viewBox="0 0 100 100" preserveAspectRatio="none" aria-label="待确认的岩点轮廓">
                  <polygon :points="holdPreviewPoints" />
                </svg>
                <span v-if="holdDraw" class="hold-draft-box" :style="holdDrawStyle" aria-hidden="true" />
                <button
                  v-if="holdReviewMode && !holdPreview"
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
            <button v-if="!isBusy" type="button" class="replace-video" @click="openPicker">更换视频</button>
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
        <div v-if="false" class="player-tools">
          <div class="player-options">
            <div v-if="activeJob?.id" class="playback-switch" role="group" aria-label="播放版本">
              <button
                type="button"
                :class="{ active: playbackKind === 'overlay' }"
                :disabled="!replayVideoAvailable"
                :aria-pressed="playbackKind === 'overlay'"
                @click="switchPlayback('overlay')"
              >复盘视频</button>
              <button
                type="button"
                :class="{ active: playbackKind === 'source' }"
                :disabled="!sourcePlayable"
                :aria-pressed="playbackKind === 'source'"
                @click="switchPlayback('source')"
              >原视频</button>
            </div>
            <div v-if="playerMode === 'interactive'" class="layer-controls" aria-label="叠加层开关">
              <label><input v-model="showHolds" type="checkbox" />岩点</label>
              <label><input v-model="showPose" type="checkbox" />采样骨架</label>
              <label><input v-model="showEvents" type="checkbox" />接触事件</label>
            </div>
            <p v-else-if="playerMode === 'rendered'">当前播放：复盘视频</p>
            <button v-if="visualState.ready && replayVideoAvailable" class="visual-replay-action" type="button" @click="viewVisualReplay">查看线路回放</button>
            <button v-if="canAddHoldAtPoint" class="hold-tool-action hold-tool-action--primary" type="button" :disabled="holdReviewSaving" :aria-pressed="holdReviewMode" @click="toggleHoldReview">{{ holdReviewMode ? '结束框选' : '框选补岩点' }}</button>
          </div>
          <p v-if="holdReviewMode" class="hold-review-hint" role="status">在暂停画面中拖框圈住一个漏检岩点，边缘可留少量墙面。松开后先看识别轮廓，偏到人物时不要确认；换帧请先结束框选。</p>
          <details v-if="holdReviewMode && !holdPreview" ref="holdCoordinateDetails" class="hold-coordinate-entry">
            <summary>无法拖框？输入画面百分比范围</summary>
            <form @submit.prevent="previewHoldFromFields">
              <label>左侧 <input ref="holdCoordinateFirstInput" v-model.number="holdRegionForm.left" type="number" min="0" max="100" step="1" required /></label>
              <label>顶部 <input v-model.number="holdRegionForm.top" type="number" min="0" max="100" step="1" required /></label>
              <label>右侧 <input v-model.number="holdRegionForm.right" type="number" min="0" max="100" step="1" required /></label>
              <label>底部 <input v-model.number="holdRegionForm.bottom" type="number" min="0" max="100" step="1" required /></label>
              <button type="submit" :disabled="holdPreviewLoading || holdReviewSaving">预览轮廓</button>
            </form>
          </details>
          <p v-if="holdPreviewLoading" class="hold-review-hint" role="status">正在描出岩点轮廓…</p>
          <div v-if="holdPreview" class="hold-preview-actions">
            <span>请核对高亮轮廓是否只覆盖岩点。{{ holdPreview.supporting_frames > 1 ? `已参考 ${holdPreview.supporting_frames} 帧一致画面。` : '附近缺少一致画面，请特别留意。' }}</span>
            <button type="button" :disabled="holdReviewSaving" @click="confirmHoldPreview">轮廓正确，确认补入</button>
            <button type="button" :disabled="holdReviewSaving" @click="holdPreview = null">重新框选</button>
          </div>
          <p v-if="holdReviewSaving" class="hold-review-hint" role="status">正在重新计算并生成视频，请稍候…</p>
          <p v-if="holdReviewError" class="hold-review-feedback hold-review-feedback--error" role="alert">{{ holdReviewError }}</p>
          <p v-if="holdReviewNotice" class="hold-review-feedback" role="status">{{ holdReviewNotice }}</p>
          <a v-if="replayVideoAvailable && !visualState.stale" class="export-action" :href="replayDownloadUrl">导出复盘视频</a>
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
        <input ref="fileInput" class="visually-hidden" type="file" accept="video/mp4,video/quicktime,video/x-m4v,video/webm,video/3gpp,video/3gpp2,video/x-matroska,.mp4,.mov,.m4v,.webm,.3gp,.3g2,.mkv" @change="onFileChange" />

        <div v-if="activeJob && !result" class="analysis-state" :class="activeJob.status" aria-live="polite">
          <div class="state-copy">
            <span class="state-mark"><Loading v-if="isBusy" /><CircleCheck v-else-if="activeJob.status === 'succeeded'" /><Warning v-else /></span>
            <div>
              <strong>{{ statusTitle }}</strong>
              <p>{{ statusDetail }}</p>
            </div>
            <b v-if="isBusy">{{ activeJob.progress || 0 }}%</b>
          </div>
          <div v-if="isBusy" class="progress-track"><i :style="{ transform: `scaleX(${(activeJob.progress || 0) / 100})` }" /></div>
          <div v-if="isBusy && analysisEvidence" class="run-summary" aria-label="本次处理计量摘要">
            <span>{{ formatNumber(analysisEvidence.sampling?.effective_fps) }} FPS 抽帧</span>
            <span>姿态 {{ analysisUsage.successful_pose_frames || 0 }}/{{ analysisUsage.planned_requests || 0 }} 帧</span>
            <span>估算 {{ formatCost(analysisCost.estimated_amount) }}</span>
            <span>{{ formatDuration(analysisTimings.total) }}</span>
          </div>
          <div v-if="['failed', 'cancelled'].includes(activeJob.status) && !isJobDeleting" class="state-actions">
            <button v-if="sourceAvailable" type="button" class="secondary-button" :disabled="!sampleConsent || !consentPolicy" @click="retryJob">重新分析</button>
            <p v-else>原视频已删除，这次复盘不能重新分析。</p>
          </div>
        </div>


      </div>

      <aside v-if="!result" class="setup-panel" aria-label="分析设置">
        <div>
          <h2>准备分析</h2>
          <p>画面尽量包含整面墙与攀爬者全身，手机固定不移动。</p>
        </div>

        <fieldset>
          <legend>已保存线路</legend>
          <label class="saved-route-choice" for="replay-saved-route">优先复用已确认岩点</label>
          <select id="replay-saved-route" v-model="selectedRouteId" :disabled="isBusy || isSubmitting" @change="chooseSavedRoute">
            <option value="">不选择，按本视频颜色候选识别</option>
            <option v-for="route in savedRoutes" :key="route.id" :value="route.id">{{ route.name || route.color_group + '线路' }} · {{ route.color_group }}</option>
          </select>
          <p class="setup-note">仅对已确认且能在视频中可靠对齐的岩点复用身份；无法对齐时仍需按颜色候选复核。</p>
        </fieldset>

        <fieldset>
          <legend>线路颜色</legend>
          <div class="color-options">
            <label v-for="color in colors" :key="color.value" :class="{ selected: routeColor === color.value }">
              <input v-model="routeColor" type="radio" name="route-color" :value="color.value" @change="choosePresetColor(color)" />
              <i :style="{ background: color.hex }" />
              <span>{{ color.value }}</span>
            </label>
          </div>
          <label class="saved-route-choice" for="replay-extra-color">其他相关颜色</label>
          <select id="replay-extra-color" :value="extendedColors.some((color) => color.value === routeColor) ? routeColor : ''" @change="chooseExtendedColor">
            <option value="">选择青色或棕色</option>
            <option v-for="color in extendedColors" :key="color.value" :value="color.value">{{ color.value }}</option>
          </select>
          <p v-if="!colors.some((color) => color.value === routeColor)" class="setup-note">当前为扩展颜色：{{ routeColor }}。也可使用调色盘或画面样本。</p>
          <div class="color-sample-tools">
            <label class="palette-action">
              <input :value="paletteHex" type="color" aria-label="打开调色盘选择线路颜色" @input="choosePaletteColor($event.target.value)" />
              <span>调色盘</span>
            </label>
            <button type="button" :disabled="!selectedFile || !videoMeta || isBusy" @click="startColorPicking">从画面点选样本岩点</button>
            <button v-if="colorSample" type="button" class="clear-color-sample" @click="clearColorSample">恢复快捷色</button>
          </div>
          <p v-if="colorSample" class="color-sample-status" role="status">
            <i :style="{ background: colorSample.hex }" />
            已{{ colorSample.source === 'video' ? '点选岩点' : '从调色盘' }}取色 {{ colorSample.hex.toUpperCase() }}，归入{{ routeColor }}；最终以岩点轮廓内颜色为准
          </p>
        </fieldset>

        <fieldset class="retention-options">
          <legend>原视频保留方式</legend>
          <label :class="{ selected: retentionMode === 'delete_after_processing' }">
            <input v-model="retentionMode" type="radio" name="retention-mode" value="delete_after_processing" :disabled="isBusy || isDeleting" />
            <span><strong>分析后自动删除</strong><small>成功后 24 小时内删除；失败或取消后保留 72 小时，方便重试。</small></span>
          </label>
          <label :class="{ selected: retentionMode === 'keep_private_original' }">
            <input v-model="retentionMode" type="radio" name="retention-mode" value="keep_private_original" :disabled="isBusy || isDeleting" />
            <span><strong>私密保留原视频</strong><small>仅当前账号可见，直到你手动删除。</small></span>
          </label>
        </fieldset>

        <label class="privacy-check">
          <input v-model="sampleConsent" type="checkbox" :disabled="!consentPolicy || isBusy || isDeleting" />
          <span>我同意本次处理：上传的视频在本系统整理为分析副本并按上方选择清理，上传的原始文件在转换成功后从服务器删除；人体姿态分析会把降帧后的单张画面发送至{{ consentPolicy?.provider || '指定姿态服务' }}，岩点在服务器本地识别。重试时需要重新同意。</span>
        </label>
        <p v-if="consentPolicy" class="consent-meta">{{ consentPolicy.service }} · {{ consentPolicy.region }} · 告知版本 {{ consentPolicy.version }}</p>
        <button v-if="activeConsentGranted" type="button" class="consent-action" @click="withdrawConsent">撤回本次授权</button>

        <section v-if="selectedFile" class="video-preflight" aria-label="视频处理说明">
          <div class="video-preflight__head"><strong>上传后由系统处理视频</strong><span>{{ videoMeta ? formatVideoMeta(videoMeta) : formatBytes(selectedFile.size) }}</span></div>
          <p>完整文件会上传到本系统，随后在后台自动修正方向、裁剪、降帧并转成不含原音频的 H.264 MP4；分析副本不超过 1920×1080（支持竖屏）、200 MB。手机里的原文件不会修改，只有抽样画面会发送给上述姿态服务。</p>
          <div v-if="videoMeta?.duration > MAX_VIDEO_SECONDS" class="video-trim">
            <strong>默认分析前 90 秒，也可以在这里调整片段</strong>
            <p>选择片段只改变本系统的分析范围，上传的仍是完整文件。</p>
            <div class="video-trim__fields">
              <label>开始 <input v-model.number="trimStartSeconds" type="number" min="0" :max="Math.max(0, videoMeta.duration - 1)" step="0.1" /></label>
              <label>结束 <input v-model.number="trimEndSeconds" type="number" :min="trimStartSeconds + 0.1" :max="videoMeta.duration" step="0.1" /></label>
            </div>
            <p class="video-trim__status" :class="{ invalid: !trimIsValid }">当前片段 {{ formatSeconds(trimDuration) }}<span v-if="!trimIsValid">，请选择不超过 90 秒的范围</span></p>
          </div>
          <p v-if="!videoMeta">手机浏览器无法预览此编码。仍可上传，服务器会读取视频；超过 90 秒时默认分析前 90 秒。如服务器也无法解码，任务会显示具体原因。</p>
        </section>

        <button type="button" class="primary-action" :disabled="!canSubmit" @click="submit">
          <Loading v-if="isBusy || isSubmitting" />
          <span>{{ isSubmitting ? (uploadProgress < 100 ? `正在上传 ${uploadProgress}%` : '正在创建后台任务') : (isBusy ? '正在处理' : '开始 AI 复盘') }}</span>
        </button>
        <button v-if="isBusy" type="button" class="cancel-action" @click="cancelJob">取消任务</button>
        <p v-if="formError" class="form-error" role="alert">{{ formError }}</p>
        <p v-if="formNotice" class="form-notice" role="status">{{ formNotice }}</p>

        <details class="replay-disclosure shooting-guide">
          <summary><h3>拍摄建议</h3><ArrowRight class="disclosure-chevron" aria-hidden="true" /></summary>
          <ul>
            <li><span>1</span>竖屏、横屏均可，机位保持固定</li>
            <li><span>2</span>从离地前开始，顶点稳定后结束</li>
            <li><span>3</span>选择单一颜色线路，减少人物遮挡</li>
          </ul>
        </details>
      </aside>
    </div>

    <details v-if="!result && recentJobs.length" :key="activeJob?.id || 'recent-jobs'" :open="!activeJob && !selectedFile" class="replay-disclosure recent-section" aria-labelledby="recent-title">
      <summary><h2 id="recent-title">最近分析</h2><span class="disclosure-meta">{{ recentJobs.length }} 次 · 仅当前账号可见</span><ArrowRight class="disclosure-chevron" aria-hidden="true" /></summary>
      <button v-for="job in recentJobs" :key="job.id" type="button" class="recent-row" @click="selectJob(job)">
        <span class="recent-dot" :class="job.status" />
        <span><strong>{{ job.original_name }}</strong><small>{{ job.route_color }}线路 · {{ dateLabel(job.created_at) }}</small></span>
        <b>{{ jobStatusLabel(job) }}</b>
      </button>
    </details>
  </section>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { ArrowLeft, ArrowRight, CircleCheck, Loading, RefreshRight, VideoCamera, Warning } from '@element-plus/icons-vue'
import climbReplayService from '../services/climbReplayService'
import { analysisDuration, analysisSeekTime, visualReplayState } from '../services/visualReplayPresentation.js'
import { photoRouteV2Service } from '../services/photoRouteService'
import { QUICK_ROUTE_COLORS, ROUTE_COLORS, hexToRgb, nearestRouteColor, rgbToHex } from '../constants/routeColors.js'
import UnifiedReplayPlayer from './UnifiedReplayPlayer.vue'

const colors = QUICK_ROUTE_COLORS
const extendedColors = ROUTE_COLORS.filter((color) => !QUICK_ROUTE_COLORS.includes(color))
const limbNames = { left_hand: '左手', right_hand: '右手', left_foot: '左脚', right_foot: '右脚' }
const manualTechniqueNames = ['高抬脚', '锁臂', '旗式', '脚上方重心转移', '动态点', '跳跃', '主动摆荡换点', '抓点后制摆', '开门摆动']
const fileInput = ref(null)
const videoElement = ref(null)
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
const videoMeta = ref(null)
const trimStartSeconds = ref(0)
const trimEndSeconds = ref(90)
const MAX_VIDEO_SECONDS = 90
const MAX_INPUT_BYTES = 500 * 1024 * 1024
const routeColor = ref('绿色')
const selectedRouteId = ref('')
const savedRoutes = ref([])
const paletteHex = ref('#2f8c62')
const colorSample = ref(null)
const colorPicking = ref(false)
const colorSampleCanvas = ref(null)
let sampledFrameRect = null
const retentionMode = ref('delete_after_processing')
const sampleConsent = ref(false)
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
const visualState = computed(() => visualReplayState(activeJob.value))
const isVisualPlayback = computed(() => playbackKind.value === 'overlay'
  && visualState.value.start !== null && playbackTime.value >= visualState.value.start)
const canRefineSampledHolds = computed(() => activeJob.value?.status === 'succeeded'
  && !isJobDeleting.value
  && !activeJob.value?.segment_reviews?.length
  && sourcePlayable.value
  && result.value?.hold_evidence?.selection === 'color_candidates_need_review'
  && !activeJob.value?.hold_review_history?.length)
const canAddHoldAtPoint = computed(() => activeJob.value?.status === 'succeeded'
  && sourcePlayable.value && !isJobDeleting.value && !activeJob.value?.segment_reviews?.length)
const canUndoManualHold = computed(() => canAddHoldAtPoint.value
  && (result.value?.holds || []).some((hold) => ['user_confirmed_video_click', 'user_confirmed_video_candidate'].includes(hold.identity_source)))
const manualHoldOperations = computed(() => {
  const holds = result.value?.holds || []
  const fps = Number(activeJob.value?.video?.fps)
  let ordinal = 0
  return (activeJob.value?.hold_review_history || [])
    .filter((entry) => ['add_hold_at_point', 'promote_candidate'].includes(entry.operation))
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
const activeContactEvents = computed(() => contactEvents.value.filter((event) => {
  const end = Number.isFinite(Number(event.end_time_seconds)) ? Number(event.end_time_seconds) : Number(event.start_time_seconds)
  return playbackTime.value >= Number(event.start_time_seconds) && playbackTime.value <= end + .08
}))
const currentRun = computed(() => {
  const attempt = activeJob.value?.attempt || 1
  return [...(activeJob.value?.analysis_runs || [])].reverse().find((run) => run.attempt === attempt)
})
const analysisEvidence = computed(() => result.value?.analysis || currentRun.value?.analysis || null)
const analysisUsage = computed(() => analysisEvidence.value?.usage || {})
const analysisCost = computed(() => analysisEvidence.value?.cost || {})
const analysisTimings = computed(() => analysisEvidence.value?.timings_ms || {})
const currentConsentEvent = computed(() => {
  const attempt = activeJob.value?.attempt || 1
  return [...(activeJob.value?.consent_history || [])].reverse().find((event) => event.attempt === attempt)
})
const activeConsentGranted = computed(() => currentConsentEvent.value?.event === 'granted')
const trimDuration = computed(() => Math.max(0, Number(trimEndSeconds.value || 0) - Number(trimStartSeconds.value || 0)))
const trimIsValid = computed(() => !videoMeta.value || (trimStartSeconds.value >= 0 && trimEndSeconds.value > trimStartSeconds.value && trimDuration.value <= MAX_VIDEO_SECONDS + .05 && trimEndSeconds.value <= videoMeta.value.duration + .05))
const canSubmit = computed(() => selectedFile.value && routeColor.value && sampleConsent.value && consentPolicy.value && trimIsValid.value && !isBusy.value && !isSubmitting.value && !isDeleting.value)
const statusTitle = computed(() => isJobDeleting.value ? '正在删除整次记录' : ({
  queued: '任务正在排队', running: activeJob.value?.stage || '正在分析视频',
  succeeded: '分析完成', failed: '分析未完成', cancelled: '任务已取消',
}[activeJob.value?.status] || '准备中'))
const statusDetail = computed(() => {
  if (isJobDeleting.value) return '正在停止任务并删除原视频、复盘指标与派生文件。'
  if (activeJob.value?.status === 'failed') return activeJob.value.error || '请检查视频和人体姿态服务配置后重试。'
  if (activeJob.value?.status === 'cancelled') return sourceAvailable.value ? '原视频仍可用于重新分析。' : '原视频已删除，本次任务不能重新分析。'
  if (activeJob.value?.status === 'succeeded') return '结果为机器估算，请结合原视频复核。'
  if (activeJob.value?.status === 'queued') return uploadProgress.value < 100 ? `视频上传 ${uploadProgress.value}%` : '前方任务完成后会自动开始。'
  return '系统正在处理视频并识别动作；可以稍后在任务列表查看结果。'
})
const sourceRetentionLabel = computed(() => {
  const source = sourceMedia.value
  if (!source) return '未记录原视频保留状态'
  if (source.status === 'deleted') return `已于 ${dateLabel(source.deleted_at)} 删除，复盘指标仍保留`
  if (source.retention_mode === 'keep_private_original') return '私密保留中，仅当前账号可见'
  if (source.delete_at) return `计划于 ${dateLabel(source.delete_at)} 自动删除`
  return '任务结束后将按规则自动清理'
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

function openPicker() { fileInput.value?.click() }
function applyColorSample(rgb, source, point = null) {
  const nearest = nearestRouteColor(rgb)
  const hex = rgbToHex(rgb)
  routeColor.value = nearest.value
  paletteHex.value = hex
  colorSample.value = {
    source,
    hex,
    rgb: rgb.map((value) => Math.max(0, Math.min(255, Math.round(value)))),
    time_seconds: source === 'video' ? Number((videoElement.value?.currentTime || 0).toFixed(3)) : null,
    point_xy: point,
  }
}
function choosePaletteColor(hex) {
  const rgb = hexToRgb(hex)
  if (rgb) applyColorSample(rgb, 'palette')
}
function choosePresetColor(color) {
  paletteHex.value = color.hex
  colorSample.value = null
  colorPicking.value = false
}
function chooseExtendedColor(event) {
  const color = extendedColors.find((item) => item.value === event.target.value)
  if (!color) return
  routeColor.value = color.value
  choosePresetColor(color)
}
function clearColorSample() {
  colorSample.value = null
  colorPicking.value = false
  paletteHex.value = ROUTE_COLORS.find((color) => color.value === routeColor.value)?.hex || '#2f8c62'
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
  formNotice.value = `已点选样本岩点。分析时将先确认点击位置落在岩点轮廓内，再取轮廓内部的实际颜色。`
}
function cancelColorPicking() { colorPicking.value = false; sampledFrameRect = null }
let selectedFileToken = 0
async function inspectVideo(file) {
  const url = URL.createObjectURL(file)
  try {
    const metadata = await new Promise((resolve, reject) => {
      const probe = document.createElement('video')
      const timer = window.setTimeout(() => reject(new Error('浏览器无法预览此视频编码')), 8000)
      probe.preload = 'metadata'
      probe.onloadedmetadata = () => { window.clearTimeout(timer); resolve({ width: probe.videoWidth, height: probe.videoHeight, duration: probe.duration }) }
      probe.onerror = () => { window.clearTimeout(timer); reject(new Error('浏览器无法预览此视频编码')) }
      probe.src = url
    })
    if (!metadata.width || !metadata.height || !Number.isFinite(metadata.duration)) throw new Error('无法读取视频尺寸或时长，请重新选择文件。')
    return metadata
  } finally { URL.revokeObjectURL(url) }
}
async function useFile(file) {
  formError.value = ''
  formNotice.value = ''
  if (!file) return
  const token = ++selectedFileToken
  const supportedTypes = new Set(['video/mp4', 'video/quicktime', 'video/x-m4v', 'video/webm', 'video/3gpp', 'video/3gpp2', 'video/x-matroska'])
  const supportedExtensions = ['.mp4', '.mov', '.m4v', '.webm', '.3gp', '.3g2', '.mkv']
  if (!supportedTypes.has(file.type.toLowerCase()) && !supportedExtensions.some((extension) => file.name.toLowerCase().endsWith(extension))) {
    formError.value = '请选择 MP4、MOV、M4V、WebM、3GP 或 MKV 视频。'
    return
  }
  if (file.size > MAX_INPUT_BYTES) {
    formError.value = '视频不能超过 500 MB。'
    return
  }
  if (previewUrl.value) URL.revokeObjectURL(previewUrl.value)
  selectedFile.value = file
  previewUrl.value = URL.createObjectURL(file)
  videoMeta.value = null
  trimStartSeconds.value = 0
  trimEndSeconds.value = MAX_VIDEO_SECONDS
  activeJob.value = null
  deletionReceipt.value = null
  playbackTime.value = 0
  preferredPlaybackKind.value = 'overlay'
  pendingPlaybackState.value = null
  window.clearTimeout(deletionTimer)
  sampleConsent.value = false
  clearColorSample()
  try {
    const metadata = await inspectVideo(file)
    if (token !== selectedFileToken) return
    videoMeta.value = metadata
    trimEndSeconds.value = Math.min(MAX_VIDEO_SECONDS, videoMeta.value.duration)
    formNotice.value = videoMeta.value.duration > MAX_VIDEO_SECONDS
      ? '视频已读取。系统默认分析前 90 秒；如需调整，可修改下面的起止时间。'
      : '视频已读取。上传后系统会自动整理视频。'
  } catch (_) {
    if (token !== selectedFileToken) return
    formNotice.value = '手机浏览器暂时无法预览此视频；仍可上传，服务器会继续尝试处理。'
  }
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
    formNotice.value = `已载入${testCase.label}。请选择线路颜色并阅读授权说明后开始复盘。`
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
async function submit() {
  if (!canSubmit.value) return
  if (colorSample.value?.source === 'video' && videoMeta.value?.duration > MAX_VIDEO_SECONDS &&
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
      routeColor: routeColor.value,
      routeId: selectedRouteId.value,
      routeColorSample: colorSample.value,
      consentVersion: consentPolicy.value.version,
      consentGranted: true,
      retentionMode: retentionMode.value,
      trimStartSeconds: videoMeta.value?.duration > MAX_VIDEO_SECONDS ? Number(trimStartSeconds.value) : 0,
      trimEndSeconds: videoMeta.value?.duration > MAX_VIDEO_SECONDS ? Number(trimEndSeconds.value) : null,
    }, (value) => { uploadProgress.value = value })
    if (previewUrl.value) URL.revokeObjectURL(previewUrl.value)
    previewUrl.value = ''
    selectedFile.value = null
    videoMeta.value = null
    sampleConsent.value = false
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
  activeJob.value = null
  selectedFile.value = null
  videoMeta.value = null
  sampleConsent.value = false
  if (previewUrl.value) URL.revokeObjectURL(previewUrl.value)
  previewUrl.value = ''
  playbackTime.value = 0
  preferredPlaybackKind.value = 'overlay'
  pendingPlaybackState.value = null
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
  if (!sampleConsent.value || !consentPolicy.value) {
    formError.value = '重新分析会再次发送抽样画面，请先重新勾选本次处理授权。'
    return
  }
  formError.value = ''
  formNotice.value = ''
  try {
    activeJob.value = await climbReplayService.retry(activeJob.value.id, consentPolicy.value.version)
    sampleConsent.value = false
    schedulePoll()
    await loadJobs()
  }
  catch (error) { formError.value = errorText(error) }
}
async function withdrawConsent() {
  if (!activeJob.value?.id) return
  formError.value = ''
  formNotice.value = ''
  try {
    activeJob.value = await climbReplayService.withdrawConsent(activeJob.value.id)
    const event = [...(activeJob.value.consent_history || [])].reverse().find((item) => item.event === 'withdrawn')
    formNotice.value = event?.outcome || '已记录授权撤回。'
    sampleConsent.value = false
    await loadJobs()
  } catch (error) { formError.value = errorText(error) }
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
function selectJob(job) {
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
  sampleConsent.value = false
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
async function loadSavedRoutes() {
  try { savedRoutes.value = await photoRouteV2Service.routes() }
  catch (_) { savedRoutes.value = [] }
}
function chooseSavedRoute() {
  const selected = savedRoutes.value.find((route) => route.id === selectedRouteId.value)
  if (selected?.color_group) routeColor.value = selected.color_group
}
function holdStyle(hold) {
  const [x, y, width, height] = hold.bbox || [0, 0, 0, 0]
  return { left: `${x * 100}%`, top: `${y * 100}%`, width: `${width * 100}%`, height: `${height * 100}%` }
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
function toggleHoldReview() {
  holdReviewError.value = ''
  holdReviewNotice.value = ''
  holdReviewMode.value = !holdReviewMode.value
  holdPreview.value = null
  holdDraw.value = null
  if (holdReviewMode.value) {
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
  if (!holdReviewMode.value || holdReviewSaving.value || holdPreviewLoading.value || !activeJob.value?.id) return
  if (event.pointerType === 'mouse' && event.button !== 0) return
  event.preventDefault()
  const position = holdPointerPosition(event)
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
  } catch (error) {
    holdReviewError.value = error.response?.data?.detail || errorText(error) || '框内没有找到可靠岩点，请框紧一些或换帧。'
  } finally { holdPreviewLoading.value = false }
}
async function confirmHoldPreview() {
  if (!holdPreview.value || holdReviewSaving.value || !activeJob.value?.id) return
  const { point_xy:point, region_xyxy:region, time_seconds:previousTime } = holdPreview.value
  const jobId = activeJob.value.id
  holdReviewSaving.value = true
  holdReviewError.value = ''
  try {
    const updated = await climbReplayService.addHoldAtPoint(jobId, point, previousTime, region)
    if (activeJob.value?.id !== jobId) return
    activeJob.value = updated
    holdPreview.value = null
    holdReviewMode.value = false
    inspectedHoldReviewVersion.value = activeJob.value.hold_review_history?.at(-1)?.version || null
    pendingPlaybackState.value = { time:previousTime, shouldPlay:false }
    holdReviewNotice.value = '已补入确认的岩点并重算复盘。'
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
    holdReviewNotice.value = `已撤销第 ${operation.ordinal} 次补点；其他补点保留，复盘结果已重新计算。`
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
    holdReviewNotice.value = `当前保留 ${activeJob.value.result.hold_refinement.after} 个岩点（原为 ${activeJob.value.result.hold_refinement.before} 个）。被移出的点仍可手动补回。`
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
function handlePlaybackLoaded() {
  const video = videoElement.value
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
function handlePlaybackError() {
  if (playbackKind.value !== 'overlay' || !sourcePlayable.value) return
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
function formatVideoMeta(meta) {
  return `${meta.width}×${meta.height} · ${formatSeconds(meta.duration)} · ${formatBytes(selectedFile.value?.size)}`
}
function jobStatusLabel(job) {
  if (job.deletion?.state === 'queued') return '删除中'
  return ({ queued: '排队中', running: '分析中', succeeded: '已完成', failed: '失败', cancelled: '已取消' })[job.status] || job.status
}
function dateLabel(value) {
  if (!value) return ''
  return new Intl.DateTimeFormat('zh-CN', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' }).format(new Date(value))
}

watch([() => activeJob.value?.id, canRefineSampledHolds, holdReviewSaving], ([jobId, eligible, saving]) => {
  if (jobId && eligible && !saving && !autoRefineAttempted.has(jobId)) {
    autoRefineAttempted.add(jobId)
    refineSampledHolds()
  }
})
watch(() => visualState.value.stale, () => updatePlaybackEvidence())
onMounted(async () => {
  loadConsentPolicy(); loadTestVideoInfo(); loadSavedRoutes()
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
  window.clearTimeout(pollTimer)
  window.clearTimeout(deletionTimer)
  if (previewUrl.value) URL.revokeObjectURL(previewUrl.value)
})
</script>

<style scoped>
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
.hold-preview-actions{display:flex;align-items:center;flex-wrap:wrap;gap:8px 12px;padding:10px 14px;background:#17231d;color:#fff}
.hold-preview-actions span{margin-right:auto;font-size:13px}
.hold-preview-actions button{min-height:44px;padding:8px 12px;border:1px solid #a8d6a9;border-radius:8px;background:#e9f8e9;color:#17351f;font-weight:700;cursor:pointer}
.hold-preview-actions button:disabled{opacity:.6;cursor:wait}
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
.saved-route-choice{display:block;font-size:12px;color:var(--ui-ink-muted);margin-bottom:6px}
#replay-saved-route,#replay-extra-color{width:100%;min-height:40px;padding:0 10px;border:1px solid var(--ui-line-strong);border-radius:var(--ui-radius-small);background:var(--ui-surface);color:var(--ui-ink);font:inherit}
.setup-note,.hold-evidence-note{font-size:12px;line-height:1.55;color:var(--ui-ink-muted)}
.replay-page{max-width:1400px;margin:0 auto;padding:34px 32px 80px;color:var(--ui-ink)}
.replay-page ::selection{background:var(--ui-brand-soft);color:var(--ui-brand-ink)}
.replay-page :is(button,input,select,a,summary):focus-visible{outline:3px solid var(--ui-focus-halo);outline-offset:2px}
.replay-heading{display:flex;align-items:flex-end;justify-content:space-between;gap:24px;margin-bottom:24px}
.replay-heading h1{margin:0;font-size:clamp(30px,3vw,38px);font-weight:650;letter-spacing:-.03em;line-height:1.08}
.replay-heading p{max-width:65ch;margin:8px 0 0;color:var(--ui-ink-muted);font-size:14px}
.prototype-badge{flex:none;padding:5px 9px;border:1px solid var(--ui-line);border-radius:999px;background:rgba(255,255,255,.56);color:var(--ui-ink-muted);font-size:11px;font-weight:600}
.replay-workspace{display:grid;grid-template-columns:minmax(0,1fr) 330px;gap:22px;align-items:start}
.replay-workspace.review-mode{grid-template-columns:minmax(0,1fr)}
.video-column,.setup-panel,.recent-section{border:1px solid var(--ui-line);border-radius:16px;background:var(--ui-surface)}
.video-column{min-width:0;overflow:hidden}
.video-drop{min-height:540px;padding:40px;display:grid;place-items:center;align-content:center;gap:12px;background:#242629;color:#fff;text-align:center;cursor:pointer;transition:background .18s ease-out}
.video-drop.dragging,.video-drop:hover{background:#2d3033}.drop-icon{width:42px;height:42px;color:var(--ui-brand)}
.video-drop strong{font-size:21px}.video-drop>span{color:#bfc2c4;font-size:13px}
.secondary-button,.replace-video,.cancel-action{min-height:38px;padding:0 15px;border:1px solid var(--ui-line-strong);border-radius:var(--ui-radius-small);background:var(--ui-surface);color:var(--ui-ink);font:inherit;font-size:13px;font-weight:600;cursor:pointer}.secondary-button:disabled{cursor:not-allowed;opacity:.45}
.video-drop .secondary-button{margin-top:8px;border-color:#696c70;background:transparent;color:#fff}
.test-video-cases{padding:16px 20px 18px;border-top:1px solid var(--ui-line);background:var(--ui-surface-subtle);display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px}.test-video-heading{grid-column:1/-1;min-width:0;margin-bottom:3px;display:grid;grid-template-columns:36px minmax(0,1fr);align-items:center;gap:12px}.test-video-mark{width:34px;height:34px;border-radius:10px;background:var(--ui-brand-soft);color:var(--ui-brand-ink);display:grid;place-items:center}.test-video-mark svg{width:18px}.test-video-heading strong{font-size:13px}.test-video-heading p{margin:3px 0 0;color:var(--ui-ink-muted);font-size:12px}.test-video-case{min-width:0;padding:11px 12px;border:1px solid var(--ui-line);border-radius:var(--ui-radius-small);background:var(--ui-surface);color:var(--ui-ink);display:flex;align-items:center;justify-content:space-between;gap:10px;text-align:left;font:inherit;cursor:pointer}.test-video-case:hover:not(:disabled){border-color:var(--ui-line-strong);background:var(--ui-surface-subtle)}.test-video-case:disabled{cursor:not-allowed;opacity:.55}.test-video-case>span{min-width:0;display:grid;gap:3px}.test-video-case strong{font-size:12px}.test-video-case small{color:var(--ui-ink-muted);font-size:11px;line-height:1.4;overflow-wrap:anywhere}.test-video-case b{flex:none;color:var(--ui-ink-muted);font-size:11px}.test-video-case svg{flex:none;width:15px;animation:spin 1s linear infinite}
.playback-review{display:grid;min-width:0;background:#0e100f}
.playback-review.has-action-focus{grid-template-columns:minmax(0,1fr) 280px}
.video-stage{position:relative;min-width:0;min-height:440px;max-height:680px;background:#0e100f;display:flex;align-items:center;justify-content:center;overflow:hidden}
.video-canvas{position:relative;max-width:100%;max-height:650px;display:inline-flex}
.video-stage video{display:block;width:auto;height:auto;max-width:100%;max-height:650px;object-fit:contain}
.color-sample-canvas{position:absolute;inset:0;width:100%;height:100%;cursor:crosshair;background:#111;z-index:6}.color-sample-hint{position:absolute;z-index:7;left:50%;top:14px;max-width:calc(100% - 28px);padding:7px 11px;border-radius:9px;background:rgba(14,16,15,.88);color:#fff;font-size:12px;line-height:1.35;transform:translateX(-50%);pointer-events:none;box-shadow:0 4px 16px rgba(0,0,0,.28)}
.hold-overlay{position:absolute;inset:0;margin:auto;width:100%;height:100%;pointer-events:none}
.hold-box{position:absolute;border:2px solid var(--ui-brand);border-radius:7px;box-shadow:0 3px 12px rgba(0,0,0,.28)}
.hold-box--inspected{border-width:3px;border-color:#68eee0;background:rgba(36,169,158,.2);box-shadow:0 0 0 4px rgba(16,24,22,.8),0 0 0 7px #68eee0}
.hold-box b{position:absolute;top:-10px;left:-8px;min-width:21px;height:21px;padding:0 4px;border-radius:7px;background:var(--ui-brand);color:var(--ui-brand-ink);display:grid;place-items:center;font-size:11px}
.pose-overlay{position:absolute;inset:0;width:100%;height:100%;overflow:visible}.pose-overlay line{stroke:#6ce0d2;stroke-width:3;stroke-linecap:round}.pose-overlay circle{fill:#d6fff9;stroke:#155d55;stroke-width:1.5}.pose-evidence{position:absolute;left:12px;top:12px;padding:6px 9px;border-radius:8px;background:rgba(17,92,83,.9);color:#fff;font-size:11px;font-weight:650;box-shadow:0 3px 12px rgba(0,0,0,.24)}.pose-evidence.nearby{background:rgba(47,50,52,.9);border:1px dashed rgba(255,255,255,.7)}.contact-badges{position:absolute;left:12px;bottom:12px;display:flex;flex-wrap:wrap;gap:6px}.contact-badges span{padding:5px 8px;border-radius:7px;background:rgba(21,76,132,.92);color:#fff;font-size:11px;font-weight:650;box-shadow:0 3px 12px rgba(0,0,0,.24)}
.replace-video{position:absolute;right:16px;top:16px;min-height:34px;padding:0 13px;border-color:rgba(255,255,255,.18);border-radius:999px;background:rgba(14,16,15,.76);color:#fff;backdrop-filter:blur(8px)}
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
.setup-panel{position:sticky;top:86px;padding:24px}.setup-panel h2,.result-report h2{margin:0;font-size:20px}.setup-panel>div>p{margin:7px 0 0;color:var(--ui-ink-muted);font-size:13px;line-height:1.6}.setup-panel fieldset{margin:26px 0 0;padding:0;border:0}.setup-panel legend{margin-bottom:10px;font-size:13px;font-weight:600}
.color-options{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:7px}.color-options label{min-height:42px;padding:0 10px;border:1px solid var(--ui-line);border-radius:var(--ui-radius-small);display:flex;align-items:center;gap:8px;font-size:13px;cursor:pointer}.color-options label.selected{border-color:var(--ui-ink);background:var(--ui-surface-subtle)}.color-options label:focus-within{outline:2px solid var(--ui-brand);outline-offset:2px}.color-options input{position:absolute;opacity:0;pointer-events:none}.color-options i{width:14px;height:14px;border:1px solid rgba(0,0,0,.28);border-radius:50%}
.color-sample-tools{margin-top:9px;display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:7px}.color-sample-tools button,.palette-action{min-height:38px;padding:0 10px;border:1px solid var(--ui-line-strong);border-radius:var(--ui-radius-small);background:var(--ui-surface);color:var(--ui-ink);display:flex;align-items:center;justify-content:center;gap:8px;font:inherit;font-size:12px;font-weight:600;cursor:pointer}.color-sample-tools button:hover:not(:disabled),.palette-action:hover{background:var(--ui-surface-subtle)}.color-sample-tools button:disabled{cursor:not-allowed;opacity:.45}.palette-action input{position:static;width:22px;height:22px;padding:0;border:0;opacity:1;pointer-events:auto;background:transparent;cursor:pointer}.clear-color-sample{grid-column:1/-1}.color-sample-status{margin:9px 0 0;color:var(--ui-ink-muted);font-size:11px;line-height:1.55;display:grid;grid-template-columns:14px minmax(0,1fr);gap:7px;align-items:start}.color-sample-status i{width:14px;height:14px;margin-top:2px;border:1px solid rgba(0,0,0,.28);border-radius:50%}
.retention-options{display:grid;gap:7px}.retention-options label{padding:11px;border:1px solid var(--ui-line);border-radius:var(--ui-radius-small);display:grid;grid-template-columns:16px 1fr;gap:9px;align-items:start;cursor:pointer}.retention-options label.selected{border-color:var(--ui-ink);background:var(--ui-surface-subtle)}.retention-options input{width:15px;height:15px;margin:2px 0 0;accent-color:var(--ui-ink)}.retention-options span{display:grid;gap:3px}.retention-options strong{font-size:12px}.retention-options small{color:var(--ui-ink-muted);font-size:11px;line-height:1.5}
.privacy-check{margin-top:22px;display:grid;grid-template-columns:17px 1fr;gap:9px;color:var(--ui-ink-muted);font-size:12px;line-height:1.5;cursor:pointer}.privacy-check input{width:16px;height:16px;margin:1px 0;accent-color:var(--ui-ink)}
.consent-meta{margin:8px 0 0 26px;color:var(--ui-ink-faint);font-size:11px;line-height:1.5;overflow-wrap:anywhere}.consent-action{margin:8px 0 0 26px;padding:0;border:0;background:transparent;color:var(--ui-ink-muted);font:inherit;font-size:12px;text-decoration:underline;text-underline-offset:3px;cursor:pointer}.consent-action:hover{color:var(--ui-ink)}
.video-preflight{margin-top:16px;padding:14px 16px;border:1px solid var(--ui-line);border-radius:var(--ui-radius-control);background:var(--ui-surface-subtle);color:var(--ui-ink-muted);font-size:12px;line-height:1.55}.video-preflight__head{display:flex;align-items:baseline;justify-content:space-between;gap:12px;color:var(--ui-ink)}.video-preflight__head span{font-size:11px;color:var(--ui-ink-faint);font-variant-numeric:tabular-nums}.video-preflight p{margin:7px 0 0}.video-trim{margin-top:12px;padding-top:12px;border-top:1px solid var(--ui-line);color:var(--ui-ink)}.video-trim>p{color:var(--ui-ink-muted)}.video-trim__fields{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-top:10px}.video-trim__fields label{display:grid;gap:5px;color:var(--ui-ink-muted);font-size:11px}.video-trim__fields input{width:100%;min-height:34px;padding:0 9px;border:1px solid var(--ui-line-strong);border-radius:8px;background:var(--ui-surface);color:var(--ui-ink);font:inherit}.video-trim__status{font-variant-numeric:tabular-nums}.video-trim__status.invalid{color:var(--ui-danger)}
.primary-action{width:100%;min-height:48px;margin-top:16px;border:0;border-radius:var(--ui-radius-control);background:var(--ui-brand);color:var(--ui-brand-ink);display:flex;align-items:center;justify-content:center;gap:8px;font:inherit;font-weight:700;cursor:pointer}.primary-action:hover:not(:disabled){background:var(--ui-brand-hover)}.primary-action:disabled{cursor:not-allowed;opacity:.45}.primary-action svg{width:17px;animation:spin 1s linear infinite}.cancel-action{width:100%;margin-top:8px}.form-error,.form-notice{margin:12px 0 0;font-size:12px;line-height:1.5}.form-error{color:var(--ui-danger)}.form-notice{color:var(--ui-success)}
.shooting-guide{margin-top:28px;padding-top:22px;border-top:1px solid var(--ui-line)}.shooting-guide h3,.sequence-block h3{margin:0;font-size:13px}.shooting-guide ul{margin:13px 0 0;padding:0;list-style:none;display:grid;gap:12px}.shooting-guide li{display:grid;grid-template-columns:22px 1fr;gap:8px;color:var(--ui-ink-muted);font-size:12px;line-height:1.5}.shooting-guide li span{width:21px;height:21px;border-radius:7px;background:var(--ui-surface-subtle);color:var(--ui-ink);display:grid;place-items:center;font-weight:600}
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
.shooting-guide.replay-disclosure{padding-top:0}
.shooting-guide.replay-disclosure ul{margin-top:0}
.replay-disclosure .comparison-error{color:var(--ui-danger)}
.visually-hidden{position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap;border:0}
@keyframes spin{to{transform:rotate(360deg)}}
@media(max-width:900px){.replay-page{padding:16px 16px 88px}.replay-heading{display:none}.replay-workspace{grid-template-columns:1fr}.setup-panel{position:static}.video-drop{min-height:340px}.video-stage{height:min(56vw,390px);min-height:0;max-height:390px}.video-canvas{height:100%;max-height:100%}.video-stage video{max-height:100%}.color-options{grid-template-columns:repeat(2,minmax(0,1fr))}}
@media(max-width:720px){.playback-review.has-action-focus{grid-template-columns:1fr}.action-focus{min-height:156px;padding:17px 16px 16px;border-top:1px solid rgba(255,255,255,.08);border-left:0}.action-focus-name{margin-top:14px;grid-template-columns:40px minmax(0,1fr);gap:12px}.action-focus-name>span{width:40px;height:40px}.action-focus-name strong{font-size:18px}.action-focus-name p{font-size:13px}.action-focus-name small{margin-top:4px}.action-focus-actions{margin-top:16px}.player-tools{align-items:flex-start;flex-wrap:wrap}}
@media(max-width:650px){.test-video-cases{grid-template-columns:1fr}}
@media(max-width:520px){.video-column{border-radius:14px}.video-stage{height:58vw;max-height:260px}.action-focus{min-height:154px}.action-focus-head{position:absolute;right:16px;margin-top:2px}.action-focus-head>strong{display:none}.action-focus-name strong{font-size:18px}.action-focus-actions button{min-height:40px}.test-video-cases{padding:14px 16px}.color-options{grid-template-columns:repeat(4,1fr)}.limb-table>div{grid-template-columns:58px 64px 1fr}.result-report{padding:20px 16px 0}.result-summary>strong{font-size:21px}.run-summary{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:7px 12px}.analysis-evidence dl{grid-template-columns:1fr}.analysis-evidence dl>div{grid-template-columns:70px minmax(0,1fr)}.layer-controls{gap:8px 12px}.event-timeline{padding:15px 14px 16px}.event-timeline button{width:68px}.event-timeline li:not(:last-child)::after{left:46px;width:22px}.media-row{display:grid;gap:7px}.media-actions{justify-content:flex-start;flex-wrap:wrap}.media-record-actions{justify-content:flex-start}}
@media(max-width:520px){.replay-detail-sections,.recent-section{padding-right:16px;padding-left:16px}.replay-disclosure>summary{grid-template-columns:minmax(0,1fr) 16px;gap:3px 12px}.replay-disclosure>summary .disclosure-meta{grid-column:1;justify-self:start;text-align:left}.disclosure-chevron{grid-column:2;grid-row:1 / 3;align-self:center}.replay-disclosure>summary :is(h2,h3),.disclosure-title{font-size:14px}}
@media(prefers-reduced-motion:reduce){.progress-track i,.video-drop,.disclosure-chevron{transition:none}.running .state-mark svg,.queued .state-mark svg,.primary-action svg,.test-video-case svg{animation:none}}
</style>
