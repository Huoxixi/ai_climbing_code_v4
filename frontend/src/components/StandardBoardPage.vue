<template>
  <section class="page standard-board-page">
      <div class="page-header standard-page-header">
        <div>
          <p class="eyebrow">标准线路数据</p>
          <h2>标准线路库</h2>
          <p class="standard-page-summary">浏览标准线路、查看岩板预览，或生成新的候选线路。</p>
        </div>
        <div class="command-row standard-header-actions">
          <el-button class="standard-refresh-button" :icon="Refresh" aria-label="刷新线路" title="刷新线路" :loading="standardBoard.loading" @click="fetchStandardRoutes"><span>刷新</span></el-button>
          <el-button type="primary" :loading="standardBoard.generating" @click="generateStandardRoute">生成候选线路</el-button>
        </div>
      </div>

      <el-segmented
        class="standard-mode-switch"
        v-model="standardBoard.mode"
        :options="[
          { label: '线路库', value: 'routes' },
          { label: '待修复路线', value: 'repairs' },
        ]"
        @change="handleStandardModeChange"
      />

      <button class="mobile-filter-toggle" type="button" :aria-expanded="filtersExpanded" @click="filtersExpanded = !filtersExpanded">
        <span><strong>筛选与排序</strong><small>{{ filterSummary }}</small></span>
        <ArrowDown :class="{ rotated: filtersExpanded }" />
      </button>

      <section class="section-block standard-filters" :class="{ 'is-mobile-open': filtersExpanded }">
        <label v-if="standardBoard.mode === 'routes'" class="filter-field filter-search-field"><span>搜索</span><el-input v-model="standardBoard.filters.q" clearable placeholder="名称、来源 ID 或定线者" :prefix-icon="Search" @keyup.enter="applyAndClose" /></label>
        <label v-if="standardBoard.mode === 'routes'" class="filter-field"><span>难度</span><el-select v-model="standardBoard.filters.difficulty" placeholder="选择难度"><el-option v-for="grade in standardBoard.difficulties" :key="grade" :label="grade" :value="grade" /></el-select></label>
        <label v-if="standardBoard.mode === 'routes'" class="filter-field filter-sort-field"><span>排序</span><el-select v-model="standardBoard.filters.sort" placeholder="选择排序"><el-option label="综合评分优先" value="score_desc" /><el-option label="难度指数从高到低" value="difficulty_score_desc" /><el-option label="难度指数从低到高" value="difficulty_score_asc" /><el-option label="难度错配优先" value="grade_mismatch_desc" /><el-option label="重复次数优先" value="repeats_desc" /><el-option label="横向跨度优先" value="span_desc" /><el-option label="岩点更少优先" value="holds_asc" /></el-select></label>
        <label v-if="standardBoard.mode === 'routes'" class="filter-field"><span>模型复核等级</span><el-select v-model="standardBoard.filters.predicted_grade" clearable placeholder="不限"><el-option v-for="grade in standardBoard.difficulties" :key="`predicted-${grade}`" :label="grade" :value="grade" /></el-select></label>
        <label v-if="standardBoard.mode === 'routes'" class="filter-field"><span>难度复核</span><el-select v-model="standardBoard.filters.grade_warning" clearable placeholder="不限"><el-option label="轻微错配" value="soft" /><el-option label="严重错配" value="hard" /><el-option label="可信度不足" value="uncertain" /></el-select></label>
        <label v-if="standardBoard.mode === 'routes'" class="filter-field filter-tags-field"><span>路线标签</span><el-select v-model="standardBoard.filters.tag_ids" multiple clearable collapse-tags collapse-tags-tooltip placeholder="不限"><el-option-group v-for="group in standardRouteTagGroups" :key="group.key" :label="group.label"><el-option v-for="tag in group.tags" :key="tag.id" :label="tag.label" :value="tag.id" /></el-option-group></el-select></label>
        <div v-if="standardBoard.mode === 'routes'" class="filter-field filter-match-field"><span>标签匹配</span><el-segmented v-model="standardBoard.filters.tag_match" :options="[{ label: '全部满足', value: 'all' }, { label: '满足任一', value: 'any' }]" /></div>
        <label v-if="standardBoard.mode === 'routes'" class="benchmark-filter"><el-checkbox v-model="standardBoard.filters.benchmark_only">只看标杆线</el-checkbox></label>
        <label v-if="standardBoard.mode === 'repairs'" class="filter-field"><span>修复状态</span><el-select v-model="standardBoard.repairFilters.status" clearable placeholder="全部状态"><el-option label="已生成修复候选" value="repaired" /><el-option label="可尝试但未通过" value="repairable" /><el-option label="不可修复" value="unrepairable" /></el-select></label>
        <label v-if="standardBoard.mode === 'repairs'" class="filter-field filter-search-field"><span>搜索</span><el-input v-model="standardBoard.repairFilters.q" clearable placeholder="名称、来源 ID 或定线者" :prefix-icon="Search" @keyup.enter="applyAndClose" /></label>
        <el-button class="apply-filter-button" type="primary" :loading="standardBoard.mode === 'routes' ? standardBoard.loading : standardBoard.repairLoading" @click="applyAndClose">应用筛选</el-button>
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
          <div v-if="standardBoard.selected" class="standard-preview-toolbar">
            <span>线路视图</span>
            <el-checkbox v-model="showNonRouteHolds">显示其他岩点</el-checkbox>
          </div>
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
              :show-non-route-holds="showNonRouteHolds"
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
          <div class="standard-preview-toolbar">
            <span>修复对比视图</span>
            <el-checkbox v-model="showNonRouteHolds">显示其他岩点</el-checkbox>
          </div>
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
                  :show-non-route-holds="showNonRouteHolds"
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
                  :show-non-route-holds="showNonRouteHolds"
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

</template>

<script setup>
import { computed, ref, watch } from 'vue'
import BoardCanvas from './BoardCanvas.vue'
import BoardComparisonPanel from './BoardComparisonPanel.vue'
import { ArrowDown, Refresh, Search } from '@element-plus/icons-vue'

const standardBoardColumns = Array.from({ length: 11 }, (_, index) => String.fromCharCode(65 + index))
const standardBoardRows = Array.from({ length: 18 }, (_, index) => index + 1)
const nonRouteHoldsStorageKey = 'climb-setter:standard-board:show-non-route-holds'
const showNonRouteHolds = ref(readNonRouteHoldsPreference())
const filtersExpanded = ref(false)

watch(showNonRouteHolds, (value) => {
  try {
    window.localStorage.setItem(nonRouteHoldsStorageKey, String(value))
  } catch {
    // Storage can be unavailable in private or restricted browser contexts.
  }
})

function readNonRouteHoldsPreference() {
  try {
    return window.localStorage.getItem(nonRouteHoldsStorageKey) === 'true'
  } catch {
    return false
  }
}

const props = defineProps({
  standardBoard: { type: Object, required: true },
  standardRouteTagGroups: { type: Array, default: () => [] },
  standardBoardSpec: { type: Object, required: true },
  standardBoardFrameStyle: { type: Object, required: true },
  library: { type: Object, required: true },
  simulationEnabled: { type: Boolean, default: false },
  allVisibleRepairedSelected: { type: Boolean, default: false },
  someVisibleRepairedSelected: { type: Boolean, default: false },
  fetchStandardRoutes: { type: Function, required: true },
  generateStandardRoute: { type: Function, required: true },
  handleStandardModeChange: { type: Function, required: true },
  applyStandardFilters: { type: Function, required: true },
  changeStandardPage: { type: Function, required: true },
  loadStandardRoute: { type: Function, required: true },
  loadStandardIntoStudio: { type: Function, required: true },
  openSelectedRouteSimulation: { type: Function, required: true },
  toggleStandardFavorite: { type: Function, required: true },
  rateStandardRoute: { type: Function, required: true },
  submitStandardAscentLog: { type: Function, required: true },
  fetchRepairRoutes: { type: Function, required: true },
  applyRepairFilters: { type: Function, required: true },
  changeRepairPage: { type: Function, required: true },
  loadRepairRoute: { type: Function, required: true },
  previewRepairRoute: { type: Function, required: true },
  loadRepairIntoStudio: { type: Function, required: true },
  toggleVisibleRepairSelection: { type: Function, required: true },
  publishSelectedRepairs: { type: Function, required: true },
  isRepairSelected: { type: Function, required: true },
  toggleRepairSelection: { type: Function, required: true },
  getStandardBoardCoordStyle: { type: Function, required: true },
  tierLabel: { type: Function, required: true },
  markerLabel: { type: Function, required: true },
  resultLabel: { type: Function, required: true },
  repairStatusLabel: { type: Function, required: true },
  gradeWarningLabel: { type: Function, required: true },
  percentLabel: { type: Function, required: true },
  scoreBreakdownItems: { type: Function, required: true },
  difficultyBreakdownItems: { type: Function, required: true },
  tagLabel: { type: Function, required: true },
  calibrationLabel: { type: Function, required: true },
  confidenceLabel: { type: Function, required: true },
})

const sortLabels = {
  score_desc: '综合评分优先',
  difficulty_score_desc: '难度从高到低',
  difficulty_score_asc: '难度从低到高',
  grade_mismatch_desc: '难度错配优先',
  repeats_desc: '重复次数优先',
  span_desc: '横向跨度优先',
  holds_asc: '岩点更少优先',
}
const filterSummary = computed(() => props.standardBoard.mode === 'routes'
  ? `${props.standardBoard.filters.difficulty || '全部难度'} · ${sortLabels[props.standardBoard.filters.sort] || '综合评分优先'}`
  : `${props.standardBoard.repairFilters.status ? '已选择状态' : '全部状态'} · ${props.standardBoard.repairTotal} 条线路`)

watch(() => props.standardBoard.mode, () => { filtersExpanded.value = false })

function applyAndClose() {
  const action = props.standardBoard.mode === 'routes' ? props.applyStandardFilters : props.applyRepairFilters
  action()
  filtersExpanded.value = false
}
</script>

<style scoped>
.standard-page-summary{max-width:54ch;margin:3px 0 0}.standard-mode-switch{width:fit-content}.mobile-filter-toggle{display:none}.filter-field{min-width:0;display:grid;gap:6px}.filter-field>span{color:var(--ui-ink-muted);font-size:11px;font-weight:500}.benchmark-filter{min-height:44px;display:flex;align-items:end}.apply-filter-button{align-self:end}
@media(min-width:1101px){.filter-search-field,.filter-tags-field{grid-column:span 2}.filter-match-field{min-width:260px}.standard-filters{grid-template-columns:repeat(4,minmax(150px,1fr))}}
@media(max-width:860px){.standard-board-page{gap:12px;padding-top:14px}.standard-page-header{margin-bottom:2px;align-items:center}.standard-page-header>div:first-child{display:none}.standard-header-actions{width:100%;display:grid;grid-template-columns:48px minmax(0,1fr);gap:10px}.standard-header-actions .el-button{width:100%;margin:0}.standard-refresh-button :deep(span span){display:none}.standard-mode-switch{box-sizing:border-box;width:100%;padding:4px}.standard-mode-switch :deep(.el-segmented__item){min-height:42px}.mobile-filter-toggle{width:100%;min-height:62px;padding:10px 13px;border:1px solid var(--ui-line);border-radius:var(--ui-radius-control);background:var(--ui-surface);display:flex;align-items:center;justify-content:space-between;gap:14px;text-align:left;cursor:pointer}.mobile-filter-toggle>span{min-width:0;display:grid;gap:2px}.mobile-filter-toggle strong{font-size:14px}.mobile-filter-toggle small{overflow:hidden;color:var(--ui-ink-muted);font-size:11px;text-overflow:ellipsis;white-space:nowrap}.mobile-filter-toggle svg{width:18px;transition:transform .18s ease}.mobile-filter-toggle svg.rotated{transform:rotate(180deg)}.standard-filters{display:none;padding:14px;grid-template-columns:1fr 1fr;gap:12px}.standard-filters.is-mobile-open{display:grid}.filter-search-field,.filter-sort-field,.filter-tags-field,.filter-match-field,.benchmark-filter,.apply-filter-button{grid-column:1/-1}.filter-match-field :deep(.el-segmented){width:100%}.benchmark-filter{min-height:36px;align-items:center}.apply-filter-button{min-height:46px}.route-list-panel{padding:14px}.route-list-panel>.section-heading{align-items:center}.standard-route-row{padding:13px 12px}.standard-route-row>span:first-of-type small:nth-of-type(n+3){display:none}.standard-route-row>span:last-child{flex:none}.standard-route-row em{font-size:18px}.quality-tier{font-size:10px}.standard-preview-toolbar{position:sticky;top:104px;z-index:4}}
@media(max-width:420px){.standard-filters{grid-template-columns:1fr}.filter-field,.filter-search-field,.filter-sort-field,.filter-tags-field,.filter-match-field,.benchmark-filter,.apply-filter-button{grid-column:1}.standard-route-row{gap:9px}.standard-route-row>span:first-of-type small{font-size:11px}}
@media(prefers-reduced-motion:reduce){.mobile-filter-toggle svg{transition:none}}
</style>
