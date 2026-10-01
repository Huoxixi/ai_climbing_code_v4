<template>
  <div class="photo-canvas-shell">
    <div class="photo-view-controls">
      <span>4.1 × 6.2 m <span class="photo-muted">· 点距 20 cm</span></span>
      <div>
        <button type="button" :aria-pressed="labels" @click="labels = !labels">孔位编号</button>
        <button type="button" aria-label="缩小岩板" :disabled="camera.zoom <= 1" @click="zoomAt(1 / 1.3)"><ZoomOut /></button>
        <span class="photo-zoom-value">{{ Math.round(camera.zoom * 100) }}%</span>
        <button type="button" aria-label="放大岩板" :disabled="camera.zoom >= 8" @click="zoomAt(1.3)"><ZoomIn /></button>
        <button type="button" @click="resetCamera">看全板</button>
      </div>
    </div>
    <div ref="viewport" class="photo-wall-viewport" :class="{ 'is-browsing': mode === 'browse' }" :style="viewportStyle"
      :aria-label="`${PHOTO_BOARD.columns}列${PHOTO_BOARD.rows}行抱石线路电子岩板，可缩放和平移`" @wheel.prevent="wheel"
      @pointerdown="pointerDown" @pointermove="pointerMove" @pointerup="pointerUp" @pointercancel="pointerUp"
      @lostpointercapture="pointerUp">
      <svg class="photo-technical-wall" :style="wallStyle" :viewBox="`0 0 ${PHOTO_BOARD.board_width_mm} ${PHOTO_BOARD.board_height_mm}`" :aria-label="`${PHOTO_BOARD.columns}列${PHOTO_BOARD.rows}行中性灰技术岩板`">
        <g class="photo-panel-joints" aria-hidden="true">
          <line v-for="part in 4" :key="`vertical-${part}`" :x1="PHOTO_BOARD.board_width_mm*part/5" :x2="PHOTO_BOARD.board_width_mm*part/5" y1="0" :y2="PHOTO_BOARD.board_height_mm" />
          <line v-for="part in 2" :key="`horizontal-${part}`" x1="0" :x2="PHOTO_BOARD.board_width_mm" :y1="PHOTO_BOARD.board_height_mm*part/3" :y2="PHOTO_BOARD.board_height_mm*part/3" />
        </g>
        <g class="photo-reference-holes" aria-hidden="true">
          <circle v-for="hole in holes" :key="hole.id" :cx="hole.x" :cy="PHOTO_BOARD.board_height_mm-hole.y" r="9"><title>{{ hole.id }}</title></circle>
        </g>
        <g v-if="snapPreview" class="photo-snap-preview" aria-hidden="true">
          <circle :cx="snapPreview.x" :cy="PHOTO_BOARD.board_height_mm-snapPreview.y" r="42" />
          <line :x1="snapPreview.fromX" :y1="PHOTO_BOARD.board_height_mm-snapPreview.fromY" :x2="snapPreview.x" :y2="PHOTO_BOARD.board_height_mm-snapPreview.y" />
        </g>
        <g v-if="labels" class="photo-axis-labels" aria-hidden="true">
          <text v-for="i in PHOTO_BOARD.columns" :key="`x${i}`" :x="PHOTO_BOARD.margin_left_mm+(i-1)*PHOTO_BOARD.hole_spacing_x_mm" :y="PHOTO_BOARD.board_height_mm-30" text-anchor="middle">{{ columnLabel(i-1) }}</text>
          <text v-for="i in PHOTO_BOARD.rows" :key="`y${i}`" x="60" :y="PHOTO_BOARD.board_height_mm-(PHOTO_BOARD.margin_bottom_mm+(i-1)*PHOTO_BOARD.hole_spacing_y_mm)+15" text-anchor="middle">{{ i }}</text>
        </g>
        <g v-if="axisModel.axis" class="photo-reference-axis" aria-hidden="true">
          <rect class="photo-axis-side photo-axis-side--left" x="0" y="0" :width="axisModel.axis.x-axisModel.axis.laneHalfWidth" :height="PHOTO_BOARD.board_height_mm" />
          <rect class="photo-axis-side photo-axis-side--right" :x="axisModel.axis.x+axisModel.axis.laneHalfWidth" y="0" :width="PHOTO_BOARD.board_width_mm-axisModel.axis.x-axisModel.axis.laneHalfWidth" :height="PHOTO_BOARD.board_height_mm" />
          <line class="photo-axis-lane" :x1="axisModel.axis.x" :y1="PHOTO_BOARD.margin_top_mm" :x2="axisModel.axis.x" :y2="PHOTO_BOARD.board_height_mm-PHOTO_BOARD.margin_bottom_mm" />
          <circle v-for="row in PHOTO_BOARD.rows" :key="`axis-hole-${row}`" :cx="axisModel.axis.x" :cy="PHOTO_BOARD.board_height_mm-(PHOTO_BOARD.margin_bottom_mm+(row-1)*PHOTO_BOARD.hole_spacing_y_mm)" r="17" />
          <g class="photo-axis-label" :transform="`translate(${axisModel.axis.x} 72)`">
            <rect x="-132" y="-48" width="264" height="62" rx="12" />
            <text x="0" y="-5" text-anchor="middle">中轴 {{ axisModel.axis.label }} 列</text>
          </g>
          <text class="photo-axis-side-label" :x="Math.max(180,(axisModel.axis.x-axisModel.axis.laneHalfWidth)/2)" y="164" text-anchor="middle">左侧独立校准</text>
          <text class="photo-axis-side-label" :x="axisModel.axis.x+axisModel.axis.laneHalfWidth+(PHOTO_BOARD.board_width_mm-axisModel.axis.x-axisModel.axis.laneHalfWidth)/2" y="164" text-anchor="middle">右侧独立校准</text>
        </g>
        <g v-for="point in layoutPoints" :key="`guide-${point.id}`" class="photo-alignment-guide"
          :class="{ 'is-visible': labels || selectedId === point.id, 'is-confirmed': point.anchored }" aria-hidden="true">
          <line v-if="point.target && point.residual > 2" :x1="point.x" :y1="PHOTO_BOARD.board_height_mm-point.y" :x2="point.target.x" :y2="PHOTO_BOARD.board_height_mm-point.target.y" />
          <circle v-if="point.target" :cx="point.target.x" :cy="PHOTO_BOARD.board_height_mm-point.target.y" r="24" />
        </g>
        <g v-for="object in sortedObjects" :key="object.id" :data-object-id="object.id"
          :transform="objectTransform(object)"
          class="photo-wall-object" :class="{ 'is-selected': selectedId === object.id || groupSelected, 'is-anchored': installationPoint(object).anchored, 'is-suggested': installationPoint(object).suggested }"
          role="button" tabindex="0" :aria-label="objectLabel(object)" :aria-pressed="selectedId === object.id"
          @keydown="objectKey($event, object.id)">
          <image :href="resolveAsset(object.cutout)" :x="-objectWidth(object)/2" :y="-objectHeight(object)/2"
            :width="objectWidth(object)" :height="objectHeight(object)" draggable="false" />
          <g class="photo-install-pin" :class="{ 'is-visible': labels || selectedId === object.id || groupSelected, 'is-suggested': installationPoint(object).suggested }" aria-hidden="true">
            <circle class="photo-install-pin-ring" r="27" />
            <circle class="photo-install-pin-core" r="9" />
            <line x1="-19" y1="0" x2="19" y2="0" />
            <line x1="0" y1="-19" x2="0" y2="19" />
          </g>
          <rect v-if="object.route_color" class="photo-route-outline" :style="{ stroke:object.route_color }"
            :x="-objectWidth(object)/2-12" :y="-objectHeight(object)/2-12" :width="objectWidth(object)+24" :height="objectHeight(object)+24"><title>{{ object.route_name }}</title></rect>
          <rect v-if="selectedId === object.id || groupSelected" class="photo-object-selection"
            :x="-objectWidth(object)/2-8" :y="-objectHeight(object)/2-8" :width="objectWidth(object)+16" :height="objectHeight(object)+16" />
          <g v-if="object.roles.length" class="photo-role-marker" :transform="`translate(${-objectWidth(object)/2} ${-objectHeight(object)/2})`">
            <rect x="-18" y="-68" :width="object.roles.length * 84" height="72" rx="10" />
            <text x="-5" y="-15">{{ object.roles.map(role => role === 'start' ? '起' : '终').join(' ') }}</text>
          </g>
          <g v-if="labels || selectedId === object.id" class="photo-hole-id" aria-hidden="true" :transform="`translate(${Math.min(objectWidth(object)/2 + 24, 210)} ${Math.min(objectHeight(object)/2 + 38, 150)})`">
            <rect x="-9" y="-46" :width="installationLabel(object).length * 31 + 34" height="58" rx="12" />
            <text x="8" y="-6">{{ installationLabel(object) }}</text>
          </g>
        </g>
      </svg>
    </div>
    <div class="photo-canvas-caption"><span>{{ mode === 'browse' ? '拖动画布 · 双指或滚轮缩放' : groupSelected ? '拖动任一对象可移动整条线路' : '拖动一个参考岩点 · 方向键微调' }}</span><span>{{ mode === 'edit' && snapping ? '相对关系锁定 · 用参考点整体校准' : '相对关系锁定 · 整体贴合孔阵' }}</span></div>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { ZoomIn, ZoomOut } from '@element-plus/icons-vue'
import { PHOTO_BOARD, calibratedObjectSize, photoHoles, columnLabel, objectInstallationPoint, photoRouteAxisLayout, zoomCamera } from '../utils/photoBoard.js'
import { photoAssetUrl } from '../services/photoRouteService'

const props = defineProps({ objects: { type: Array, required: true }, selectedId: { type: String, default: '' }, groupSelected: Boolean, mode: { type: String, default: 'browse' }, editable: Boolean, snapping: Boolean, snapPreview: { type: Object, default: null }, calibrationMatrix: { type: Array, default: null }, assetUrl: { type: Function, default: photoAssetUrl } })
const emit = defineEmits(['select', 'begin', 'move', 'end', 'nudge'])
const viewport = ref(null), labels = ref(false)
const camera = reactive({ zoom: 1, x: 0, y: 0 }), size = reactive({ width: 1, height: 1 })
const holes = photoHoles()
const sortedObjects = computed(() => [...props.objects].sort((a, b) => a.z_index - b.z_index))
const axisModel = computed(() => photoRouteAxisLayout(props.objects, props.calibrationMatrix))
const layoutPoints = computed(() => axisModel.value.points)
const layoutById = computed(() => new Map(layoutPoints.value.map(point => [point.id, point])))
const baseWidth = computed(() => Math.min(size.width, size.height * PHOTO_BOARD.board_width_mm / PHOTO_BOARD.board_height_mm))
const viewportStyle = computed(() => ({ aspectRatio: `${PHOTO_BOARD.board_width_mm} / ${PHOTO_BOARD.board_height_mm}` }))
const wallStyle = computed(() => ({ width: `${baseWidth.value}px`, height: `${baseWidth.value * PHOTO_BOARD.board_height_mm / PHOTO_BOARD.board_width_mm}px`, transform: `translate(-50%, -50%) translate(${camera.x}px, ${camera.y}px) scale(${camera.zoom})` }))
const calibratedSize = (object) => calibratedObjectSize(object, props.calibrationMatrix)
const objectWidth = (object) => calibratedSize(object)?.width || object.source_bbox_px[2] * object.scale_mm_per_px
const objectHeight = (object) => calibratedSize(object)?.height || object.source_bbox_px[3] * object.scale_mm_per_px
const installationPoint = (object) => layoutById.value.get(object.id) || objectInstallationPoint(object)
const objectTransform = (object) => {
  const point = installationPoint(object)
  return `translate(${point.x} ${PHOTO_BOARD.board_height_mm-point.y}) rotate(${object.rotation_deg})`
}
const installationLabel = (object) => {
  const point = installationPoint(object)
  return point.label ? `${point.label}${point.anchored ? '' : '?'}` : '待确认'
}
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
  --photo-axis-color: #2563eb;
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

.photo-reference-axis {
  pointer-events: none;
}

.photo-axis-side {
  opacity: .045;
}

.photo-axis-side--left {
  fill: var(--ui-warning);
}

.photo-axis-side--right {
  fill: var(--photo-axis-color);
}

.photo-axis-lane {
  stroke: var(--photo-axis-color);
  stroke-width: 10;
  stroke-dasharray: 34 22;
}

.photo-reference-axis > circle {
  fill: var(--ui-board-face);
  stroke: var(--photo-axis-color);
  stroke-width: 8;
}

.photo-axis-label rect {
  fill: var(--photo-axis-color);
}

.photo-axis-label text {
  fill: var(--ui-brand-ink);
  font-size: 38px;
  font-weight: 700;
}

.photo-axis-side-label {
  fill: var(--ui-ink-muted);
  font-size: 34px;
  font-weight: 700;
}

.photo-wall-object {
  cursor: pointer;
  outline: none;
}

.photo-wall-object image {
  pointer-events: all;
}

.photo-install-pin {
  opacity: .42;
  pointer-events: none;
  transition: opacity 160ms ease-out;
}

.photo-alignment-guide {
  opacity: 0;
  pointer-events: none;
  transition: opacity 160ms ease-out;
}

.photo-alignment-guide.is-visible {
  opacity: 1;
}

.photo-alignment-guide line {
  stroke: var(--ui-warning);
  stroke-width: 5;
  stroke-dasharray: 18 12;
}

.photo-alignment-guide circle {
  fill: none;
  stroke: var(--ui-warning);
  stroke-width: 6;
  stroke-dasharray: 12 8;
}

.photo-alignment-guide.is-confirmed line,
.photo-alignment-guide.is-confirmed circle {
  stroke: var(--ui-success);
  stroke-dasharray: none;
}

.photo-install-pin.is-visible,
.photo-wall-object.is-selected .photo-install-pin {
  opacity: 1;
}

.photo-install-pin-ring {
  fill: rgba(255, 255, 255, .86);
  stroke: var(--ui-board-hole);
  stroke-width: 7;
}

.photo-install-pin.is-suggested .photo-install-pin-ring {
  stroke: var(--ui-warning);
  stroke-dasharray: 12 8;
}

.photo-install-pin-core {
  fill: var(--ui-brand);
  stroke: var(--ui-board-face);
  stroke-width: 4;
}

.photo-install-pin line {
  stroke: var(--ui-board-hole);
  stroke-width: 3;
}

.photo-hole-id {
  pointer-events: none;
}

.photo-hole-id rect {
  fill: rgba(255, 255, 255, .94);
  stroke: var(--ui-board-grid);
  stroke-width: 3;
}

.photo-hole-id text {
  fill: var(--ui-ink);
  font-size: 38px;
  font-weight: 700;
  font-variant-numeric: tabular-nums;
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
