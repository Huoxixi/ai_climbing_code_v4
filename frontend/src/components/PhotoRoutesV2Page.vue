<template>
  <section class="route-v2">
    <header class="route-v2__header">
      <div>
        <h1>从照片开始定线</h1>
        <p>照片留在本机；先复核识别结果，再保存为可追溯的线路版本。</p>
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
.route-v2 {
  --photo-ink: var(--ui-ink);
  --photo-muted: var(--ui-ink-muted);
  --photo-line: var(--ui-line);
  --photo-paper: var(--ui-ground);
  --photo-surface: var(--ui-surface);
  --photo-subtle: var(--ui-surface-subtle);
  --photo-accent: var(--ui-brand);
  --photo-accent-hover: var(--ui-brand-hover);
  --photo-accent-soft: var(--ui-brand-soft);
  --photo-danger: var(--ui-danger);
  min-width: 0;
  min-height: calc(100vh - var(--ui-shell-top));
  color: var(--photo-ink);
  background: var(--photo-paper);
}

.route-v2 ::selection {
  color: var(--ui-brand-ink);
  background: var(--photo-accent-soft);
}

.route-v2 :is(button, input, select, textarea):focus-visible {
  outline: 3px solid var(--ui-focus);
  outline-offset: 2px;
}

.route-v2 :is(input, select, textarea) {
  width: 100%;
  min-height: 40px;
  border: 1px solid var(--ui-line-strong);
  border-radius: var(--ui-radius-small);
  background: var(--photo-surface);
  color: var(--photo-ink);
  padding: 9px 11px;
  font: inherit;
  caret-color: var(--photo-ink);
}

.route-v2 :is(input, textarea)::placeholder {
  color: var(--ui-ink-faint);
}

.route-v2 button {
  min-height: 40px;
  border: 1px solid var(--ui-line-strong);
  border-radius: var(--ui-radius-small);
  background: var(--photo-surface);
  color: var(--photo-ink);
  padding: 8px 12px;
  font: inherit;
  font-weight: 500;
  cursor: pointer;
}

.route-v2 button:hover:not(:disabled) {
  border-color: var(--photo-ink);
  background: var(--photo-subtle);
}

.route-v2 button:disabled {
  cursor: not-allowed;
  opacity: .46;
}

.route-v2 button[aria-pressed="true"] {
  border-color: var(--photo-accent);
  background: var(--photo-accent-soft);
  color: var(--ui-brand-ink);
}

.route-v2__header {
  min-height: 96px;
  padding: 22px clamp(20px, 3vw, 36px) 18px;
  border-bottom: 1px solid var(--photo-line);
  background: var(--photo-surface);
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 28px;
}

.route-v2__header h1 {
  margin: 0 0 5px;
  font-size: clamp(24px, 2.5vw, 32px);
  letter-spacing: -.03em;
}

.route-v2__header p {
  max-width: 68ch;
  margin: 0;
  color: var(--photo-muted);
  font-size: 13px;
  line-height: 1.6;
}

.route-v2__status {
  color: var(--ui-success);
  display: inline-flex;
  align-items: center;
  gap: 8px;
  flex: none;
  font-size: 12px;
  font-weight: 600;
  white-space: nowrap;
}

.route-v2__status span {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: currentColor;
}

.route-v2__status.is-dirty,
.route-v2__status.is-saving {
  color: var(--ui-warning);
}

.route-v2__status.is-error,
.route-v2__status.is-conflict {
  color: var(--photo-danger);
}

.route-v2__steps {
  padding: 0 clamp(20px, 3vw, 36px);
  border-bottom: 1px solid var(--photo-line);
  background: var(--photo-surface);
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
}

.route-v2__steps button {
  position: relative;
  min-height: 68px;
  border: 0;
  border-radius: 0;
  background: transparent;
  display: grid;
  align-content: center;
  gap: 3px;
  text-align: left;
}

.route-v2__steps button::after {
  content: "";
  position: absolute;
  right: 12px;
  bottom: -1px;
  left: 12px;
  height: 3px;
  border-radius: 3px 3px 0 0;
  background: transparent;
}

.route-v2__steps button:hover:not(:disabled) {
  border-color: transparent;
  background: var(--photo-subtle);
}

.route-v2__steps button[aria-current="step"] {
  background: var(--photo-accent-soft);
}

.route-v2__steps button[aria-current="step"]::after {
  background: var(--photo-accent);
}

.route-v2__steps strong {
  font-size: 13px;
}

.route-v2__steps small {
  overflow: hidden;
  color: var(--photo-muted);
  font-size: 11px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.route-v2__board-context {
  padding: 9px clamp(20px, 3vw, 36px);
  border-bottom: 1px solid var(--photo-line);
  background: var(--photo-subtle);
  display: flex;
  align-items: center;
  gap: 14px;
  flex-wrap: wrap;
  font-size: 12px;
}

.route-v2__board-context span {
  color: var(--photo-muted);
}

.route-v2__board-context span + span {
  padding-left: 14px;
  border-left: 1px solid var(--ui-line-strong);
}

.route-v2__alert {
  max-width: 1380px;
  margin: 16px auto 0;
  padding: 12px 14px;
  border: 1px solid color-mix(in srgb, var(--photo-danger) 42%, white);
  border-radius: var(--ui-radius-small);
  background: color-mix(in srgb, var(--photo-danger) 9%, white);
  color: #792b2b;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  font-size: 13px;
}

.route-v2__upload {
  width: min(1120px, 100%);
  margin: auto;
  padding: 30px clamp(16px, 3vw, 32px) 48px;
  display: grid;
  gap: 22px;
}

.route-v2__drop {
  position: relative;
  min-height: 280px;
  border: 1px solid var(--ui-board-frame);
  border-radius: var(--ui-radius-card);
  background-color: var(--ui-board-face);
  background-image: radial-gradient(circle, var(--ui-board-hole) 0 2px, transparent 2.5px);
  background-size: 28px 28px;
  display: grid;
  place-items: center;
  overflow: hidden;
  text-align: center;
}

.route-v2__drop::after {
  content: "";
  position: absolute;
  inset: 18px;
  border: 1px dashed var(--ui-board-grid);
  border-radius: var(--ui-radius-small);
  pointer-events: none;
}

.route-v2__drop input {
  position: absolute;
  opacity: 0;
  pointer-events: none;
}

.route-v2__drop-copy {
  position: relative;
  z-index: 1;
  width: min(580px, calc(100% - 56px));
  padding: 30px;
  border-radius: var(--ui-radius-card);
  background: var(--photo-surface);
  box-shadow: var(--ui-shadow-float);
}

.route-v2__drop h2 {
  margin: 0 0 9px;
  font-size: 23px;
  letter-spacing: -.025em;
}

.route-v2__drop p {
  max-width: 62ch;
  margin: 0 auto 18px;
  color: var(--photo-muted);
  line-height: 1.7;
}

.route-v2__primary {
  border-color: var(--photo-accent) !important;
  background: var(--photo-accent) !important;
  color: var(--ui-brand-ink) !important;
  font-weight: 650 !important;
}

.route-v2__primary:hover:not(:disabled) {
  border-color: var(--photo-accent-hover) !important;
  background: var(--photo-accent-hover) !important;
}

.route-v2__wide {
  width: 100%;
  margin: 12px 0;
}

.route-v2__job,
.route-v2__recent {
  padding: 18px;
  border: 1px solid var(--photo-line);
  border-radius: var(--ui-radius-card);
  background: var(--photo-surface);
}

.route-v2__job > div {
  display: flex;
  justify-content: space-between;
  gap: 16px;
}

.route-v2__job progress {
  width: 100%;
  height: 9px;
  margin: 14px 0;
  accent-color: var(--photo-accent);
}

.route-v2__job p {
  color: var(--photo-danger);
}

.route-v2__section-heading {
  margin-bottom: 14px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
}

.route-v2__section-heading h2 {
  margin: 0;
  font-size: 17px;
  letter-spacing: -.015em;
}

.route-v2__section-heading p {
  margin: 4px 0 0;
  color: var(--photo-muted);
  font-size: 12px;
}

.route-v2__section-heading > span {
  color: var(--photo-muted);
  font-size: 12px;
}

.route-v2__recent > button {
  width: 100%;
  border-width: 1px 0 0;
  border-radius: 0;
  display: flex;
  align-items: center;
  justify-content: space-between;
  text-align: left;
}

.route-v2__recent > button span:first-child {
  display: grid;
  gap: 3px;
}

.route-v2__recent small,
.route-v2__history small {
  color: var(--photo-muted);
}

.route-v2__badge {
  padding: 4px 7px;
  border-radius: 999px;
  background: var(--photo-subtle);
  color: var(--photo-muted);
  font-size: 11px;
  white-space: nowrap;
}

.route-v2__review {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 310px;
}

.route-v2__photo-panel {
  min-width: 0;
  padding: 24px clamp(18px, 3vw, 32px) 36px;
}

.route-v2__photo-stage {
  position: relative;
  border: 1px solid var(--ui-line-strong);
  border-radius: var(--ui-radius-small);
  background: var(--ui-board-face);
  line-height: 0;
  overflow: hidden;
}

.route-v2__photo-stage > img {
  width: 100%;
  height: auto;
  display: block;
}

.route-v2__contours {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
}

.route-v2__contours g {
  cursor: pointer;
  outline: none;
}

.route-v2__contour-hit {
  fill: transparent;
  stroke: transparent;
  stroke-width: 44;
  vector-effect: non-scaling-stroke;
  pointer-events: stroke;
}

.route-v2__contour-line {
  fill: color-mix(in srgb, var(--object-color) 12%, transparent);
  stroke: var(--object-color);
  stroke-width: 2;
  vector-effect: non-scaling-stroke;
  pointer-events: none;
}

.route-v2__contour-line.needs-review {
  stroke-dasharray: 8 6;
}

.route-v2__contour-line.is-selected {
  stroke: white;
  stroke-width: 6;
  filter: drop-shadow(0 2px 3px rgba(28, 30, 33, .55));
}

.route-v2__calibration-points {
  fill: var(--photo-accent);
  stroke: var(--photo-ink);
  stroke-width: 6;
}

.route-v2__calibration-points text {
  fill: var(--photo-ink);
  stroke: none;
  font-size: 42px;
  font-weight: 700;
}

.route-v2__review-panel,
.route-v2__route-panel {
  min-width: 0;
  padding: 20px;
  border-left: 1px solid var(--photo-line);
  background: var(--photo-surface);
}

.route-v2__color-list {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 7px;
}

.route-v2__color-list button {
  padding: 7px;
  display: flex;
  align-items: center;
  gap: 7px;
}

.route-v2__color-list small {
  margin-left: auto;
  color: var(--photo-muted);
}

.route-v2__swatch {
  width: 13px;
  height: 13px;
  border: 1px solid rgba(28, 30, 33, .18);
  border-radius: 50%;
  display: inline-block;
  flex: none;
}

.route-v2__inspector,
.route-v2__route-panel fieldset {
  margin: 14px 0 0;
  padding: 16px 0 0;
  border: 0;
  border-top: 1px solid var(--photo-line);
  display: grid;
  gap: 11px;
}

.route-v2__inspector legend,
.route-v2__member legend {
  padding: 0 0 10px;
  font-weight: 650;
}

.route-v2 label {
  color: var(--photo-muted);
  display: grid;
  gap: 5px;
  font-size: 12px;
}

.route-v2__inspector p,
.route-v2__clean-result p {
  color: var(--photo-muted);
  font-size: 11px;
}

.route-v2__danger {
  border-color: color-mix(in srgb, var(--photo-danger) 48%, white) !important;
  color: var(--photo-danger) !important;
}

.route-v2__empty {
  color: var(--photo-muted);
  font-size: 13px;
  line-height: 1.65;
}

.route-v2__empty--large {
  padding: 100px 24px;
  text-align: center;
}

.route-v2__object-tools {
  margin-top: 8px;
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 7px;
}

.route-v2__merge-list {
  max-height: 132px;
  margin-top: 8px;
  padding: 8px;
  border: 1px solid var(--photo-line);
  border-radius: var(--ui-radius-small);
  overflow: auto;
}

.route-v2__merge-list label {
  min-height: 32px;
  padding: 4px;
  display: flex;
  align-items: center;
  gap: 7px;
}

.route-v2__nearby-holes {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 5px;
}

.route-v2__nearby-holes button {
  min-height: 36px;
  padding: 5px;
}

.route-v2__clean-result {
  padding: 18px;
  text-align: center;
}

.route-v2__clean-result img {
  width: 100%;
  max-height: 680px;
  border-radius: var(--ui-radius-small);
  display: block;
  object-fit: contain;
}

.route-v2__editor-top {
  padding: 12px clamp(18px, 3vw, 28px);
  border-bottom: 1px solid var(--photo-line);
  background: var(--photo-surface);
  display: flex;
  align-items: end;
  justify-content: space-between;
  gap: 16px;
}

.route-v2__editor-top label {
  min-width: 260px;
}

.route-v2__editor-top > div {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}

.route-v2__editor-grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 320px;
}

.route-v2__canvas-wrap {
  min-width: 0;
}

.route-v2__roles {
  display: flex;
  gap: 18px;
}

.route-v2__roles label,
.route-v2__route-list article > div label {
  display: flex;
  align-items: center;
  gap: 6px;
}

.route-v2__tags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.route-v2__tags button {
  min-height: 34px;
  padding: 5px 9px;
  font-size: 12px;
}

.route-v2__finish-actions {
  margin-top: 18px;
  display: flex;
  gap: 8px;
}

.route-v2__finish-actions button {
  flex: 1;
}

.route-v2__library {
  width: min(1440px, 100%);
  margin: auto;
  padding: 24px clamp(16px, 3vw, 32px) 44px;
}

.route-v2__library-tools {
  margin-bottom: 16px;
  display: grid;
  grid-template-columns: minmax(240px, 1fr) 160px 160px;
  gap: 10px;
}

.route-v2__library-grid {
  display: grid;
  grid-template-columns: minmax(300px, 480px) minmax(0, 1fr);
  gap: 18px;
}

.route-v2__route-list,
.route-v2__overlay {
  border: 1px solid var(--photo-line);
  border-radius: var(--ui-radius-card);
  background: var(--photo-surface);
  overflow: hidden;
}

.route-v2__route-list article {
  padding: 8px;
  border-bottom: 1px solid var(--photo-line);
}

.route-v2__route-main {
  width: 100%;
  border: 0;
  display: grid;
  grid-template-columns: auto minmax(0, 1fr) auto;
  align-items: center;
  gap: 10px;
  text-align: left;
}

.route-v2__route-main > span:nth-child(2) {
  min-width: 0;
  display: grid;
  gap: 4px;
}

.route-v2__route-list article > div {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 6px;
}

.route-v2__route-list article > div label {
  margin-right: auto;
}

.route-v2__history {
  padding: 8px;
  background: var(--photo-subtle);
  display: grid !important;
  gap: 5px !important;
}

.route-v2__history > button {
  width: 100%;
  display: flex;
  align-items: center;
  justify-content: space-between;
  text-align: left;
}

.route-v2__overlay {
  min-width: 0;
  padding: 16px;
}

.route-v2__overlay-legend {
  margin-bottom: 10px;
  display: flex;
  flex-wrap: wrap;
  gap: 8px 14px;
  font-size: 12px;
}

.route-v2__overlay-legend span {
  display: flex;
  align-items: center;
  gap: 5px;
}

.route-v2__overlay-legend i {
  width: 16px;
  height: 4px;
}

.route-v2 textarea {
  min-height: 76px;
  resize: vertical;
}

.route-v2 * {
  scrollbar-color: var(--ui-line-strong) transparent;
  scrollbar-width: thin;
}

@media (max-width: 1080px) {
  .route-v2__review,
  .route-v2__editor-grid,
  .route-v2__library-grid {
    grid-template-columns: 1fr;
  }

  .route-v2__review-panel,
  .route-v2__route-panel {
    border-top: 1px solid var(--photo-line);
    border-left: 0;
  }

  .route-v2__library-tools {
    grid-template-columns: 1fr 1fr;
  }

  .route-v2__library-tools input {
    grid-column: 1 / -1;
  }
}

@media (max-width: 620px) {
  .route-v2 {
    min-height: calc(100vh - var(--ui-shell-top) - var(--ui-shell-bottom));
  }

  .route-v2 :is(button, input, select, textarea) {
    min-height: 44px;
  }

  .route-v2__header {
    min-height: 82px;
    padding: 16px;
    align-items: flex-start;
  }

  .route-v2__header h1 {
    font-size: 22px;
  }

  .route-v2__header p {
    max-width: 36ch;
  }

  .route-v2__steps {
    padding: 0;
  }

  .route-v2__steps button {
    min-height: 52px;
    padding: 9px 7px;
    text-align: center;
  }

  .route-v2__steps button::after {
    right: 8px;
    left: 8px;
  }

  .route-v2__steps small {
    display: none;
  }

  .route-v2__board-context {
    padding: 8px 12px;
    gap: 8px 10px;
  }

  .route-v2__board-context span + span {
    padding-left: 10px;
  }

  .route-v2__alert {
    margin: 12px 12px 0;
    align-items: flex-start;
    flex-direction: column;
  }

  .route-v2__upload {
    padding: 14px 12px 30px;
  }

  .route-v2__drop {
    min-height: 242px;
  }

  .route-v2__drop-copy {
    width: calc(100% - 40px);
    padding: 22px 18px;
  }

  .route-v2__drop h2 {
    font-size: 20px;
  }

  .route-v2__photo-panel,
  .route-v2__review-panel,
  .route-v2__route-panel {
    padding: 14px 12px 22px;
  }

  .route-v2__section-heading {
    align-items: flex-start;
  }

  .route-v2__editor-top {
    padding: 12px;
    align-items: stretch;
    flex-direction: column;
  }

  .route-v2__editor-top label {
    min-width: 0;
  }

  .route-v2__editor-top > div {
    display: grid;
    grid-template-columns: repeat(4, 1fr);
  }

  .route-v2__editor-top > div button {
    padding-inline: 6px;
  }

  .route-v2__library {
    padding: 14px 12px 30px;
  }

  .route-v2__library-tools {
    grid-template-columns: 1fr;
  }

  .route-v2__library-tools input {
    grid-column: auto;
  }

  .route-v2__status {
    white-space: nowrap;
  }

  .route-v2__color-list {
    grid-template-columns: 1fr 1fr;
  }

  .route-v2__history > button {
    align-items: flex-start;
    flex-direction: column;
  }
}

@media (prefers-reduced-motion: no-preference) {
  .route-v2__drop {
    animation: photo-board-ready 360ms cubic-bezier(.2, .8, .2, 1) both;
  }

  .route-v2 button {
    transition: background-color 150ms ease-out, border-color 150ms ease-out, color 150ms ease-out;
  }
}

@keyframes photo-board-ready {
  from {
    opacity: .72;
    clip-path: inset(0 0 8% 0 round var(--ui-radius-card));
    transform: translateY(8px);
  }

  to {
    opacity: 1;
    clip-path: inset(0 round var(--ui-radius-card));
    transform: translateY(0);
  }
}
</style>
