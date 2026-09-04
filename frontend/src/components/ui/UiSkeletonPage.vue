<template>
  <section class="ui-page ui-skeleton-screen" :data-skeleton-page="page">
    <header v-if="page !== 'studio'" class="ui-page-heading">
      <div>
        <h2>{{ pageMeta.title }}</h2>
        <p>{{ pageMeta.description }}</p>
      </div>
      <div class="ui-page-actions">
        <span class="ui-review-badge">骨架确认模式</span>
        <button type="button" class="ui-button ui-button-primary">{{ pageMeta.action }}</button>
      </div>
    </header>

    <template v-if="page === 'dashboard'">
      <section class="ui-panel ui-specimen-skeleton">
        <div class="ui-section-heading">
          <div><h3>岩点样品架</h3><p>真实内容将在骨架确认后回填</p></div>
          <button type="button" class="ui-button ui-button-quiet">进入岩点库</button>
        </div>
        <div class="ui-specimen-track">
          <article v-for="index in 7" :key="index" class="ui-specimen-slot">
            <div class="ui-placeholder-media"><span>图像区域</span></div>
            <span class="ui-placeholder-line short" />
            <span class="ui-placeholder-line tiny" />
          </article>
        </div>
      </section>

      <div class="ui-dashboard-grid">
        <section class="ui-panel ui-current-board-skeleton">
          <div class="ui-section-heading">
            <div><h3>当前岩板</h3><p>主任务区域</p></div>
            <button type="button" class="ui-button">新建岩板</button>
          </div>
          <div class="ui-board-stage-skeleton">
            <UiTechnicalBoard compact />
            <div class="ui-board-summary-skeleton">
              <span class="ui-placeholder-line wide" />
              <span class="ui-placeholder-line medium" />
              <span class="ui-placeholder-line short" />
              <button type="button" class="ui-button ui-button-primary">继续定线</button>
            </div>
          </div>
        </section>
        <aside class="ui-side-stack">
          <section class="ui-panel ui-list-skeleton">
            <div class="ui-section-heading"><h3>最近编辑</h3><button type="button" class="ui-text-button">查看全部</button></div>
            <div v-for="index in 3" :key="index" class="ui-list-row-skeleton">
              <span class="ui-row-index tabular">{{ String(index).padStart(2, '0') }}</span>
              <span><i class="ui-placeholder-line medium" /><i class="ui-placeholder-line short" /></span>
              <i class="ui-status-dot" />
            </div>
          </section>
          <section class="ui-panel ui-template-skeleton">
            <div class="ui-section-heading"><h3>岩板规格</h3><button type="button" class="ui-button ui-button-primary">确认</button></div>
            <div class="ui-template-strip"><span v-for="index in 4" :key="index" :class="{ active: index === 1 }" /></div>
          </section>
        </aside>
      </div>
      <div class="ui-status-strip">
        <span v-for="label in ['当前线路', 'Beta 动作', '岩板资产', '岩点资产']" :key="label"><strong class="tabular">—</strong>{{ label }}</span>
      </div>
    </template>

    <template v-else-if="page === 'studio'">
      <div class="ui-studio-command">
        <div><strong>当前岩板</strong><span>规格与保存状态</span></div>
        <div class="ui-command-placeholder"><span /><span /></div>
        <button type="button" class="ui-button ui-button-primary">保存</button>
      </div>
      <div class="ui-studio-grid">
        <aside class="ui-studio-rail ui-palette-skeleton">
          <div class="ui-section-heading"><div><h3>岩点</h3><p>选择与筛选</p></div></div>
          <div class="ui-filter-placeholder"><span /><span /></div>
          <div class="ui-palette-grid">
            <span v-for="index in 8" :key="index"><i /><b /></span>
          </div>
        </aside>
        <main class="ui-studio-canvas">
          <div class="ui-canvas-heading"><strong>当前画布</strong><span>选择岩点后点击孔位</span></div>
          <UiTechnicalBoard />
        </main>
        <aside class="ui-studio-rail ui-inspector-skeleton">
          <div class="ui-section-heading"><div><h3>属性</h3><p>岩板 / 岩点 / Beta</p></div></div>
          <div v-for="index in 5" :key="index" class="ui-field-skeleton"><span /><i /></div>
        </aside>
      </div>
      <nav class="ui-studio-mobile-dock" aria-label="定线骨架工具">
        <button v-for="label in ['岩点', '属性', 'Beta']" :key="label" type="button"><span /><b>{{ label }}</b></button>
        <button type="button" class="save"><span /><b>保存</b></button>
      </nav>
    </template>

    <template v-else-if="page === 'library'">
      <div class="ui-toolbar-skeleton">
        <div class="ui-search-placeholder">搜索岩点</div>
        <div class="ui-filter-chip active">全部类型</div>
        <div class="ui-filter-chip">状态</div>
        <div class="ui-toolbar-spacer" />
        <button type="button" class="ui-button">归档</button>
      </div>
      <div class="ui-asset-layout">
        <section class="ui-asset-grid-skeleton">
          <article v-for="index in 8" :key="index" class="ui-asset-card-skeleton">
            <div class="ui-placeholder-media"><span>岩点图像区域</span></div>
            <i class="ui-placeholder-line medium" /><i class="ui-placeholder-line short" />
          </article>
        </section>
        <aside class="ui-panel ui-detail-skeleton">
          <h3>岩点详情</h3>
          <div class="ui-detail-visual">选择样品后显示</div>
          <div v-for="index in 4" :key="index" class="ui-field-skeleton"><span /><i /></div>
        </aside>
      </div>
    </template>

    <template v-else-if="page === 'boards'">
      <div class="ui-toolbar-skeleton">
        <div class="ui-search-placeholder">搜索岩板</div>
        <div class="ui-filter-chip active">启用中</div>
        <div class="ui-filter-chip">归档</div>
        <div class="ui-toolbar-spacer" />
        <button type="button" class="ui-button">对照模式</button>
      </div>
      <div class="ui-master-detail">
        <section class="ui-panel ui-master-list">
          <article v-for="index in 5" :key="index" :class="['ui-master-row', { active: index === 1 }]">
            <UiTechnicalBoard compact label="缩略图" />
            <div><i class="ui-placeholder-line medium" /><i class="ui-placeholder-line short" /><span class="ui-chip-placeholder" /></div>
          </article>
        </section>
        <aside class="ui-panel ui-board-detail">
          <div class="ui-section-heading"><div><h3>岩板详情</h3><p>预览与资产操作</p></div></div>
          <UiTechnicalBoard compact />
          <div class="ui-detail-meta"><span v-for="index in 4" :key="index" /></div>
        </aside>
      </div>
    </template>

    <template v-else-if="page === 'standard-board'">
      <div class="ui-toolbar-skeleton">
        <div class="ui-search-placeholder">搜索线路</div>
        <div class="ui-filter-chip active">全部等级</div>
        <div class="ui-filter-chip">收藏</div>
        <div class="ui-toolbar-spacer" />
        <span class="ui-review-badge">列表 + 常驻预览</span>
      </div>
      <div class="ui-master-detail ui-standard-skeleton">
        <section class="ui-panel ui-master-list">
          <article v-for="index in 7" :key="index" :class="['ui-route-row', { active: index === 2 }]">
            <span class="ui-row-index tabular">{{ String(index).padStart(2, '0') }}</span>
            <div><i class="ui-placeholder-line medium" /><i class="ui-placeholder-line short" /></div>
            <span class="ui-chip-placeholder" />
          </article>
        </section>
        <aside class="ui-panel ui-standard-preview">
          <div class="ui-section-heading"><div><h3>线路预览</h3><p>详情、评级和加载操作</p></div></div>
          <UiTechnicalBoard compact />
          <div class="ui-detail-meta"><span v-for="index in 3" :key="index" /></div>
        </aside>
      </div>
    </template>

    <template v-else>
      <ol class="ui-stepper-skeleton" aria-label="AI 工作流程">
        <li v-for="(label, index) in ['选岩板', '设目标', '运行', '看结果']" :key="label" :class="{ active: index === 0 }"><span>{{ index + 1 }}</span><strong>{{ label }}</strong></li>
      </ol>
      <div class="ui-ai-layout">
        <section class="ui-panel ui-ai-control-skeleton">
          <div class="ui-section-heading"><div><h3>任务设置</h3><p>输入、边界与运行条件</p></div></div>
          <div class="ui-select-board-skeleton"><UiTechnicalBoard compact /><div><i class="ui-placeholder-line wide" /><i class="ui-placeholder-line medium" /><span class="ui-chip-placeholder" /></div></div>
          <div v-for="index in 4" :key="index" class="ui-field-skeleton"><span /><i /></div>
          <button type="button" class="ui-button ui-button-primary">运行检查</button>
        </section>
        <section class="ui-panel ui-ai-result-skeleton">
          <div class="ui-section-heading"><div><h3>结果区域</h3><p>结论、证据和下一步</p></div></div>
          <div class="ui-empty-result"><span /><strong>结果状态</strong><p>运行后在这里呈现依据和建议。</p></div>
          <div class="ui-evidence-rows"><span v-for="index in 4" :key="index" /></div>
        </section>
      </div>
    </template>
  </section>
</template>

<script setup>
import { computed } from 'vue'
import UiTechnicalBoard from './UiTechnicalBoard.vue'

const props = defineProps({ page: { type: String, required: true } })
const meta = {
  dashboard: { title: '总览', description: '快速进入当前任务与最近工作', action: '开始定线' },
  studio: { title: '定线工作台', description: '以岩板画布为中心完成线路编辑', action: '保存' },
  library: { title: '岩点库', description: '浏览、筛选与维护岩点资产', action: '上传岩点' },
  boards: { title: '岩板资产', description: '管理保存的线路与岩板版本', action: '新建岩板' },
  'standard-board': { title: '标准板库', description: '从线路列表进入预览与加载', action: '刷新线路' },
  simulation: { title: '仿真审核', description: '查看动作验证与风险依据', action: '开始审核' },
  'ai-lab': { title: 'AI 实验室', description: '按明确步骤提交并检查岩板', action: '新建任务' },
}
const pageMeta = computed(() => meta[props.page] || meta['ai-lab'])
</script>
