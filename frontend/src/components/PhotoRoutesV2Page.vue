<template>
  <section class="route-v2">
    <header class="route-v2__header">
      <div>
        <h1>照片线路工作台</h1>
        <p>照片留在本机。识别结果先复核，再保存为可追溯的线路版本。</p>
      </div>
      <div class="route-v2__status" :class="`is-${saveState}`" aria-live="polite">
        <span></span>{{ stateLabel }}
      </div>
    </header>

    <nav class="route-v2__steps" aria-label="照片线路流程">
      <button v-for="item in steps" :key="item.id" type="button" :aria-current="stage === item.id ? 'step' : undefined"
        :disabled="item.requiresBoard && !board" @click="stage = item.id">
        <strong>{{ item.label }}</strong><small>{{ item.help }}</small>
      </button>
    </nav>
    <div v-if="board" class="route-v2__board-context" aria-label="当前岩板版本">
      <strong>当前岩板 · {{ board.board_key.slice(0, 6).toUpperCase() }}</strong>
      <span>{{ formatDate(board.created_at) }}</span>
      <span>岩板版本 {{ board.board_version_no || 1 }}</span>
      <span>{{ boardStatus(board.status) }}</span>
      <span>{{ board.calibration?.status === 'confirmed' ? '标定已确认' : '标定待复核' }}</span>
    </div>

    <div v-if="error" class="route-v2__alert" role="alert">
      <span>{{ error }}</span><button type="button" @click="error = ''">关闭</button>
    </div>

    <main v-if="stage === 'upload'" class="route-v2__upload">
      <section class="route-v2__drop" :class="{ 'is-busy': uploading }">
        <input ref="fileInput" type="file" accept="image/jpeg,image/png,image/webp" :disabled="uploading || !editable" @change="upload" />
        <div class="route-v2__drop-copy">
          <h2>{{ uploading ? '正在检查并创建本地任务…' : '上传完整正面岩壁照片' }}</h2>
          <p>需要看清岩壁四周边界、全部岩点和孔阵列。画面模糊、过曝或大面积遮挡会要求重拍。</p>
          <button class="route-v2__primary" type="button" :disabled="uploading || !editable" @click="fileInput?.click()">选择照片</button>
        </div>
      </section>
      <section v-if="activeJob" class="route-v2__job">
        <div><strong>{{ activeJob.stage }}</strong><span>{{ activeJob.progress }}%</span></div>
        <progress :value="activeJob.progress" max="100"></progress>
        <p v-if="activeJob.error">{{ activeJob.error }}</p>
        <button v-if="['queued','running'].includes(activeJob.status)" type="button" @click="cancelJob">取消任务</button>
        <button v-if="['failed','cancelled'].includes(activeJob.status)" type="button" @click="retryJob">重试</button>
      </section>
      <section class="route-v2__recent">
        <div class="route-v2__section-heading"><h2>本机岩板版本</h2><span>{{ boards.length }} 个</span></div>
        <button v-for="item in boards" :key="item.id" type="button" @click="openBoard(item.id)">
          <span><strong>{{ formatDate(item.created_at) }}</strong><small>{{ item.model_version || '等待识别' }}</small></span>
          <span class="route-v2__badge">{{ boardStatus(item.status) }}</span>
        </button>
        <p v-if="!boards.length" class="route-v2__empty">还没有岩板版本。上传第一张完整岩壁照片即可开始。</p>
      </section>
    </main>

    <main v-else-if="stage === 'review' && board" class="route-v2__review">
      <section class="route-v2__photo-panel">
        <div class="route-v2__section-heading">
          <div><h2>对象与孔位复核</h2><p>{{ board.calibration?.method || '尚未标定' }} · {{ board.objects.length }} 个候选</p></div>
          <button type="button" :aria-pressed="calibrationMode" :disabled="!editable" @click="startCalibration">{{ calibrationMode ? `依次点击四角（${calibrationPoints.length}/4）` : '在照片上标定四角' }}</button>
        </div>
        <div class="route-v2__photo-stage" @click="addAtPhoto">
          <img :src="photoV2AssetUrl(board.original_asset)" alt="上传的岩壁原图" />
          <svg class="route-v2__contours" :viewBox="`0 0 ${board.width} ${board.height}`" aria-label="识别对象轮廓">
            <g v-for="object in visibleObjects" :key="object.id" role="button" tabindex="0"
              :aria-label="`${object.color_group}${kindLabel(object.kind)}`" @click.stop="selectedId = object.id"
              @keydown.enter.prevent="selectedId = object.id" @keydown.space.prevent="selectedId = object.id">
              <polygon class="route-v2__contour-hit" :points="contourPoints(object)" />
              <polygon class="route-v2__contour-line" :class="{ 'is-selected': selectedObject?.id === object.id, 'needs-review': object.review_status !== 'confirmed' }"
                :style="{ '--object-color': swatch(object.color_group) }" :points="contourPoints(object)" />
            </g>
            <g class="route-v2__calibration-points" aria-hidden="true"><circle v-for="(point,index) in calibrationPoints" :key="index" :cx="point[0]" :cy="point[1]" r="18" /><text v-for="(point,index) in calibrationPoints" :key="`t${index}`" :x="point[0]+24" :y="point[1]+8">{{ index+1 }}</text></g>
          </svg>
        </div>
      </section>
      <aside class="route-v2__review-panel">
        <div class="route-v2__section-heading"><h2>颜色组</h2><span>一色一线</span></div>
        <div class="route-v2__color-list">
          <button v-for="item in colorGroups" :key="item.color" type="button" :aria-pressed="colorFilter === item.color"
            @click="colorFilter = colorFilter === item.color ? '' : item.color">
            <span class="route-v2__swatch" :style="{ background: swatch(item.color) }"></span>{{ item.color }}<small>{{ item.count }}</small>
          </button>
        </div>
        <button v-if="colorFilter" class="route-v2__primary route-v2__wide" type="button" :disabled="!editable" @click="createRoute(colorFilter)">生成{{ colorFilter }}线路</button>
        <div class="route-v2__object-tools">
          <button type="button" :aria-pressed="addMode" :disabled="!editable" @click="addMode = !addMode">{{ addMode ? '点击照片放置轮廓' : '补加漏识别对象' }}</button>
          <button type="button" :disabled="mergeIds.length < 2 || !editable" @click="mergeSelected">合并所选轮廓</button>
        </div>
        <div class="route-v2__merge-list">
          <label v-for="item in visibleObjects" :key="`merge-${item.id}`"><input v-model="mergeIds" type="checkbox" :value="item.id" />{{ item.color_group }} · {{ item.id.slice(-6) }}</label>
        </div>

        <fieldset v-if="selectedObject" class="route-v2__inspector" :disabled="!editable">
          <legend>{{ selectedObject.color_group }}{{ kindLabel(selectedObject.kind) }}</legend>
          <label>类型<select :value="selectedObject.kind" @change="editObject({ kind: $event.target.value })"><option value="hold">岩点</option><option value="volume">造型</option></select></label>
          <label>颜色组<input :value="selectedObject.color_group" maxlength="40" @change="editObject({ color_group: $event.target.value.trim() })" /></label>
          <label>复核状态<select :value="selectedObject.review_status" @change="editObject({ review_status: $event.target.value })"><option value="needs_review">待复核</option><option value="confirmed">已确认</option></select></label>
          <label>孔位（可多选）
            <input :value="anchorText" placeholder="例如 A1, B2" @change="editAnchors($event.target.value)" />
          </label>
          <div class="route-v2__nearby-holes" aria-label="附近孔位">
            <button v-for="hole in nearbyHoles" :key="hole.id" type="button" :aria-pressed="selectedObject.anchors.some(item => item.hole_id === hole.id)" @click="toggleAnchor(hole)">{{ hole.id }}</button>
          </div>
          <p>置信度 {{ Math.round(selectedObject.confidence * 100) }}% · 对象版本 {{ selectedObject.object_version }}</p>
          <button type="button" @click="splitSelected">沿轮廓中线拆成两个</button>
          <button type="button" class="route-v2__danger" @click="removeObject">删除误识别对象</button>
        </fieldset>
        <p v-else class="route-v2__empty">点击照片上的轮廓，修改类型、颜色或孔位。</p>
      </aside>
    </main>

    <main v-else-if="stage === 'route' && board" class="route-v2__editor">
      <div class="route-v2__editor-top">
        <label>当前线路<select :value="route?.id || ''" @change="openRoute($event.target.value)"><option value="">请选择线路</option><option v-for="item in boardRoutes" :key="item.id" :value="item.id">{{ item.name }} · {{ item.color_group }}</option></select></label>
        <div><button type="button" :aria-pressed="interactionMode === 'browse'" @click="interactionMode = 'browse'">浏览</button><button type="button" :aria-pressed="interactionMode === 'edit'" @click="interactionMode = 'edit'">吸附编辑</button><button type="button" :disabled="!canUndo" @click="undo">撤销</button><button type="button" :disabled="!canRedo" @click="redo">重做</button></div>
      </div>
      <template v-if="route">
        <div class="route-v2__editor-grid">
          <section class="route-v2__canvas-wrap">
            <div v-if="background" class="route-v2__clean-result"><img :src="photoV2AssetUrl(background.composite_asset)" alt="净化墙面结果，目标路线像素来自原图" /><p>净化结果不会覆盖原图；人物、告示牌和贴纸默认保留。</p></div>
            <PhotoRouteBoardCanvas v-else :objects="routeObjects" :selected-id="selectedId" :mode="interactionMode" :editable="editable"
              snapping :snap-preview="snapPreview" :asset-url="photoV2AssetUrl" @select="selectRouteObject" @begin="beginDrag"
              @move="moveDrag" @end="endDrag" @nudge="nudge" />
          </section>
          <aside class="route-v2__route-panel">
            <div class="route-v2__section-heading"><h2>线路信息</h2><span>版本 {{ route.version }}</span></div>
            <fieldset :disabled="!editable || route.status === 'completed'">
              <label>线路名称<input :value="route.name" maxlength="120" @input="routeField('name', $event.target.value.trim())" /></label>
              <label>颜色<input :value="route.color_group" disabled /></label>
              <label>难度<input :value="route.difficulty" maxlength="40" @input="routeField('difficulty', $event.target.value.trim())" /></label>
              <label>定线者<input :value="route.setter" maxlength="80" @input="routeField('setter', $event.target.value.trim())" /></label>
              <label>线路备注<textarea :value="route.notes" rows="3" maxlength="4000" @input="routeField('notes', $event.target.value)"></textarea></label>
            </fieldset>
            <fieldset v-if="selectedMember" class="route-v2__member" :disabled="!editable || route.status === 'completed'">
              <legend>当前岩点备注</legend>
              <div class="route-v2__roles"><label><input type="checkbox" :checked="selectedMember.roles.includes('start')" @change="toggleRole('start')" />起点</label><label><input type="checkbox" :checked="selectedMember.roles.includes('end')" @change="toggleRole('end')" />终点</label></div>
              <div class="route-v2__tags"><button v-for="tag in actionTags" :key="tag" type="button" :aria-pressed="selectedMember.tags.includes(tag)" @click="toggleTag(tag)">{{ tag }}</button></div>
              <label>自由备注<textarea :value="selectedMember.note" rows="3" maxlength="2000" @input="memberNote($event.target.value)"></textarea></label>
            </fieldset>
            <p v-else class="route-v2__empty">点击岩点后才显示该线路内的动作标签与备注。</p>
            <div class="route-v2__finish-actions">
              <button type="button" :disabled="route.status === 'completed' || !editable" @click="completeRoute">确认完成</button>
              <button type="button" :disabled="route.status !== 'completed' || !editable" @click="startCleanup">生成净化墙面</button>
            </div>
            <button v-if="background" class="route-v2__wide" type="button" @click="background = null">返回电子岩板</button>
          </aside>
        </div>
      </template>
      <p v-else class="route-v2__empty route-v2__empty--large">请先在“对象复核”中选择颜色生成线路。</p>
    </main>

    <main v-else-if="stage === 'library'" class="route-v2__library">
      <div class="route-v2__library-tools">
        <input v-model.trim="filters.search" placeholder="搜索名称、定线者或备注" @input="loadRoutes" />
        <select v-model="filters.status" @change="loadRoutes"><option value="">全部状态</option><option value="draft">草稿</option><option value="completed">已完成</option></select>
        <select v-model="filters.color" @change="loadRoutes"><option value="">全部颜色</option><option v-for="item in allColors" :key="item" :value="item">{{ item }}</option></select>
      </div>
      <div class="route-v2__library-grid">
        <section class="route-v2__route-list">
          <article v-for="item in routes" :key="item.id">
            <button type="button" class="route-v2__route-main" @click="openRoute(item.id)">
              <span class="route-v2__swatch" :style="{ background: swatch(item.color_group) }"></span>
              <span><strong>{{ item.name }}</strong><small>{{ item.difficulty || '未定级' }} · {{ item.setter || '未填写定线者' }} · V{{ item.version }}</small></span>
              <span class="route-v2__badge">{{ item.status === 'completed' ? '已完成' : '草稿' }}</span>
            </button>
            <div><label><input type="checkbox" :checked="overlayIds.includes(item.id)" @change="toggleOverlay(item.id)" />叠加</label><button type="button" @click="showHistory(item)">历史</button><button type="button" @click="archiveRoute(item)">归档</button></div>
            <div v-if="openHistoryId === item.id" class="route-v2__history">
              <p v-if="!historyByRoute[item.id]?.length">还没有已确认版本。</p>
              <button v-for="revision in historyByRoute[item.id]" :key="revision.id" type="button" @click="restoreHistory(item, revision)">
                <span>V{{ revision.version }} · {{ revision.snapshot.difficulty || '未定级' }}</span><small>{{ formatDate(revision.created_at) }} · 恢复为新草稿</small>
              </button>
            </div>
          </article>
          <p v-if="!routes.length" class="route-v2__empty">没有符合筛选条件的线路。</p>
        </section>
        <section class="route-v2__overlay">
          <div class="route-v2__section-heading"><h2>同板线路叠加</h2><span>{{ overlayRoutes.length }} 条</span></div>
          <div v-if="overlayRoutes.length" class="route-v2__overlay-legend"><span v-for="item in overlayRoutes" :key="item.id"><i :style="{ background:routeDisplayColor(item) }"></i>{{ item.name }}</span></div>
          <PhotoRouteBoardCanvas v-if="overlayObjects.length" :objects="overlayObjects" mode="browse" :editable="false" :asset-url="photoV2AssetUrl" />
          <p v-else class="route-v2__empty">勾选同一岩板版本中的线路进行叠加查看。</p>
        </section>
      </div>
    </main>
  </section>
</template>

<script setup>
import { computed, inject, onBeforeUnmount, onMounted, ref } from 'vue'
import { ElMessageBox } from 'element-plus'
import PhotoRouteBoardCanvas from './PhotoRouteBoardCanvas.vue'
import { photoRouteV2Service as service, photoV2AssetUrl } from '../services/photoRouteService.js'
import { clone, createHistory, nearestPhotoHole, photoHoles, snapObjectToHole, translateObjects } from '../utils/photoBoard.js'

const emit = defineEmits(['status'])
const access = inject('pilotAccess')
const editable = computed(() => !access.session.authEnabled || access.lease.ownedByMe)
const steps = [
  { id:'upload', label:'上传', help:'检查照片与本地识别' },
  { id:'review', label:'对象复核', help:'颜色、轮廓与孔位', requiresBoard:true },
  { id:'route', label:'线路编辑', help:'吸附、起终点与备注', requiresBoard:true },
  { id:'library', label:'线路库', help:'版本、筛选与叠加' },
]
const actionTags = ['动态','静态','匹配','交叉','换手','休息','核心动作','安全提醒']
const stage = ref('upload'), boards = ref([]), board = ref(null), routes = ref([]), route = ref(null)
const activeJob = ref(null), uploading = ref(false), error = ref(''), saveState = ref('saved')
const selectedId = ref(''), colorFilter = ref(''), interactionMode = ref('browse'), snapPreview = ref(null)
const addMode = ref(false), mergeIds = ref([]), background = ref(null)
const calibrationMode = ref(false), calibrationPoints = ref([]), openHistoryId = ref(''), historyByRoute = ref({})
const fileInput = ref(null), overlayIds = ref([]), filters = ref({ search:'', color:'', status:'' })
const history = createHistory(80), canUndo = ref(false), canRedo = ref(false)
let pollTimer, saveTimer, dragBaseline, savedSnapshot, disposed = false

const stateLabel = computed(() => ({ saved:'已保存', dirty:'等待保存', saving:'保存中…', error:'保存失败', conflict:'版本冲突' }[saveState.value] || '本机'))
const selectedObject = computed(() => board.value?.objects.find(item => item.id === selectedId.value))
const anchorText = computed(() => selectedObject.value?.anchors.map(item => item.hole_id).join(', ') || '')
const colorGroups = computed(() => Object.entries((board.value?.objects || []).reduce((all, item) => { all[item.color_group] = (all[item.color_group] || 0) + 1; return all }, {})).map(([color,count]) => ({ color,count })))
const visibleObjects = computed(() => (board.value?.objects || []).filter(item => !colorFilter.value || item.color_group === colorFilter.value))
const boardRoutes = computed(() => routes.value.filter(item => item.board_version_id === board.value?.id))
const selectedMember = computed(() => route.value?.members.find(item => item.object_id === selectedId.value))
const nearbyHoles = computed(() => selectedObject.value ? photoHoles().map(hole => ({ ...hole, distance:Math.hypot(hole.x-selectedObject.value.center_x_mm, hole.y-selectedObject.value.center_y_mm) })).sort((a,b) => a.distance-b.distance).slice(0, 12) : [])
const routeObjects = computed(() => {
  const members = new Map((route.value?.members || []).map(item => [item.object_id, item]))
  return (board.value?.objects || []).filter(item => members.has(item.id)).map((item,index) => ({ ...item, roles:members.get(item.id).roles, z_index:index }))
})
const allColors = computed(() => [...new Set(routes.value.map(item => item.color_group))].sort())
const overlayRoutes = computed(() => routes.value.filter(item => overlayIds.value.includes(item.id)))
const overlayObjects = computed(() => {
  if (!overlayRoutes.value.length) return []
  const boardId = overlayRoutes.value[0].board_version_id
  const objects = new Map((board.value?.id === boardId ? board.value.objects : []).map(item => [item.id,item]))
  return overlayRoutes.value.filter(item => item.board_version_id === boardId).flatMap((item,routeIndex) => item.members.map((member,index) => ({
    ...objects.get(member.object_id), id:`${item.id}:${member.object_id}`, roles:member.roles,
    z_index:routeIndex*1000+index, route_color:routeDisplayColor(item), route_name:item.name,
  })).filter(item => item.cutout))
})

function report() { emit('status', { count:board.value?.objects.length || 0, dirty:saveState.value === 'dirty', state:stateLabel.value }) }
function formatDate(value) { return new Intl.DateTimeFormat('zh-CN', { dateStyle:'medium', timeStyle:'short' }).format(new Date(value)) }
function boardStatus(value) { return ({ processing:'识别中', review:'待复核', ready:'可定线', failed:'失败' })[value] || value }
function kindLabel(value) { return value === 'volume' ? '造型' : '岩点' }
function swatch(color) { return ({ 黄色:'#d6a800',蓝色:'#2474a6',红色:'#b84336',绿色:'#3d8061',紫色:'#7b5aa6',橙色:'#c56b2b',粉色:'#bb6683',黑色:'#30343a',白色:'#eeeae1',灰色:'#7c858c' })[color] || '#7b7468' }
function routeDisplayColor(item) { const palette = ['#176b78','#b14e35','#6b5aa6','#93701c','#407752','#b04470']; return palette[routes.value.findIndex(route => route.id === item.id) % palette.length] }
function contourPoints(object) { return object.contour.map(point => point.join(',')).join(' ') }
function syncHistory() { canUndo.value = history.canUndo; canRedo.value = history.canRedo }
function snapshot() { return clone({ board:board.value, route:route.value }) }
function mutate(action) {
  if (!editable.value) return
  const before = snapshot(); action()
  if (JSON.stringify(before) !== JSON.stringify(snapshot())) { history.push(before); syncHistory(); queueSave() }
}
function queueSave() { saveState.value = 'dirty'; report(); clearTimeout(saveTimer); saveTimer = setTimeout(flush, 2000) }
async function flush() {
  clearTimeout(saveTimer)
  if (!editable.value || saveState.value !== 'dirty') return
  saveState.value = 'saving'; report()
  try {
    if (board.value && savedSnapshot?.board) {
      const prior = new Map(savedSnapshot.board.objects.map(item => [item.id, item]))
      for (const item of board.value.objects) {
        const old = prior.get(item.id)
        if (!old || JSON.stringify(item) === JSON.stringify(old)) continue
        board.value = await service.patchObject(board.value.id, item.id, {
          expected_version:old.object_version, kind:item.kind, color_group:item.color_group,
          center_x_mm:item.center_x_mm, center_y_mm:item.center_y_mm, rotation_deg:item.rotation_deg,
          scale_mm_per_px:item.scale_mm_per_px, review_status:item.review_status,
          anchors:item.anchors.map(({ hole_id, confidence, confirmed }) => ({ hole_id, confidence, confirmed })),
        })
      }
    }
    if (route.value && (!savedSnapshot?.route || JSON.stringify(route.value) !== JSON.stringify(savedSnapshot.route))) route.value = await service.saveRoute(route.value)
    savedSnapshot = snapshot(); saveState.value = 'saved'
  } catch (cause) {
    saveState.value = cause?.response?.status === 409 ? 'conflict' : 'error'
    error.value = detail(cause, '保存失败；修改仍保留在当前页面。')
  }
  report()
}
async function undo() { const next = history.undo(snapshot()); if (next === snapshot()) return; board.value = next.board; route.value = next.route; syncHistory(); queueSave() }
async function redo() { const next = history.redo(snapshot()); if (next === snapshot()) return; board.value = next.board; route.value = next.route; syncHistory(); queueSave() }
function detail(cause, fallback) { const value = cause?.response?.data?.detail; return typeof value === 'string' ? value : value?.message ? `${value.message}：${(value.issues || []).join('；')}` : fallback }

async function loadBoards() { boards.value = await service.boards() }
async function loadRoutes() {
  routes.value = await service.routes({ search:filters.value.search || undefined, color:filters.value.color || undefined, status:filters.value.status || undefined })
}
async function upload(event) {
  const file = event.target.files?.[0]; event.target.value = ''; if (!file) return
  uploading.value = true; error.value = ''
  try { const result = await service.upload(file); board.value = result.board; activeJob.value = result.job; stage.value = 'upload'; watchJob() }
  catch (cause) { error.value = detail(cause, '上传失败，请确认照片格式和本机服务。') }
  finally { uploading.value = false }
}
function watchJob() {
  clearInterval(pollTimer)
  pollTimer = setInterval(async () => {
    if (!activeJob.value || disposed) return
    try {
      activeJob.value = await service.job(activeJob.value.id)
      if (['succeeded','failed','cancelled'].includes(activeJob.value.status)) {
        clearInterval(pollTimer); await loadBoards()
        if (activeJob.value.status === 'succeeded' && activeJob.value.kind === 'cleanup') {
          background.value = await service.background(activeJob.value.route_id); stage.value = 'route'
        } else if (activeJob.value.status === 'succeeded') { await openBoard(activeJob.value.board_version_id); stage.value = 'review' }
      }
    } catch { clearInterval(pollTimer) }
  }, 1200)
}
async function cancelJob() { activeJob.value = await service.cancelJob(activeJob.value.id) }
async function retryJob() { activeJob.value = await service.retryJob(activeJob.value.id); watchJob() }
async function openBoard(id) {
  await flush(); board.value = await service.board(id); route.value = null; selectedId.value = ''; colorFilter.value = ''
  savedSnapshot = snapshot(); history.clear(); syncHistory(); await loadRoutes(); stage.value = board.value.status === 'processing' ? 'upload' : 'review'
}
function startCalibration() { calibrationMode.value = !calibrationMode.value; calibrationPoints.value = []; if (calibrationMode.value) error.value = '请依次点击：左下、右下、右上、左上四个角点。' }
function editObject(patch) { if (!selectedObject.value) return; mutate(() => Object.assign(selectedObject.value, patch)) }
function editAnchors(value) {
  const ids = [...new Set(value.toUpperCase().split(/[,，\s]+/).filter(Boolean))]
  editObject({ anchors:ids.map(id => ({ hole_id:id, confidence:1, confirmed:true })) })
}
function toggleAnchor(hole) {
  const anchors = selectedObject.value.anchors || [], exists = anchors.some(item => item.hole_id === hole.id)
  editObject({ anchors:exists ? anchors.filter(item => item.hole_id !== hole.id) : [...anchors, { hole_id:hole.id, x_mm:hole.x, y_mm:hole.y, confidence:1, confirmed:true }] })
}
async function removeObject() {
  if (!selectedObject.value) return
  try { await ElMessageBox.confirm('该对象会从当前岩板版本的可用对象中移除。', '删除误识别对象', { type:'warning', confirmButtonText:'删除', cancelButtonText:'取消' }) } catch { return }
  try { board.value = await service.deleteObject(board.value.id, selectedObject.value.id, selectedObject.value.object_version); selectedId.value = ''; savedSnapshot = snapshot() }
  catch (cause) { error.value = detail(cause, '删除失败，请刷新后重试。') }
}
async function addAtPhoto(event) {
  if (event.target.closest('[role=button]')) return
  const rect = event.currentTarget.getBoundingClientRect()
  const x = (event.clientX - rect.left) / rect.width * board.value.width
  const y = (event.clientY - rect.top) / rect.height * board.value.height
  if (calibrationMode.value) {
    calibrationPoints.value = [...calibrationPoints.value, [x,y]]
    if (calibrationPoints.value.length === 4) {
      try { board.value = await service.calibrate(board.value.id, { photo_points:calibrationPoints.value, board_hole_ids:['A1','AD1','AD20','A20'] }); savedSnapshot = snapshot(); error.value = '' }
      catch (cause) { error.value = detail(cause, '标定失败，请重新选择四个角点。') }
      finally { calibrationMode.value = false }
    }
    return
  }
  if (!addMode.value) return
  const size = Math.max(18, Math.min(board.value.width, board.value.height) * .035)
  const contour = [[x-size,y-size],[x+size,y-size],[x+size,y+size],[x-size,y+size]].map(([px,py]) => [Math.max(0,Math.min(board.value.width,px)),Math.max(0,Math.min(board.value.height,py))])
  try { board.value = await service.addObject(board.value.id, { expected_version:board.value.version, kind:'hold', color_group:colorFilter.value || '未分组', contour }); addMode.value = false; savedSnapshot = snapshot() }
  catch (cause) { error.value = detail(cause, '无法添加对象，请先完成标定。') }
}
async function splitSelected() {
  const item = selectedObject.value; if (!item) return
  const [x,y,w,h] = item.source_bbox_px
  const contours = w >= h
    ? [[[x,y],[x+w/2,y],[x+w/2,y+h],[x,y+h]],[[x+w/2,y],[x+w,y],[x+w,y+h],[x+w/2,y+h]]]
    : [[[x,y],[x+w,y],[x+w,y+h/2],[x,y+h/2]],[[x,y+h/2],[x+w,y+h/2],[x+w,y+h],[x,y+h]]]
  try { board.value = await service.splitObject(board.value.id, item.id, { expected_version:item.object_version, contours }); selectedId.value = ''; savedSnapshot = snapshot() }
  catch (cause) { error.value = detail(cause, '拆分失败，请刷新后重试。') }
}
async function mergeSelected() {
  try { board.value = await service.mergeObjects(board.value.id, { expected_version:board.value.version, object_ids:mergeIds.value }); mergeIds.value = []; selectedId.value = ''; savedSnapshot = snapshot() }
  catch (cause) { error.value = detail(cause, '合并失败；请确认对象属于同一颜色组。') }
}
async function createRoute(color) {
  try { route.value = await service.fromColor({ board_version_id:board.value.id, color_group:color, name:`${color}线路` }); await loadRoutes(); savedSnapshot = snapshot(); stage.value = 'route' }
  catch (cause) { error.value = detail(cause, '无法按颜色创建线路。') }
}
async function openRoute(id) {
  if (!id) { route.value = null; return }
  await flush(); route.value = await service.route(id)
  if (board.value?.id !== route.value.board_version_id) board.value = await service.board(route.value.board_version_id)
  selectedId.value = ''; background.value = null; savedSnapshot = snapshot(); history.clear(); syncHistory(); stage.value = 'route'
}
function selectRouteObject(id) { selectedId.value = id }
function beginDrag(id) { dragBaseline = snapshot(); selectedId.value = id }
function moveDrag({ id, dx, dy }) {
  if (!dragBaseline) return
  const base = dragBaseline.board.objects.find(item => item.id === id); if (!base) return
  const moved = translateObjects([base], dx, dy)[0]
  const index = board.value.objects.findIndex(item => item.id === id); board.value.objects[index] = { ...board.value.objects[index], center_x_mm:moved.center_x_mm, center_y_mm:moved.center_y_mm }
  const hole = nearestPhotoHole(moved.center_x_mm, moved.center_y_mm)
  snapPreview.value = hole ? { ...hole, fromX:moved.center_x_mm, fromY:moved.center_y_mm } : null
}
function endDrag() {
  if (!dragBaseline) return
  const object = selectedObject.value; const snapped = object && snapObjectToHole(object)
  if (snapped?.preview) Object.assign(object, snapped.object)
  snapPreview.value = null
  if (JSON.stringify(dragBaseline) !== JSON.stringify(snapshot())) { history.push(dragBaseline); syncHistory(); queueSave() }
  dragBaseline = null
}
function nudge({ id, dx, dy }) { mutate(() => { const item = board.value.objects.find(object => object.id === id); Object.assign(item, translateObjects([item], dx, dy)[0]) }) }
function routeField(field, value) { mutate(() => { route.value[field] = value }) }
function toggleRole(role) { mutate(() => { selectedMember.value.roles = selectedMember.value.roles.includes(role) ? selectedMember.value.roles.filter(item => item !== role) : [...selectedMember.value.roles, role] }) }
function toggleTag(tag) { mutate(() => { selectedMember.value.tags = selectedMember.value.tags.includes(tag) ? selectedMember.value.tags.filter(item => item !== tag) : [...selectedMember.value.tags, tag] }) }
function memberNote(value) { mutate(() => { selectedMember.value.note = value }) }
async function completeRoute() {
  await flush()
  try { route.value = await service.completeRoute(route.value.id); savedSnapshot = snapshot(); await loadRoutes() }
  catch (cause) { error.value = detail(cause, '线路尚未满足完成条件。') }
}
async function startCleanup() {
  try { activeJob.value = await service.cleanup(route.value.id, { removal_polygons:[], preserve_polygons:[], method:'opencv' }); stage.value = 'upload'; watchJob() }
  catch (cause) { error.value = detail(cause, '无法创建净化任务。') }
}
function toggleOverlay(id) {
  const item = routes.value.find(candidate => candidate.id === id)
  const first = overlayRoutes.value[0]
  if (first && item.board_version_id !== first.board_version_id) { error.value = '不同岩板版本不能叠加。'; return }
  overlayIds.value = overlayIds.value.includes(id) ? overlayIds.value.filter(item => item !== id) : [...overlayIds.value,id]
  if (item && board.value?.id !== item.board_version_id) service.board(item.board_version_id).then(value => { board.value = value })
}
async function showHistory(item) {
  if (openHistoryId.value === item.id) { openHistoryId.value = ''; return }
  historyByRoute.value = { ...historyByRoute.value, [item.id]:await service.revisions(item.id) }; openHistoryId.value = item.id
}
async function restoreHistory(item, revision) {
  await service.restoreRevision(item.id, revision.version); openHistoryId.value = ''; await loadRoutes()
}
async function archiveRoute(item) { await service.archive(item.id); overlayIds.value = overlayIds.value.filter(id => id !== item.id); await loadRoutes() }
async function beforeLeave() { endDrag(); await flush(); return saveState.value !== 'dirty' && saveState.value !== 'saving' }

onMounted(async () => { try { await Promise.all([loadBoards(), loadRoutes()]); if (boards.value.length) await openBoard(boards.value[0].id) } catch { error.value = '无法读取本机照片线路数据。' } report() })
onBeforeUnmount(() => { disposed = true; clearInterval(pollTimer); clearTimeout(saveTimer) })
defineExpose({ beforeLeave })
</script>

<style scoped>
.route-v2 { --ink:#24313d; --muted:#66717a; --line:#d7d9d5; --paper:#fbfaf6; --wood:#e5d4b7; --accent:#195f70; --accent-soft:#dcecef; --danger:#9a3d2d; min-width:0; min-height:calc(100vh - 64px); color:var(--ink); background:var(--paper); }
.route-v2 :is(button,input,select,textarea):focus-visible { outline:2px solid #0d7184; outline-offset:2px; }
.route-v2 ::selection { background:#b9dfe5; color:#17323a; }
.route-v2 input,.route-v2 select,.route-v2 textarea { border:1px solid #b9c0c1; border-radius:6px; background:#fff; color:var(--ink); padding:9px 10px; font:inherit; }
.route-v2 button { border:1px solid #b8c0c1; border-radius:6px; background:#fff; color:var(--ink); min-height:38px; padding:8px 12px; font:inherit; cursor:pointer; }
.route-v2 button:hover { background:#eef4f4; }.route-v2 button:disabled{opacity:.48;cursor:default}.route-v2 button[aria-pressed=true]{background:var(--accent-soft);border-color:#6d9da6}
.route-v2__header { display:flex; justify-content:space-between; gap:24px; align-items:center; padding:20px 24px 16px; border-bottom:1px solid var(--line); background:#fff; }
.route-v2__header h1 { margin:0 0 5px; font-size:24px; letter-spacing:-.02em; }.route-v2__header p{margin:0;color:var(--muted);font-size:13px}
.route-v2__status{display:flex;align-items:center;gap:8px;font-size:12px;color:#42645a}.route-v2__status span{width:8px;height:8px;border-radius:50%;background:#4c836c}.route-v2__status.is-dirty span,.route-v2__status.is-saving span{background:#b67929}.route-v2__status.is-error span,.route-v2__status.is-conflict span{background:var(--danger)}
.route-v2__steps{display:grid;grid-template-columns:repeat(4,1fr);border-bottom:1px solid var(--line);background:#fff}.route-v2__steps button{display:grid;gap:3px;text-align:left;border:0;border-right:1px solid var(--line);border-radius:0;padding:13px 20px;background:#fff}.route-v2__steps button[aria-current=step]{background:#e9f1f1;box-shadow:inset 0 -3px #195f70}.route-v2__steps strong{font-size:13px}.route-v2__steps small{color:var(--muted);font-size:11px}
.route-v2__board-context{display:flex;gap:14px;align-items:center;flex-wrap:wrap;padding:8px 20px;background:#f0f3f1;border-bottom:1px solid var(--line);font-size:12px}.route-v2__board-context span{color:#5c686f}.route-v2__board-context span+span{border-left:1px solid #c6cdca;padding-left:14px}
.route-v2__alert{display:flex;justify-content:space-between;align-items:center;gap:16px;margin:14px 20px;padding:11px 14px;background:#f8e8df;color:#7b3026;border:1px solid #e2b4a5;border-radius:8px;font-size:13px}
.route-v2__upload{max-width:1040px;margin:auto;padding:30px 24px;display:grid;gap:24px}.route-v2__drop{position:relative;min-height:260px;display:grid;place-items:center;text-align:center;background:#e8ddca url('../assets/photo-wall-birch.png') center/cover;border:1px solid #c9b99d}.route-v2__drop:after{content:'';position:absolute;inset:18px;border:1px dashed #7d735f;pointer-events:none}.route-v2__drop input{position:absolute;opacity:0;pointer-events:none}.route-v2__drop-copy{position:relative;z-index:1;max-width:580px;padding:30px;background:#fffdf7e8;border:1px solid #d2c8b5;border-radius:12px;box-shadow:0 14px 30px #55452c22}.route-v2__drop h2{font-size:23px;margin:0 0 10px}.route-v2__drop p{line-height:1.7;color:#5e594f;margin:0 0 18px}.route-v2__primary{background:var(--accent)!important;border-color:var(--accent)!important;color:white!important}.route-v2__wide{width:100%;margin:12px 0}
.route-v2__job,.route-v2__recent{background:#fff;border:1px solid var(--line);padding:18px}.route-v2__job>div{display:flex;justify-content:space-between}.route-v2__job progress{width:100%;height:10px;margin:12px 0;accent-color:var(--accent)}.route-v2__job p{color:var(--danger)}
.route-v2__section-heading{display:flex;align-items:center;justify-content:space-between;gap:14px;margin-bottom:14px}.route-v2__section-heading h2{font-size:16px;margin:0}.route-v2__section-heading p{font-size:12px;color:var(--muted);margin:4px 0 0}.route-v2__section-heading>span{font-size:12px;color:var(--muted)}.route-v2__recent>button{width:100%;display:flex;align-items:center;justify-content:space-between;text-align:left;border-width:1px 0 0;border-radius:0}.route-v2__recent>button span:first-child{display:grid;gap:3px}.route-v2__recent small{color:var(--muted)}.route-v2__badge{font-size:11px;background:#edf0ed;padding:4px 7px;border-radius:5px;white-space:nowrap}
.route-v2__review{display:grid;grid-template-columns:minmax(0,1fr) 300px}.route-v2__photo-panel{padding:20px;min-width:0}.route-v2__photo-stage{position:relative;line-height:0;background:#ddd}.route-v2__photo-stage>img{width:100%;height:auto;display:block}.route-v2__contours{position:absolute;inset:0;width:100%;height:100%}.route-v2__contours g{cursor:pointer;outline:none}.route-v2__contour-hit{fill:transparent;stroke:transparent;stroke-width:44;vector-effect:non-scaling-stroke;pointer-events:stroke}.route-v2__contour-line{fill:color-mix(in srgb,var(--object-color) 12%,transparent);stroke:var(--object-color);stroke-width:2;vector-effect:non-scaling-stroke;pointer-events:none}.route-v2__contour-line.needs-review{stroke-dasharray:8 6}.route-v2__contour-line.is-selected{stroke:#fff;stroke-width:7;filter:drop-shadow(0 0 4px var(--object-color))}.route-v2__calibration-points{fill:#fff;stroke:#0d7184;stroke-width:7}.route-v2__calibration-points text{fill:#17323a;stroke:none;font-size:42px;font-weight:700}
.route-v2__review-panel,.route-v2__route-panel{background:#fff;border-left:1px solid var(--line);padding:18px;min-width:0}.route-v2__color-list{display:grid;grid-template-columns:1fr 1fr;gap:7px}.route-v2__color-list button{display:flex;align-items:center;gap:7px;padding:7px}.route-v2__color-list small{margin-left:auto;color:var(--muted)}.route-v2__swatch{display:inline-block;width:13px;height:13px;border-radius:50%;border:1px solid #0002;flex:none}.route-v2__inspector,.route-v2__route-panel fieldset{border:0;padding:16px 0 0;margin:14px 0 0;border-top:1px solid var(--line);display:grid;gap:11px}.route-v2__inspector legend,.route-v2__member legend{font-weight:700;padding:0 0 10px}.route-v2 label{display:grid;gap:5px;font-size:12px;color:#53616a}.route-v2__inspector p{font-size:11px;color:var(--muted)}.route-v2__danger{color:var(--danger)!important;border-color:#d8a79d!important}.route-v2__empty{color:var(--muted);font-size:13px;line-height:1.6}.route-v2__empty--large{text-align:center;padding:100px 24px}.route-v2__object-tools{display:grid;grid-template-columns:1fr 1fr;gap:7px;margin-top:8px}.route-v2__merge-list{max-height:120px;overflow:auto;margin-top:8px;padding:8px;border:1px solid var(--line)}.route-v2__merge-list label{display:flex;align-items:center;gap:7px;padding:4px}.route-v2__nearby-holes{display:grid;grid-template-columns:repeat(4,1fr);gap:5px}.route-v2__nearby-holes button{min-height:36px;padding:5px}.route-v2__clean-result{padding:16px;text-align:center}.route-v2__clean-result img{display:block;width:100%;max-height:680px;object-fit:contain}.route-v2__clean-result p{font-size:12px;color:var(--muted)}
.route-v2__editor-top{display:flex;justify-content:space-between;align-items:end;gap:16px;padding:12px 18px;border-bottom:1px solid var(--line);background:#fff}.route-v2__editor-top label{min-width:260px}.route-v2__editor-top>div{display:flex;gap:6px;flex-wrap:wrap}.route-v2__editor-grid{display:grid;grid-template-columns:minmax(0,1fr) 310px}.route-v2__canvas-wrap{min-width:0}.route-v2__roles{display:flex;gap:18px}.route-v2__roles label{display:flex;align-items:center;gap:6px}.route-v2__tags{display:flex;flex-wrap:wrap;gap:6px}.route-v2__tags button{min-height:32px;padding:5px 9px;font-size:12px}.route-v2__finish-actions{display:flex;gap:8px;margin-top:18px}.route-v2__finish-actions button{flex:1}
.route-v2__library{padding:20px}.route-v2__library-tools{display:grid;grid-template-columns:minmax(240px,1fr) 160px 160px;gap:10px;margin-bottom:16px}.route-v2__library-grid{display:grid;grid-template-columns:minmax(300px,480px) minmax(0,1fr);gap:18px}.route-v2__route-list,.route-v2__overlay{background:#fff;border:1px solid var(--line)}.route-v2__route-list article{border-bottom:1px solid var(--line);padding:8px}.route-v2__route-main{width:100%;border:0;display:grid;grid-template-columns:auto minmax(0,1fr) auto;align-items:center;gap:10px;text-align:left}.route-v2__route-main>span:nth-child(2){display:grid;gap:4px}.route-v2__route-main small{color:var(--muted)}.route-v2__route-list article>div{display:flex;justify-content:flex-end;align-items:center;gap:6px}.route-v2__route-list article>div label{display:flex;align-items:center;gap:5px;margin-right:auto}.route-v2__history{display:grid!important;gap:5px!important;padding:8px;background:#f4f6f4}.route-v2__history>button{display:flex;justify-content:space-between;align-items:center;text-align:left;width:100%}.route-v2__history small{color:var(--muted)}.route-v2__overlay{min-width:0;padding:14px}.route-v2__overlay-legend{display:flex;flex-wrap:wrap;gap:8px 14px;margin-bottom:8px;font-size:12px}.route-v2__overlay-legend span{display:flex;align-items:center;gap:5px}.route-v2__overlay-legend i{width:16px;height:4px}.route-v2 textarea{resize:vertical;min-height:70px}
@media(max-width:900px){.route-v2__review,.route-v2__editor-grid,.route-v2__library-grid{grid-template-columns:1fr}.route-v2__review-panel,.route-v2__route-panel{border-left:0;border-top:1px solid var(--line)}.route-v2__library-tools{grid-template-columns:1fr 1fr}.route-v2__library-tools input{grid-column:1/-1}}
@media(max-width:620px){.route-v2__header{padding:16px;align-items:flex-start}.route-v2__header p{max-width:34ch}.route-v2__steps button{padding:10px 7px}.route-v2__steps small{display:none}.route-v2__upload{padding:16px 12px}.route-v2__drop{min-height:230px}.route-v2__drop-copy{margin:24px;padding:20px}.route-v2__review{display:block}.route-v2__photo-panel{padding:12px}.route-v2__editor-top{align-items:stretch;flex-direction:column}.route-v2__editor-top label{min-width:0}.route-v2__library{padding:12px}.route-v2__library-tools{grid-template-columns:1fr}.route-v2__library-tools input{grid-column:auto}.route-v2__status{white-space:nowrap}.route-v2__color-list{grid-template-columns:1fr 1fr}}
@media(prefers-reduced-motion:no-preference){.route-v2 button{transition:background-color .15s ease-out,border-color .15s ease-out}}
</style>
