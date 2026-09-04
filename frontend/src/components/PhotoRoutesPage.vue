<template>
  <section class="photo-routes-page" aria-label="照片线路工作台">
    <div class="photo-draft-toolbar">
      <label class="photo-draft-picker">当前草稿
        <select :value="draft?.id || ''" :disabled="loading" @change="switchDraft($event.target.value)">
          <option v-if="!drafts.length" value="">尚无照片线路草稿</option>
          <option v-for="item in drafts" :key="item.id" :value="item.id">{{ item.name || '未命名草稿' }}</option>
        </select>
      </label>
      <button class="photo-action" :aria-expanded="showImport" @click="showImport = !showImport">载入提取结果</button>
      <div class="photo-save-status" role="status" :class="`is-${saveState}`">{{ stateLabel }}</div>
      <button v-if="draft" class="photo-action primary" :disabled="!editable || ['saving', 'conflict'].includes(saveState)" @click="saveNow">保存草稿</button>
    </div>
    <div v-if="showImport" class="photo-import-panel">
      <p>从已在本机登记的提取结果创建草稿；同一结果重复载入会打开已有草稿。</p>
      <button v-for="item in extractions" :key="item.extraction_id" class="photo-action" :disabled="!editable || loading" @click="importDraft(item.extraction_id)">{{ item.name }} · {{ item.object_count }} 个对象</button>
      <span v-if="!extractions.length">暂无可用结果，请先运行本地证据导入工具。</span>
    </div>
    <div v-if="error" class="photo-error" role="alert">{{ error }} <button class="photo-action" @click="refresh">重试读取</button></div>
    <div v-if="saveState === 'conflict'" class="photo-conflict" role="alert">
      <strong>这条草稿已有更新。你的待保存修改已保留。</strong>
      <div><button class="photo-action" @click="downloadRecovery">下载待保存副本</button><button class="photo-action" @click="loadLatest">放弃本次修改，载入最新</button></div>
    </div>
    <div v-if="saveState === 'lease'" class="photo-conflict" role="alert">{{ editable ? '已可继续编辑，点击重试保存当前修改。' : '编辑权已失效，当前修改仍保留。请先取得编辑权。' }} <button v-if="editable" class="photo-action" @click="saveNow">重试保存</button></div>
    <div v-if="saveState === 'error'" class="photo-error" role="alert">保存失败，当前修改仍保留。<button class="photo-action" @click="saveNow">重试保存</button></div>
    <div v-if="recoveryWarning" class="photo-error" role="alert">{{ recoveryWarning }} <button v-if="draft" class="photo-action" @click="downloadRecovery">下载当前副本</button></div>
    <div v-if="loading && !draft" class="photo-empty" role="status">正在读取照片线路…</div>
    <div v-else-if="!draft" class="photo-empty"><h2>将提取线路放到电子岩板</h2><p>载入本机已有的提取结果，即可等比适配并自由编辑。</p><button class="photo-action primary" @click="showImport = true">选择提取结果</button></div>
    <template v-else>
      <div class="photo-editor-toolbar">
        <div class="photo-mode-tabs" aria-label="背景视图">
          <button v-for="item in viewModes" :key="item.value" :aria-pressed="viewMode === item.value" :disabled="item.value === 'clean' && !draft.source.background" @click="viewMode = item.value">{{ item.label }}</button>
        </div>
        <div class="photo-editor-actions">
          <button class="photo-action" :aria-pressed="interactionMode === 'browse'" @click="interactionMode = 'browse'">浏览</button>
          <button class="photo-action" :aria-pressed="interactionMode === 'edit'" :disabled="!editable || viewMode !== 'board'" @click="interactionMode = 'edit'">编辑</button>
          <button class="photo-icon-action" aria-label="撤销" :disabled="!editable || !canUndo" @click="undo"><RefreshLeft /></button>
          <button class="photo-icon-action" aria-label="重做" :disabled="!editable || !canRedo" @click="redo"><RefreshRight /></button>
        </div>
      </div>
      <div class="photo-editor-layout">
        <aside class="photo-object-panel">
          <div class="photo-panel-heading"><h2>线路对象</h2><span>{{ draft.objects.length }}</span></div>
          <button class="photo-group-button" :class="{ active: groupSelected }" @click="selectGroup">整条线路</button>
          <div class="photo-object-list">
            <button v-for="object in orderedObjects" :key="object.id" :class="{ active: selectedId === object.id && !groupSelected }" @click="selectObject(object.id)">
              <img :src="photoAssetUrl(object.cutout)" alt="" />
              <span><strong>{{ object.kind === 'volume' ? '造型' : '岩点' }} {{ object.id.replace('object-', '') }}</strong><small v-if="object.contour_status === 'needs_correction'" class="photo-needs-review">轮廓待修正</small><small v-else>{{ object.roles.map(r => r === 'start' ? '起点' : '终点').join(' / ') || '暂定轮廓' }}</small></span>
            </button>
          </div>
        </aside>
        <main class="photo-main-canvas">
          <PhotoRouteBoardCanvas v-if="viewMode === 'board'" ref="canvas" :objects="draft.objects" :selected-id="selectedId"
            :group-selected="groupSelected" :mode="interactionMode" :editable="editable" @select="canvasSelect"
            @begin="beginDrag" @move="moveDrag" @end="endDrag" @nudge="nudge" />
          <div v-else class="photo-reference-view">
            <p>{{ viewMode === 'original' ? '原始照片 · 保留拍摄位置' : '净化墙面 · 按来源位置叠回独立对象' }}</p>
            <img v-if="viewMode === 'original'" :src="photoAssetUrl(draft.source.original)" alt="线路原始照片" />
            <svg v-else :viewBox="`0 0 ${draft.source.working_dimensions.join(' ')}`" role="img" aria-label="净化背景与原位置目标对象">
              <image :href="photoAssetUrl(draft.source.background)" :width="draft.source.working_dimensions[0]" :height="draft.source.working_dimensions[1]" />
              <image v-for="object in orderedObjects" :key="object.id" :href="photoAssetUrl(object.cutout)" :x="object.source_bbox_px[0]" :y="object.source_bbox_px[1]" :width="object.source_bbox_px[2]" :height="object.source_bbox_px[3]" />
            </svg>
            <p>{{ viewMode === 'clean' ? '修补区域为合成外观。人物、标牌沿用当前结果。' : '电子岩板上的调整不会改写原始照片。' }}</p>
          </div>
          <p class="photo-fit-note">按比例适配后的设计尺度，不代表原墙实测尺寸。{{ reviewCount ? `${reviewCount} 个对象轮廓待修正。` : '当前提取轮廓尚未完成最终复核。' }}</p>
        </main>
        <aside class="photo-inspector">
          <div class="photo-panel-heading"><h2>{{ groupSelected ? '整条线路' : selectedObject ? `对象 ${selectedObject.id.replace('object-', '')}` : '对象调整' }}</h2><span v-if="!editable">只读</span></div>
          <fieldset :disabled="!editable || viewMode !== 'board'" class="photo-transform-fields">
            <template v-if="groupSelected">
              <p>整体移动或缩放，保持所有对象的相对关系。</p>
              <div class="photo-scale-buttons"><button class="photo-action" @click="scaleSelection(.95)">缩小 5%</button><button class="photo-action" @click="scaleSelection(1.05)">放大 5%</button></div>
              <div class="photo-group-nudge"><button class="photo-action" @click="nudge({ dx: -100, dy: 0 })">左移 10cm</button><button class="photo-action" @click="nudge({ dx: 100, dy: 0 })">右移 10cm</button><button class="photo-action" @click="nudge({ dx: 0, dy: 100 })">上移 10cm</button><button class="photo-action" @click="nudge({ dx: 0, dy: -100 })">下移 10cm</button></div>
              <button class="photo-action" @click="restoreFit">恢复初始适配</button>
            </template>
            <template v-else-if="selectedObject">
              <p v-if="selectedObject.contour_status === 'needs_correction'" class="photo-needs-review">该对象的可见轮廓仍需修正；移动和缩放不会消除分割错误。</p>
              <div class="photo-coordinate-fields">
                <label>横向位置（cm）<input type="number" :value="(selectedObject.center_x_mm/10).toFixed(1)" min="0" max="620" step="1" @change="numberPatch('center_x_mm', $event, 10)" /></label>
                <label>距底部（cm）<input type="number" :value="(selectedObject.center_y_mm/10).toFixed(1)" min="0" max="410" step="1" @change="numberPatch('center_y_mm', $event, 10)" /></label>
              </div>
              <label>旋转（度）<input type="number" :value="selectedObject.rotation_deg.toFixed(1)" min="-360" max="360" step="5" @change="numberPatch('rotation_deg', $event)" /></label>
              <label>大小（初始比例 %）<input type="number" :value="Math.round(selectedObject.scale_mm_per_px / initialScale * 100)" min="1" step="5" @change="numberPatch('scale_mm_per_px', $event, initialScale/100)" /></label>
              <label>对象类型<select :value="selectedObject.kind" @change="editObject({ kind: $event.target.value })"><option value="hold">岩点</option><option value="volume">造型</option></select></label>
              <div class="photo-role-fields"><label><input type="checkbox" :checked="selectedObject.roles.includes('start')" @change="toggleRole('start')" />起点</label><label><input type="checkbox" :checked="selectedObject.roles.includes('end')" @change="toggleRole('end')" />终点</label></div>
              <div class="photo-scale-buttons"><button class="photo-action" @click="reorder(-1)">下移一层</button><button class="photo-action" @click="reorder(1)">上移一层</button></div>
            </template>
            <p v-else>选择岩点或造型，调整位置、大小及前后层级。</p>
          </fieldset>
          <p v-if="geometryMessage" class="photo-needs-review" role="status">{{ geometryMessage }}</p>
          <div class="photo-metadata">
            <h3>线路信息</h3>
            <fieldset :disabled="!editable">
              <label>名称<input :value="draft.name" maxlength="120" placeholder="未命名草稿" @input="metadata('name', $event.target.value)" /></label>
              <label>颜色<input :value="draft.color" maxlength="40" @input="metadata('color', $event.target.value)" /></label>
              <label>原始难度（选填）<input :value="draft.original_grade" maxlength="40" placeholder="保留原始标注" @input="metadata('original_grade', $event.target.value)" /></label>
              <label>备注<textarea :value="draft.notes" maxlength="4000" rows="3" @input="metadata('notes', $event.target.value)" /></label>
            </fieldset>
            <small>草稿版本 {{ draft.version }} · 停止操作 2 秒自动保存</small>
          </div>
        </aside>
      </div>
    </template>
  </section>
</template>

<script setup>
import { computed, inject, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { ElMessageBox } from 'element-plus'
import { RefreshLeft, RefreshRight } from '@element-plus/icons-vue'
import PhotoRouteBoardCanvas from './PhotoRouteBoardCanvas.vue'
import service, { photoAssetUrl } from '../services/photoRouteService'
import { clone, createHistory, fitPhotoObjects, patchObject, scaleObjects, translateObjects } from '../utils/photoBoard.js'
import { createDraftAutosave } from '../utils/photoDraftAutosave.js'

const emit = defineEmits(['status'])
const access = inject('pilotAccess')
const editable = computed(() => !access.session.authEnabled || access.lease.ownedByMe)
const draft = ref(null), drafts = ref([]), extractions = ref([]), loading = ref(false), showImport = ref(false), error = ref('')
const saveState = ref('saved'), recoveryWarning = ref(''), geometryMessage = ref('')
const viewMode = ref('board'), interactionMode = ref('browse'), selectedId = ref(''), groupSelected = ref(false), canvas = ref(null)
const viewModes = [{ value: 'board', label: '电子岩板' }, { value: 'original', label: '原图对照' }, { value: 'clean', label: '净化墙面' }]
const orderedObjects = computed(() => [...(draft.value?.objects || [])].sort((a,b) => a.z_index-b.z_index))
const selectedObject = computed(() => draft.value?.objects.find(o => o.id === selectedId.value))
const initialScale = computed(() => draft.value ? fitPhotoObjects(draft.value.objects)[0].scale_mm_per_px : 1)
const reviewCount = computed(() => draft.value?.objects.filter(o => o.contour_status === 'needs_correction').length || 0)
const history = createHistory(), canUndo = ref(false), canRedo = ref(false)
let saver, dragBaseline, disposed = false
const storagePrefix = `photo-route:${access.session.username}:`
const stateLabel = computed(() => ({ saved: '已保存', dirty: '等待保存', saving: '保存中…', error: '保存失败', conflict: '版本冲突', lease: '修改待保存' }[saveState.value]))
function notify() { emit('status', { count: draft.value?.objects.length || 0, dirty: Boolean(saver?.dirty), state: stateLabel.value }) }
function remember(value) {
  if (!draft.value) return
  try { const key = `${storagePrefix}${draft.value.id}`; if (value) localStorage.setItem(key, JSON.stringify(value)); else localStorage.removeItem(key); recoveryWarning.value = '' }
  catch { recoveryWarning.value = '浏览器无法保留恢复副本。请保持页面打开并完成服务端保存。' }
}
function activate(data) {
  saver?.dispose(); draft.value = data; history.clear(); syncHistory(); selectedId.value = ''; groupSelected.value = false
  viewMode.value = 'board'; geometryMessage.value = ''; interactionMode.value = 'browse'
  saver = createDraftAutosave({ save: service.save, persist: remember, onState(value) { saveState.value = value; notify() },
    onSaved(saved, current) { if (current) draft.value = saved; else draft.value.version = saved.version; replaceList(saved); notify() } })
  saver.reset(data.version); saver.setAllowed(editable.value)
  try {
    localStorage.setItem(`${storagePrefix}active`, data.id)
    const recovered = JSON.parse(localStorage.getItem(`${storagePrefix}${data.id}`) || 'null')
    if (recovered?.id === data.id && recovered?.owner === data.owner && Array.isArray(recovered.objects)) {
      draft.value = recovered; saver.restore(recovered, recovered.version !== data.version)
    }
  } catch { recoveryWarning.value = '未能读取浏览器恢复副本，当前显示服务端草稿。' }
  notify()
}
function replaceList(data) { drafts.value = [data, ...drafts.value.filter(d => d.id !== data.id)] }
async function refresh() {
  loading.value = true; error.value = ''
  try {
    const [items, available] = await Promise.all([service.list(), service.extractions()])
    if (disposed) return
    drafts.value = items; extractions.value = available
    if (!draft.value && items.length) {
      let active; try { active = localStorage.getItem(`${storagePrefix}active`) } catch { /* service copy remains available */ }
      activate(items.find(d => d.id === active) || items[0])
    }
    if (!items.length) showImport.value = true
  } catch { error.value = '无法读取照片线路，请检查本机服务后重试。' }
  finally { loading.value = false }
}
async function beforeLeave() {
  endDrag(); await saver?.flush()
  if (!saver?.dirty) return true
  const message = recoveryWarning.value ? '当前修改尚未保存到服务器，浏览器也未能保留恢复副本。请先下载当前副本，离开可能丢失修改。' : '当前修改尚未保存到服务器。已保留在此浏览器，其他设备暂时看不到这些修改。'
  try { await ElMessageBox.confirm(message, '离开照片线路？', { confirmButtonText: '离开', cancelButtonText: '继续编辑' }); return true } catch { return false }
}
async function switchDraft(id) {
  if (!id || id === draft.value?.id || !(await beforeLeave())) return
  loading.value = true
  try { activate(await service.get(id)) } catch { error.value = '无法打开草稿，请重试。' } finally { loading.value = false }
}
async function importDraft(id) {
  if (!editable.value || !(await beforeLeave())) return
  loading.value = true
  try { const data = await service.import(id); replaceList(data); activate(data); showImport.value = false }
  catch (err) { error.value = typeof err?.response?.data?.detail === 'string' ? err.response.data.detail : '导入失败，请检查素材及提取结果。' }
  finally { loading.value = false }
}
function syncHistory() { canUndo.value = history.canUndo; canRedo.value = history.canRedo }
function changed() { syncHistory(); saver.change(draft.value); notify() }
function mutate(action) {
  if (!editable.value || !draft.value) return
  const before = clone(draft.value); action()
  if (JSON.stringify(before) !== JSON.stringify(draft.value)) { history.push(before); geometryMessage.value = ''; changed() }
}
function undo() { if (!editable.value) return; const version = draft.value.version; draft.value = history.undo(draft.value); draft.value.version = version; changed() }
function redo() { if (!editable.value) return; const version = draft.value.version; draft.value = history.redo(draft.value); draft.value.version = version; changed() }
function selectObject(id) { selectedId.value = id; groupSelected.value = false; geometryMessage.value = '' }
function canvasSelect(id) { if (!groupSelected.value) selectedId.value = id }
function selectGroup() { groupSelected.value = true; selectedId.value = ''; geometryMessage.value = '' }
function selectedObjects(id = selectedId.value) { return groupSelected.value ? draft.value.objects : draft.value.objects.filter(o => o.id === id) }
function applyObjects(objects) { const updates = new Map(objects.map(o => [o.id, o])); draft.value.objects = draft.value.objects.map(o => updates.get(o.id) || o) }
function beginDrag(id) { if (!editable.value) return; dragBaseline = clone(draft.value); if (!groupSelected.value) selectedId.value = id }
function moveDrag({ id, dx, dy }) {
  if (!dragBaseline || !editable.value) return
  const objects = groupSelected.value ? dragBaseline.objects : dragBaseline.objects.filter(o => o.id === id)
  applyObjects(translateObjects(objects, dx, dy))
}
function endDrag() { if (!dragBaseline) return; if (JSON.stringify(dragBaseline.objects) !== JSON.stringify(draft.value.objects)) { history.push(dragBaseline); changed() } dragBaseline = null }
function nudge({ id, dx, dy }) { mutate(() => applyObjects(translateObjects(selectedObjects(id), dx, dy))) }
function scaleSelection(factor) { const objects = selectedObjects(); const next = scaleObjects(objects, factor); if (next === objects) geometryMessage.value = '已到岩板边缘，无法继续放大。'; else mutate(() => applyObjects(next)) }
function restoreFit() { mutate(() => { draft.value.objects = fitPhotoObjects(draft.value.objects) }) }
function editObject(patch) { const next = patchObject(selectedObject.value, patch); if (next === selectedObject.value) geometryMessage.value = '调整会超出岩板边缘，请减小尺寸或先移动对象。'; else mutate(() => applyObjects([next])) }
function numberPatch(field, event, factor = 1) {
  const value = Number(event.target.value) * factor
  if (!Number.isFinite(value) || (field === 'rotation_deg' && Math.abs(value) > 360)) { event.target.value = selectedObject.value[field] / factor; return }
  editObject({ [field]: value }); event.target.value = Number((selectedObject.value[field] / factor).toFixed(1))
}
function toggleRole(role) { editObject({ roles: selectedObject.value.roles.includes(role) ? selectedObject.value.roles.filter(r => r !== role) : [...selectedObject.value.roles, role] }) }
function reorder(direction) { const objects = [...orderedObjects.value]; const index = objects.findIndex(o => o.id === selectedId.value), other = index + direction; if (other < 0 || other >= objects.length) return; [objects[index], objects[other]] = [objects[other], objects[index]]; mutate(() => { draft.value.objects = objects.map((o, i) => ({ ...o, z_index: i })) }) }
function metadata(field, value) { mutate(() => { draft.value[field] = value }) }
async function saveNow() { if (saveState.value !== 'conflict') await saver?.retry() }
function downloadRecovery() { const url = URL.createObjectURL(new Blob([JSON.stringify(draft.value, null, 2)], { type: 'application/json' })); const link = document.createElement('a'); link.href = url; link.download = `photo-route-${draft.value.id}-recovery.json`; link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000) }
async function loadLatest() {
  try { await ElMessageBox.confirm('建议先下载待保存副本。载入最新版本后，本浏览器中的待保存修改会被移除。', '载入服务器最新草稿', { confirmButtonText: '放弃修改并载入', cancelButtonText: '保留修改' }) } catch { return }
  try { const data = await service.get(draft.value.id); saver.reset(data.version); remember(null); activate(data); replaceList(data) } catch { error.value = '无法取得最新版本，当前修改仍保留。' }
}
function unload(event) { endDrag(); if (saver?.dirty) { event.preventDefault(); event.returnValue = '' } }
watch(editable, value => { if (!value) { endDrag(); interactionMode.value = 'browse' } saver?.setAllowed(value) })
onMounted(() => { refresh(); window.addEventListener('beforeunload', unload) })
onBeforeUnmount(() => { disposed = true; endDrag(); saver?.dispose(); window.removeEventListener('beforeunload', unload) })
defineExpose({ beforeLeave })
</script>

<style scoped>
.photo-routes-page { --photo-ink: #253448; --photo-line: #dce1e5; color: var(--photo-ink); min-width: 0; }
.photo-routes-page :is(button, input, select, textarea):focus-visible { outline: 2px solid #1f5f99; outline-offset: 2px; }
.photo-routes-page ::selection { background: #c9ddef; color: #132b45; }
.photo-routes-page :is(input, textarea) { caret-color: #1f5f99; }
.photo-draft-toolbar { display: flex; align-items: flex-end; flex-wrap: wrap; gap: 12px; padding: 14px 20px; border-bottom: 1px solid var(--photo-line); background: #fff; }
.photo-draft-picker { display: grid; gap: 4px; color: #526173; font-size: 12px; min-width: 230px; max-width: 100%; }
.photo-routes-page select, .photo-routes-page input:not([type=checkbox]), .photo-routes-page textarea { width: 100%; min-width: 0; border: 1px solid #bfc9d2; border-radius: 4px; background: #fff; color: #253448; padding: 9px 10px; font: inherit; }
.photo-routes-page input::placeholder { color: #687787; }
.photo-action, .photo-icon-action { display: inline-flex; justify-content: center; align-items: center; gap: 6px; min-height: 38px; padding: 8px 12px; border: 1px solid #bfc9d2; border-radius: 4px; color: #294159; background: #fff; font: inherit; font-size: 13px; cursor: pointer; }
.photo-action:hover, .photo-icon-action:hover { background: #edf3f8; }
.photo-action.primary { color: #fff; background: #1f5f99; border-color: #1f5f99; }
.photo-routes-page button:disabled { cursor: default; opacity: .45; }
.photo-action[aria-pressed=true] { background: #e6eff6; border-color: #1f5f99; color: #194e7e; }
.photo-icon-action { padding: 8px; }
.photo-icon-action svg { width: 18px; height: 18px; }
.photo-save-status { margin-left: auto; align-self: center; color: #376152; font-size: 12px; }
.photo-save-status:is(.is-error,.is-conflict,.is-lease) { color: #9b421d; }
.photo-import-panel { padding: 14px 20px; display: flex; gap: 10px; flex-wrap: wrap; background: #f2f6f9; border-bottom: 1px solid var(--photo-line); font-size: 13px; }
.photo-import-panel p { flex-basis: 100%; margin: 0; }
.photo-error, .photo-conflict { margin: 10px 20px; padding: 12px; background: #fff0df; color: #813b16; font-size: 13px; display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 10px; }
.photo-conflict > div { display: flex; flex-wrap: wrap; gap: 8px; }
.photo-empty { padding: 80px 24px; text-align: center; color: #526173; }
.photo-empty h2 { color: #253448; font-size: 24px; }
.photo-editor-toolbar { display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 12px; padding: 10px 20px; background: #fafbfc; border-bottom: 1px solid var(--photo-line); }
.photo-mode-tabs { display: flex; gap: 4px; }
.photo-mode-tabs button { background: transparent; color: #57687a; border: 0; border-bottom: 2px solid transparent; padding: 10px 12px; font: inherit; font-size: 13px; cursor: pointer; }
.photo-mode-tabs button[aria-pressed=true] { color: #194e7e; border-bottom-color: #1f5f99; }
.photo-editor-actions { display: flex; gap: 6px; }
.photo-editor-layout { display: grid; grid-template-columns: 164px minmax(0, 1fr) 242px; align-items: start; }
.photo-object-panel, .photo-inspector { padding: 16px 12px; min-width: 0; background: #fff; }
.photo-object-panel { border-right: 1px solid var(--photo-line); }
.photo-inspector { border-left: 1px solid var(--photo-line); }
.photo-panel-heading { display: flex; align-items: baseline; justify-content: space-between; margin-bottom: 14px; gap: 8px; }
.photo-panel-heading h2 { margin: 0; font-size: 15px; font-weight: 650; }
.photo-panel-heading span { font-size: 12px; color: #687787; }
.photo-group-button { width: 100%; padding: 10px; background: #f3f6f8; border: 1px solid transparent; color: #344d66; font: inherit; font-size: 13px; text-align: left; cursor: pointer; border-radius: 4px; }
.photo-group-button.active, .photo-object-list button.active { background: #eaf1f7; border-color: #7ca3c5; }
.photo-object-list { max-height: 610px; overflow: auto; margin-top: 8px; scrollbar-width: thin; scrollbar-color: #aab8c4 #f6f7f9; }
.photo-object-list button { width: 100%; padding: 7px 4px; display: flex; gap: 8px; align-items: center; text-align: left; border: 1px solid transparent; border-radius: 4px; background: #fff; color: #31465d; cursor: pointer; }
.photo-object-list button:hover { background: #f2f6f9; }
.photo-object-list img { width: 44px; height: 48px; object-fit: contain; }
.photo-object-list span { display: grid; gap: 4px; }
.photo-object-list strong { font-size: 12px; font-weight: 600; }
.photo-object-list small { font-size: 10px; color: #637385; }
.photo-object-list .photo-needs-review, .photo-needs-review { color: #904215; }
.photo-main-canvas { min-width: 0; background: #f3f0e9; }
.photo-fit-note { margin: 0; padding: 12px 16px 20px; color: #675b48; font-size: 12px; line-height: 1.6; }
.photo-reference-view { padding: 16px; text-align: center; background: #ebe8e1; }
.photo-reference-view > img, .photo-reference-view > svg { display: block; width: 100%; height: 600px; object-fit: contain; }
.photo-reference-view p { font-size: 12px; color: #5c5345; }
.photo-inspector fieldset { padding: 0; margin: 0; border: 0; min-width: 0; display: grid; gap: 12px; }
.photo-inspector label { display: grid; gap: 6px; font-size: 12px; color: #526173; }
.photo-inspector p { font-size: 12px; line-height: 1.7; margin: 0 0 12px; }
.photo-coordinate-fields, .photo-group-nudge { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
.photo-scale-buttons { display: flex; gap: 8px; flex-wrap: wrap; }
.photo-role-fields { display: flex; gap: 20px; }
.photo-role-fields label { display: flex; align-items: center; gap: 6px; }
.photo-role-fields input { accent-color: #1f5f99; }
.photo-metadata { border-top: 1px solid var(--photo-line); margin-top: 24px; padding-top: 20px; }
.photo-metadata h3 { margin: 0 0 16px; font-size: 14px; }
.photo-metadata small { display: block; color: #687787; font-size: 11px; margin-top: 14px; }
@media (max-width: 1180px) {
  .photo-editor-layout { grid-template-columns: 140px minmax(0, 1fr); }
  .photo-inspector { grid-column: 1 / -1; border-top: 1px solid var(--photo-line); border-left: 0; display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
  .photo-inspector > .photo-panel-heading { grid-column: 1; margin-bottom: 0; }
  .photo-transform-fields { grid-column: 1; }
  .photo-metadata { grid-column: 2; grid-row: 1 / 4; margin: 0; padding: 0 0 0 20px; border-top: 0; border-left: 1px solid var(--photo-line); }
}
@media (max-width: 760px) {
  .photo-draft-toolbar { padding: 12px; gap: 8px; }
  .photo-draft-picker { width: 100%; min-width: 0; }
  .photo-action { min-height: 42px; }
  .photo-editor-toolbar { padding: 8px 12px; gap: 8px; }
  .photo-mode-tabs { width: 100%; }
  .photo-mode-tabs button { flex: 1; padding: 10px 6px; }
  .photo-editor-actions { width: 100%; justify-content: flex-end; }
  .photo-editor-layout { display: flex; flex-direction: column; }
  .photo-main-canvas { order: 0; width: 100%; }
  .photo-object-panel { order: 1; width: 100%; border-right: 0; border-block: 1px solid var(--photo-line); padding: 12px; }
  .photo-object-list { display: flex; gap: 8px; overflow-x: auto; max-height: none; }
  .photo-object-list button { width: 124px; min-width: 124px; }
  .photo-group-button { width: auto; }
  .photo-panel-heading { margin-bottom: 8px; }
  .photo-inspector { order: 2; display: block; width: 100%; padding: 16px; }
  .photo-metadata { margin-top: 20px; padding: 20px 0 0; border-left: 0; border-top: 1px solid var(--photo-line); }
  .photo-reference-view > img, .photo-reference-view > svg { height: 440px; }
  .photo-error, .photo-conflict { margin: 8px 12px; }
  .photo-fit-note { font-size: 11px; padding: 10px 12px; }
}
@media (prefers-reduced-motion: no-preference) { .photo-object-list button { transition: background-color .15s ease-out; } }
</style>
