<template>
  <div class="canvas-wrap">
    <div class="board-frame" :style="frameStyle">
      <div class="dimension-label dimension-label-top">宽 {{ boardSpec.board_width_mm }}mm</div>
      <div class="dimension-label dimension-label-side">高 {{ boardSpec.board_height_mm }}mm</div>
      <div class="dimension-label dimension-label-spacing">孔距 {{ boardSpec.hole_spacing_x_mm }}mm</div>
      <div class="axis axis-x">
        <span v-for="column in columns" :key="column">{{ column }}</span>
      </div>
      <div class="axis axis-y">
        <span v-for="row in rows" :key="row">{{ row }}</span>
      </div>

      <button
        v-for="coord in coords"
        :key="coord"
        type="button"
        class="board-hole"
        :class="{ 'is-readonly': readonly }"
        :style="getCoordStyle(coord)"
        :title="coord"
        :aria-label="readonly ? `查看孔位 ${coord}` : `在 ${coord} 放置岩点`"
        :disabled="readonly"
        :tabindex="readonly ? -1 : 0"
        @click="handlePlace(coord)"
      />

      <button
        v-for="hold in visibleBaseHolds"
        :key="`setup-${hold.id}`"
        type="button"
        class="placed-hold setup-hold"
        :class="{ ...setupClass(hold), 'is-readonly': readonly }"
        :style="{ ...getCoordStyle(hold.id), transform: `translate(-50%, 50%) rotate(${hold.rotation || 0}deg) scale(${hold.scale || 1})` }"
        :title="setupTitle(hold)"
        :aria-label="readonly ? `查看${setupTitle(hold)}` : setupTitle(hold)"
        :disabled="readonly"
        :tabindex="readonly ? -1 : 0"
        @click.stop="handleSelect(hold)"
      >
        <img v-if="visualFor(hold).imageUrl" :src="visualFor(hold).imageUrl" alt="" />
        <svg v-else-if="visualFor(hold).svgPath" viewBox="0 0 100 100" aria-hidden="true">
          <path :d="visualFor(hold).svgPath" :fill="shapeColor(hold.hold_type || hold.type)" />
        </svg>
        <span v-else :class="['hold-shape', (hold.hold_type || hold.type || 'Jug').toLowerCase()]" />
      </button>

      <button
        v-if="!baseHolds.length"
        v-for="hold in holds"
        :key="hold.id"
        type="button"
        class="placed-hold"
        :class="{
          selected: selectedHold?.id === hold.id,
          start: hold.is_start,
          top: isTop(hold.id),
          'is-readonly': readonly,
          [`comparison-${comparisonStatus(hold)}`]: Boolean(comparisonStatus(hold)),
        }"
        :style="{ ...getCoordStyle(hold.id), transform: `translate(-50%, 50%) rotate(${hold.rotation || 0}deg) scale(${hold.scale || 1})` }"
        :title="hold.id"
        :aria-label="holdAriaLabel(hold)"
        :disabled="readonly"
        :tabindex="readonly ? -1 : 0"
        @click.stop="handleSelect(hold)"
      >
        <img v-if="visualFor(hold).imageUrl" :src="visualFor(hold).imageUrl" alt="" />
        <svg v-else-if="visualFor(hold).svgPath" viewBox="0 0 100 100" aria-hidden="true">
          <path :d="visualFor(hold).svgPath" :fill="shapeColor(hold.hold_type || hold.type)" />
        </svg>
        <span v-else :class="['hold-shape', (hold.hold_type || hold.type || 'Jug').toLowerCase()]" />
        <span v-if="comparisonBadge(hold)" class="comparison-marker-badge">{{ comparisonBadge(hold) }}</span>
        <span v-if="showBetaSteps && betaNumbers(hold.id)" class="beta-step-badge">{{ betaNumbers(hold.id) }}</span>
      </button>

      <svg
        v-if="skeletonFrame?.joints"
        class="skeleton-overlay"
        :viewBox="`0 0 ${boardSpec.board_width_mm} ${boardSpec.board_height_mm}`"
        preserveAspectRatio="none"
        aria-label="虚拟攀爬者极简火柴人姿态"
      >
        <g class="skeleton-links">
          <line v-for="segment in skeletonSegments" :key="segment.key" :class="segment.className" :x1="segment.a.x" :y1="segment.a.y" :x2="segment.b.x" :y2="segment.b.y" />
        </g>
        <g class="skeleton-joints">
          <circle
            v-for="joint in skeletonPoints"
            :key="joint.key"
            :class="joint.className"
            :data-joint="joint.key"
            :cx="joint.x"
            :cy="joint.y"
            :r="joint.head ? 32 : 20"
          />
        </g>
        <g v-if="skeletonCenter" class="skeleton-com">
          <circle :cx="skeletonCenter.x" :cy="skeletonCenter.y" r="18" />
        </g>
      </svg>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  columns: { type: Array, required: true },
  rows: { type: Array, required: true },
  baseHolds: { type: Array, default: () => [] },
  routeOverlay: { type: Array, default: () => [] },
  holds: { type: Array, default: () => [] },
  routeSteps: { type: Array, default: () => [] },
  selectedHold: { type: Object, default: null },
  boardSpec: { type: Object, required: true },
  frameStyle: { type: Object, default: () => ({}) },
  getCoordStyle: { type: Function, required: true },
  resolveHoldVisual: { type: Function, required: true },
  skeletonFrame: { type: Object, default: null },
  readonly: { type: Boolean, default: false },
  comparisonStatusById: { type: Object, default: () => ({}) },
  showBetaSteps: { type: Boolean, default: false },
  showNonRouteHolds: { type: Boolean, default: true },
})

const emit = defineEmits(['place', 'select'])

const coords = computed(() => props.rows.flatMap((row) => props.columns.map((column) => `${column}${row}`)))
const overlayByCoord = computed(() => {
  const map = new Map()
  props.routeOverlay.forEach((point) => map.set(point.coord_id, point))
  return map
})
const visibleBaseHolds = computed(() => {
  if (props.showNonRouteHolds) return props.baseHolds
  return props.baseHolds.filter((hold) => overlayByCoord.value.has(hold.id))
})
const betaNumbersByHold = computed(() => {
  const numbers = new Map()
  props.routeSteps.forEach((step, index) => {
    const current = numbers.get(step.hold_id) || []
    current.push(Number.isFinite(Number(step.step)) ? Number(step.step) : index + 1)
    numbers.set(step.hold_id, current)
  })
  return numbers
})
const skeletonConnections = [
  ['head', 'shoulder_center'],
  ['shoulder_center', 'pelvis'],
  ['left_shoulder', 'left_elbow'],
  ['left_elbow', 'left_hand'],
  ['right_shoulder', 'right_elbow'],
  ['right_elbow', 'right_hand'],
  ['left_hip', 'left_knee'],
  ['left_knee', 'left_foot'],
  ['right_hip', 'right_knee'],
  ['right_knee', 'right_foot'],
]
const endpointByLimb = {
  lh: 'left_hand',
  rh: 'right_hand',
  lf: 'left_foot',
  rf: 'right_foot',
}
const skeletonJoints = computed(() => {
  const joints = { ...(props.skeletonFrame?.joints || {}) }
  for (const [limb, holdId] of Object.entries(props.skeletonFrame?.contacts || {})) {
    if (holdId && endpointByLimb[limb]) joints[endpointByLimb[limb]] = holdCenterPoint(holdId)
  }
  return joints
})
const visiblePoints = new Set(['head', 'left_hand', 'right_hand', 'left_foot', 'right_foot'])
const skeletonPoints = computed(() => Object.entries(skeletonJoints.value)
  .filter(([key]) => visiblePoints.has(key))
  .map(([key, point]) => ({
    key,
    ...toSvgPoint(point),
    head: key === 'head',
    className: isMovingJoint(key) ? 'is-moving' : '',
  })))
const skeletonSegments = computed(() => skeletonConnections.flatMap(([aKey, bKey]) => {
  const a = skeletonJoints.value[aKey]
  const b = skeletonJoints.value[bKey]
  return a && b ? [{
    key: `${aKey}-${bKey}`,
    a: toSvgPoint(a),
    b: toSvgPoint(b),
    className: isMovingJoint(aKey) || isMovingJoint(bKey) ? 'is-moving' : '',
  }] : []
}))
const skeletonCenter = computed(() => props.skeletonFrame?.center_of_mass ? toSvgPoint(props.skeletonFrame.center_of_mass) : null)

function isMovingJoint(key) {
  const moving = String(props.skeletonFrame?.moving_limb || '').toLowerCase()
  return ({
    lh: ['left_elbow', 'left_hand'],
    rh: ['right_elbow', 'right_hand'],
    lf: ['left_knee', 'left_foot'],
    rf: ['right_knee', 'right_foot'],
  }[moving] || []).includes(key)
}

function holdCenterPoint(coordId) {
  const match = String(coordId).match(/^([A-Z]+)(\d+)$/i) || []
  const column = Math.max(0, props.columns.indexOf((match[1] || 'A').toUpperCase()))
  const row = Math.max(1, Number(match[2] || 1))
  return {
    x: (column * props.boardSpec.hole_spacing_x_mm) / 1000,
    y: ((row - 1) * props.boardSpec.hole_spacing_y_mm) / 1000,
    z: 0,
  }
}

function toSvgPoint(point) {
  const xMm = (props.boardSpec.margin_left_mm || 0) + Number(point.x || 0) * 1000
  const yMm = (props.boardSpec.margin_bottom_mm || 0) + Number(point.y || 0) * 1000
  return {
    x: xMm,
    y: props.boardSpec.board_height_mm - yMm,
  }
}

function isTop(id) {
  return props.routeSteps.some((step) => step.hold_id === id && step.is_top)
}

function handlePlace(coord) {
  if (!props.readonly) emit('place', coord)
}

function handleSelect(hold) {
  if (!props.readonly) emit('select', hold)
}

function comparisonStatus(hold) {
  return props.comparisonStatusById[hold.id] || ''
}

function comparisonBadge(hold) {
  return {
    added: '新',
    removed: '移',
    changed: '改',
  }[comparisonStatus(hold)] || ''
}

function comparisonLabel(hold) {
  return {
    retained: '，与基准相同',
    added: '，相对基准新增',
    removed: '，相对基准移除',
    changed: '，相对基准已修改',
  }[comparisonStatus(hold)] || ''
}

function betaNumbers(id) {
  return (betaNumbersByHold.value.get(id) || []).join('·')
}

function holdAriaLabel(hold) {
  const action = props.readonly ? '查看' : '选择'
  const beta = props.showBetaSteps && betaNumbers(hold.id) ? `，Beta 第 ${betaNumbers(hold.id)} 步` : ''
  return `${action}岩点 ${hold.id}，${hold.hold_type || hold.type || '岩点'}${hold.is_start ? '，起点' : ''}${isTop(hold.id) ? '，终点' : ''}${comparisonLabel(hold)}${beta}`
}

function setupClass(hold) {
  const overlay = overlayFor(hold)
  return {
    lit: Boolean(overlay),
    start: overlay?.role === 'start',
    startHand: overlay?.role === 'start_hand',
    startFoot: overlay?.role === 'start_foot',
    mid: overlay?.role === 'mid',
    top: overlay?.role === 'end',
  }
}

function setupTitle(hold) {
  const overlay = overlayFor(hold)
  const label = overlayRoleLabel(overlay?.role)
  return overlay ? `${hold.id} ${label} LED ${overlay.led_index}` : hold.id
}

function overlayFor(hold) {
  return overlayByCoord.value.get(hold.id)
}

function overlayRoleLabel(role) {
  return {
    start: '起点',
    start_hand: '起点手点',
    start_foot: '起点脚点',
    mid: '中间点',
    end: '终点',
  }[role] || '线路点'
}

function visualFor(hold) {
  const resolved = props.resolveHoldVisual(hold)
  return {
    svgPath: resolved.svgPath || hold.svgPath,
    imageUrl: resolved.imageUrl || hold.imageUrl,
  }
}

function shapeColor(type) {
  return { Jug: '#24876b', Crimp: '#d94b52', Sloper: '#c8912f', Pinch: '#7457d8', Pocket: '#2f72c8', Foot: '#718096' }[type] || '#24876b'
}
</script>
