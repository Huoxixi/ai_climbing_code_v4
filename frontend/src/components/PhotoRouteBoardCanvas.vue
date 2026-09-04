<template>
  <div class="photo-canvas-shell">
    <div class="photo-view-controls">
      <span>6.2 × 4.1 m <span class="photo-muted">· 点距 20 cm</span></span>
      <div>
        <button type="button" :aria-pressed="labels" @click="labels = !labels">孔位编号</button>
        <button type="button" aria-label="缩小岩板" :disabled="camera.zoom <= 1" @click="zoomAt(1 / 1.3)"><ZoomOut /></button>
        <span class="photo-zoom-value">{{ Math.round(camera.zoom * 100) }}%</span>
        <button type="button" aria-label="放大岩板" :disabled="camera.zoom >= 8" @click="zoomAt(1.3)"><ZoomIn /></button>
        <button type="button" @click="resetCamera">看全板</button>
      </div>
    </div>
    <div ref="viewport" class="photo-wall-viewport" :class="{ 'is-browsing': mode === 'browse' }"
      aria-label="30列20行照片线路电子岩板，可缩放和平移" @wheel.prevent="wheel"
      @pointerdown="pointerDown" @pointermove="pointerMove" @pointerup="pointerUp" @pointercancel="pointerUp"
      @lostpointercapture="pointerUp">
      <svg class="photo-wood-wall" :style="wallStyle" viewBox="0 0 6200 4100" aria-label="浅木色无边框岩板">
        <g class="photo-panel-joints" aria-hidden="true">
          <line v-for="x in [1240, 2480, 3720, 4960]" :key="x" :x1="x" :x2="x" y1="0" y2="4100" />
          <line x1="0" x2="6200" y1="2050" y2="2050" />
        </g>
        <g class="photo-reference-holes" aria-hidden="true">
          <circle v-for="hole in holes" :key="hole.id" :cx="hole.x" :cy="4100-hole.y" r="9"><title>{{ hole.id }}</title></circle>
        </g>
        <g v-if="labels" class="photo-axis-labels" aria-hidden="true">
          <text v-for="i in 30" :key="`x${i}`" :x="200+(i-1)*200" y="4070" text-anchor="middle">{{ columnLabel(i-1) }}</text>
          <text v-for="i in 20" :key="`y${i}`" x="60" :y="4100-(100+(i-1)*200)+15" text-anchor="middle">{{ i }}</text>
        </g>
        <g v-for="object in sortedObjects" :key="object.id" :data-object-id="object.id"
          :transform="`translate(${object.center_x_mm} ${4100-object.center_y_mm}) rotate(${object.rotation_deg})`"
          class="photo-wall-object" :class="{ 'is-selected': selectedId === object.id || groupSelected }"
          role="button" tabindex="0" :aria-label="objectLabel(object)" :aria-pressed="selectedId === object.id"
          @keydown="objectKey($event, object.id)">
          <image :href="photoAssetUrl(object.cutout)" :x="-objectWidth(object)/2" :y="-objectHeight(object)/2"
            :width="objectWidth(object)" :height="objectHeight(object)" draggable="false" />
          <rect v-if="selectedId === object.id || groupSelected" class="photo-object-selection"
            :x="-objectWidth(object)/2-8" :y="-objectHeight(object)/2-8" :width="objectWidth(object)+16" :height="objectHeight(object)+16" />
          <g v-if="object.roles.length" class="photo-role-marker" :transform="`translate(${-objectWidth(object)/2} ${-objectHeight(object)/2})`">
            <rect x="-18" y="-68" :width="object.roles.length * 84" height="72" rx="10" />
            <text x="-5" y="-15">{{ object.roles.map(role => role === 'start' ? '起' : '终').join(' ') }}</text>
          </g>
        </g>
      </svg>
    </div>
    <div class="photo-canvas-caption"><span>{{ mode === 'browse' ? '拖动画布 · 双指或滚轮缩放' : groupSelected ? '拖动任一对象可移动整条线路' : '点选并拖动对象 · 方向键微调' }}</span><span>按比例适配 · 无吸附</span></div>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { ZoomIn, ZoomOut } from '@element-plus/icons-vue'
import { photoHoles, columnLabel, zoomCamera } from '../utils/photoBoard.js'
import { photoAssetUrl } from '../services/photoRouteService'

const props = defineProps({ objects: { type: Array, required: true }, selectedId: { type: String, default: '' }, groupSelected: Boolean, mode: { type: String, default: 'browse' }, editable: Boolean })
const emit = defineEmits(['select', 'begin', 'move', 'end', 'nudge'])
const viewport = ref(null), labels = ref(false)
const camera = reactive({ zoom: 1, x: 0, y: 0 }), size = reactive({ width: 1, height: 1 })
const holes = photoHoles()
const sortedObjects = computed(() => [...props.objects].sort((a, b) => a.z_index - b.z_index))
const baseWidth = computed(() => Math.min(size.width, size.height * 6200 / 4100))
const wallStyle = computed(() => ({ width: `${baseWidth.value}px`, height: `${baseWidth.value * 4100 / 6200}px`, transform: `translate(-50%, -50%) translate(${camera.x}px, ${camera.y}px) scale(${camera.zoom})` }))
const objectWidth = (o) => o.source_bbox_px[2] * o.scale_mm_per_px
const objectHeight = (o) => o.source_bbox_px[3] * o.scale_mm_per_px
const objectLabel = (o) => `对象 ${o.id.replace('object-', '')}${o.kind === 'volume' ? '，造型' : '，岩点'}${o.contour_status === 'needs_correction' ? '，轮廓待修正' : ''}`
let observer, drag = null, pinch = null
const pointers = new Map()
function resetCamera() { Object.assign(camera, { zoom: 1, x: 0, y: 0 }) }
function zoomAt(factor, point = { x: 0, y: 0 }) { Object.assign(camera, zoomCamera(camera, factor, point)) }
function localPoint(event) { const r = viewport.value.getBoundingClientRect(); return { x: event.clientX - r.left - r.width / 2, y: event.clientY - r.top - r.height / 2 } }
function wheel(event) { zoomAt(event.deltaY < 0 ? 1.12 : 1 / 1.12, localPoint(event)) }
function pinchState() { const [a, b] = [...pointers.values()]; return { distance: Math.hypot(a.x-b.x, a.y-b.y), center: { x: (a.x+b.x)/2, y: (a.y+b.y)/2 } } }
function pointerDown(event) {
  if (event.button !== 0) return
  const point = localPoint(event)
  pointers.set(event.pointerId, point)
  viewport.value.setPointerCapture(event.pointerId)
  if (pointers.size === 2) {
    if (drag?.kind === 'object') emit('end')
    drag = null; pinch = pinchState(); return
  }
  const id = event.target.closest('[data-object-id]')?.dataset.objectId
  if (id) emit('select', id)
  if (id && props.mode === 'edit' && props.editable) {
    drag = { kind: 'object', id, start: point }; emit('begin', id)
  } else drag = { kind: 'pan', start: point, x: camera.x, y: camera.y }
}
function pointerMove(event) {
  if (!pointers.has(event.pointerId)) return
  const point = localPoint(event); pointers.set(event.pointerId, point)
  if (pointers.size >= 2) {
    const next = pinchState()
    if (pinch?.distance > 0) { zoomAt(next.distance / pinch.distance, pinch.center); camera.x += next.center.x - pinch.center.x; camera.y += next.center.y - pinch.center.y }
    pinch = next; return
  }
  if (!drag) return
  if (drag.kind === 'pan') { camera.x = drag.x + point.x - drag.start.x; camera.y = drag.y + point.y - drag.start.y }
  else if (props.editable) emit('move', { id: drag.id, dx: (point.x - drag.start.x) * 6200 / (baseWidth.value * camera.zoom), dy: -(point.y - drag.start.y) * 6200 / (baseWidth.value * camera.zoom) })
}
function pointerUp(event) {
  if (!pointers.has(event.pointerId)) return
  pointers.delete(event.pointerId)
  if (drag?.kind === 'object') emit('end')
  drag = null; pinch = null
  if (pointers.size === 1) drag = { kind: 'pan', start: [...pointers.values()][0], x: camera.x, y: camera.y }
}
function objectKey(event, id) {
  if (['Enter', ' '].includes(event.key)) { event.preventDefault(); emit('select', id); return }
  if (!props.editable || props.mode !== 'edit') return
  const vector = { ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, 1], ArrowDown: [0, -1] }[event.key]
  if (!vector) return
  event.preventDefault(); emit('select', id); emit('nudge', { id, dx: vector[0] * (event.shiftKey ? 50 : 10), dy: vector[1] * (event.shiftKey ? 50 : 10) })
}
watch(() => props.editable, (value) => { if (!value && drag?.kind === 'object') { emit('end'); drag = null } })
onMounted(() => { observer = new ResizeObserver(([entry]) => { size.width = entry.contentRect.width; size.height = entry.contentRect.height }); observer.observe(viewport.value) })
onBeforeUnmount(() => observer?.disconnect())
defineExpose({ resetCamera })
</script>

<style scoped>
.photo-canvas-shell { min-width: 0; background: #f3f0e9; }
.photo-view-controls, .photo-canvas-caption { display: flex; align-items: center; justify-content: space-between; gap: 10px; padding: 12px 16px; color: #554c3d; font-size: 12px; }
.photo-view-controls > div { display: flex; align-items: center; gap: 4px; }
.photo-view-controls button { background: transparent; border: 0; color: #4b4439; min-height: 36px; padding: 6px 9px; cursor: pointer; border-radius: 4px; }
.photo-view-controls button:hover, .photo-view-controls button[aria-pressed=true] { background: #e3ded3; }
.photo-view-controls button:disabled { opacity: .4; cursor: default; }
.photo-view-controls button svg { width: 18px; height: 18px; vertical-align: middle; }
.photo-view-controls button:focus-visible { outline: 2px solid #1f5f99; outline-offset: 2px; }
.photo-muted { color: #6c6253; }
.photo-zoom-value { min-width: 40px; text-align: center; font-variant-numeric: tabular-nums; }
.photo-wall-viewport { position: relative; width: 100%; height: clamp(350px, 55vw, 680px); overflow: hidden; touch-action: none; user-select: none; }
.photo-wall-viewport.is-browsing { cursor: grab; }
.photo-wall-viewport.is-browsing:active { cursor: grabbing; }
.photo-wood-wall { position: absolute; left: 50%; top: 50%; transform-origin: center; border: 0; border-radius: 0; box-shadow: none; background: #e8d4b2 url('../assets/photo-wall-birch.png') center / cover; }
.photo-panel-joints { stroke: #8c704545; stroke-width: 4; pointer-events: none; }
.photo-reference-holes { fill: #695439; pointer-events: none; }
.photo-axis-labels { fill: #57452f; font-size: 43px; font-weight: 500; pointer-events: none; }
.photo-wall-object { cursor: pointer; outline: none; }
.photo-wall-object image { pointer-events: all; }
.photo-wall-object:focus-visible image { outline: 3px solid #1f5f99; }
.photo-object-selection { fill: none; stroke: #174d78; stroke-width: 1.5; vector-effect: non-scaling-stroke; pointer-events: none; }
.photo-role-marker { pointer-events: none; }
.photo-role-marker rect { fill: #fffdf5; }
.photo-role-marker text { fill: #1a4536; font-size: 55px; font-weight: 700; }
.photo-canvas-caption { border-top: 1px solid #ddd5c8; color: #675b48; flex-wrap: wrap; }
@media (max-width: 760px) {
  .photo-wall-viewport { height: max(285px, 66vw); }
  .photo-view-controls { padding: 8px; align-items: flex-start; flex-direction: column; gap: 4px; }
  .photo-view-controls > div { width: 100%; justify-content: flex-end; }
  .photo-canvas-caption { font-size: 11px; padding: 10px; }
}
</style>
