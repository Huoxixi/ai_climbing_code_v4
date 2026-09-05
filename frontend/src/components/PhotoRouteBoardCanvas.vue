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
      aria-label="30列20行抱石线路电子岩板，可缩放和平移" @wheel.prevent="wheel"
      @pointerdown="pointerDown" @pointermove="pointerMove" @pointerup="pointerUp" @pointercancel="pointerUp"
      @lostpointercapture="pointerUp">
      <svg class="photo-technical-wall" :style="wallStyle" :viewBox="`0 0 ${PHOTO_BOARD.board_width_mm} ${PHOTO_BOARD.board_height_mm}`" aria-label="30列20行中性灰技术岩板">
        <g class="photo-panel-joints" aria-hidden="true">
          <line v-for="x in [1240, 2480, 3720, 4960]" :key="x" :x1="x" :x2="x" y1="0" y2="4100" />
          <line x1="0" x2="6200" y1="2050" y2="2050" />
        </g>
        <g class="photo-reference-holes" aria-hidden="true">
          <circle v-for="hole in holes" :key="hole.id" :cx="hole.x" :cy="PHOTO_BOARD.board_height_mm-hole.y" r="9"><title>{{ hole.id }}</title></circle>
        </g>
        <g v-if="snapPreview" class="photo-snap-preview" aria-hidden="true">
          <circle :cx="snapPreview.x" :cy="PHOTO_BOARD.board_height_mm-snapPreview.y" r="42" />
          <line :x1="snapPreview.fromX" :y1="PHOTO_BOARD.board_height_mm-snapPreview.fromY" :x2="snapPreview.x" :y2="PHOTO_BOARD.board_height_mm-snapPreview.y" />
        </g>
        <g v-if="labels" class="photo-axis-labels" aria-hidden="true">
          <text v-for="i in 30" :key="`x${i}`" :x="200+(i-1)*200" y="4070" text-anchor="middle">{{ columnLabel(i-1) }}</text>
          <text v-for="i in 20" :key="`y${i}`" x="60" :y="4100-(100+(i-1)*200)+15" text-anchor="middle">{{ i }}</text>
        </g>
        <g v-for="object in sortedObjects" :key="object.id" :data-object-id="object.id"
          :transform="`translate(${object.center_x_mm} ${PHOTO_BOARD.board_height_mm-object.center_y_mm}) rotate(${object.rotation_deg})`"
          class="photo-wall-object" :class="{ 'is-selected': selectedId === object.id || groupSelected }"
          role="button" tabindex="0" :aria-label="objectLabel(object)" :aria-pressed="selectedId === object.id"
          @keydown="objectKey($event, object.id)">
          <image :href="resolveAsset(object.cutout)" :x="-objectWidth(object)/2" :y="-objectHeight(object)/2"
            :width="objectWidth(object)" :height="objectHeight(object)" draggable="false" />
          <rect v-if="object.route_color" class="photo-route-outline" :style="{ stroke:object.route_color }"
            :x="-objectWidth(object)/2-12" :y="-objectHeight(object)/2-12" :width="objectWidth(object)+24" :height="objectHeight(object)+24"><title>{{ object.route_name }}</title></rect>
          <rect v-if="selectedId === object.id || groupSelected" class="photo-object-selection"
            :x="-objectWidth(object)/2-8" :y="-objectHeight(object)/2-8" :width="objectWidth(object)+16" :height="objectHeight(object)+16" />
          <g v-if="object.roles.length" class="photo-role-marker" :transform="`translate(${-objectWidth(object)/2} ${-objectHeight(object)/2})`">
            <rect x="-18" y="-68" :width="object.roles.length * 84" height="72" rx="10" />
            <text x="-5" y="-15">{{ object.roles.map(role => role === 'start' ? '起' : '终').join(' ') }}</text>
          </g>
        </g>
      </svg>
    </div>
    <div class="photo-canvas-caption"><span>{{ mode === 'browse' ? '拖动画布 · 双指或滚轮缩放' : groupSelected ? '拖动任一对象可移动整条线路' : '点选并拖动对象 · 方向键微调' }}</span><span>{{ mode === 'edit' && snapping ? '释放后吸附到最近孔位' : '按比例适配 · 自由移动' }}</span></div>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { ZoomIn, ZoomOut } from '@element-plus/icons-vue'
import { PHOTO_BOARD, photoHoles, columnLabel, zoomCamera } from '../utils/photoBoard.js'
import { photoAssetUrl } from '../services/photoRouteService'

const props = defineProps({ objects: { type: Array, required: true }, selectedId: { type: String, default: '' }, groupSelected: Boolean, mode: { type: String, default: 'browse' }, editable: Boolean, snapping: Boolean, snapPreview: { type: Object, default: null }, assetUrl: { type: Function, default: photoAssetUrl } })
const emit = defineEmits(['select', 'begin', 'move', 'end', 'nudge'])
const viewport = ref(null), labels = ref(false)
const camera = reactive({ zoom: 1, x: 0, y: 0 }), size = reactive({ width: 1, height: 1 })
const holes = photoHoles()
const sortedObjects = computed(() => [...props.objects].sort((a, b) => a.z_index - b.z_index))
const baseWidth = computed(() => Math.min(size.width, size.height * PHOTO_BOARD.board_width_mm / PHOTO_BOARD.board_height_mm))
const wallStyle = computed(() => ({ width: `${baseWidth.value}px`, height: `${baseWidth.value * PHOTO_BOARD.board_height_mm / PHOTO_BOARD.board_width_mm}px`, transform: `translate(-50%, -50%) translate(${camera.x}px, ${camera.y}px) scale(${camera.zoom})` }))
const objectWidth = (o) => o.source_bbox_px[2] * o.scale_mm_per_px
const objectHeight = (o) => o.source_bbox_px[3] * o.scale_mm_per_px
const resolveAsset = (asset) => props.assetUrl(asset)
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
  else if (props.editable) emit('move', { id: drag.id, dx: (point.x - drag.start.x) * PHOTO_BOARD.board_width_mm / (baseWidth.value * camera.zoom), dy: -(point.y - drag.start.y) * PHOTO_BOARD.board_width_mm / (baseWidth.value * camera.zoom) })
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
.photo-canvas-shell {
  min-width: 0;
  background: var(--ui-surface-subtle);
}

.photo-view-controls,
.photo-canvas-caption {
  padding: 11px 16px;
  color: var(--ui-ink-muted);
  background: var(--ui-surface);
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  font-size: 12px;
}

.photo-view-controls {
  border-bottom: 1px solid var(--ui-line);
}

.photo-view-controls > div {
  display: flex;
  align-items: center;
  gap: 4px;
}

.photo-view-controls button {
  min-height: 36px;
  padding: 6px 9px;
  border: 0;
  border-radius: var(--ui-radius-small);
  background: transparent;
  color: var(--ui-ink);
  cursor: pointer;
}

.photo-view-controls button:hover,
.photo-view-controls button[aria-pressed="true"] {
  background: var(--ui-brand-soft);
}

.photo-view-controls button:disabled {
  cursor: default;
  opacity: .4;
}

.photo-view-controls button svg {
  width: 18px;
  height: 18px;
  vertical-align: middle;
}

.photo-view-controls button:focus-visible,
.photo-wall-object:focus-visible {
  outline: 3px solid var(--ui-focus);
  outline-offset: 2px;
}

.photo-muted {
  color: var(--ui-ink-faint);
}

.photo-zoom-value {
  min-width: 40px;
  text-align: center;
  font-variant-numeric: tabular-nums;
}

.photo-wall-viewport {
  position: relative;
  width: 100%;
  height: auto;
  aspect-ratio: 6200 / 4100;
  max-height: calc(100dvh - 260px);
  background: var(--ui-ground);
  overflow: hidden;
  touch-action: none;
  user-select: none;
}

.photo-wall-viewport.is-browsing {
  cursor: grab;
}

.photo-wall-viewport.is-browsing:active {
  cursor: grabbing;
}

.photo-technical-wall {
  position: absolute;
  display: block;
  max-width: none;
  max-height: none;
  top: 50%;
  left: 50%;
  border: 1px solid var(--ui-board-frame);
  border-radius: 2px;
  background: var(--ui-board-face);
  box-shadow: 0 18px 36px rgba(28, 30, 33, .14);
  transform-origin: center;
}

.photo-panel-joints {
  stroke: var(--ui-board-grid);
  stroke-width: 3;
  opacity: .42;
  pointer-events: none;
}

.photo-reference-holes {
  fill: var(--ui-board-hole);
  opacity: .88;
  pointer-events: none;
}

.photo-snap-preview {
  fill: none;
  stroke: var(--ui-brand);
  stroke-width: 18;
  pointer-events: none;
}

.photo-snap-preview line {
  stroke-dasharray: 30 22;
}

.photo-axis-labels {
  fill: var(--ui-ink-muted);
  font-size: 43px;
  font-weight: 500;
  pointer-events: none;
}

.photo-wall-object {
  cursor: pointer;
  outline: none;
}

.photo-wall-object image {
  pointer-events: all;
}

.photo-object-selection {
  fill: none;
  stroke: var(--ui-brand);
  stroke-width: 3;
  vector-effect: non-scaling-stroke;
  pointer-events: none;
}

.photo-route-outline {
  fill: none;
  stroke-width: 5;
  vector-effect: non-scaling-stroke;
  pointer-events: none;
}

.photo-role-marker {
  pointer-events: none;
}

.photo-role-marker rect {
  fill: var(--ui-brand);
}

.photo-role-marker text {
  fill: var(--ui-brand-ink);
  font-size: 55px;
  font-weight: 700;
}

.photo-canvas-caption {
  border-top: 1px solid var(--ui-line);
  flex-wrap: wrap;
}

@media (max-width: 760px) {
  .photo-wall-viewport {
    height: auto;
    max-height: none;
    aspect-ratio: 6200 / 4100;
  }

  .photo-view-controls {
    padding: 8px 10px;
    align-items: flex-start;
    flex-direction: column;
    gap: 4px;
  }

  .photo-view-controls > div {
    width: 100%;
    justify-content: flex-end;
  }

  .photo-view-controls button {
    min-height: 44px;
  }

  .photo-canvas-caption {
    padding: 10px;
    font-size: 11px;
  }

  .photo-technical-wall {
    box-shadow: 0 12px 26px rgba(28, 30, 33, .12);
  }
}
</style>
