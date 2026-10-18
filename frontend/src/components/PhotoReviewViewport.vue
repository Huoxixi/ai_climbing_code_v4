<template>
  <div class="photo-review-viewer">
    <div class="photo-review-viewer__tools" aria-label="照片缩放" title="触摸板双指或滚轮滑动查看 · 捏合或按钮缩放">
      <button type="button" :disabled="zoom <= 1" @click="scale(zoom / 1.25)">缩小</button>
      <output aria-label="照片缩放比例">{{ Math.round(zoom * 100) }}%</output>
      <button type="button" :disabled="zoom >= 8" @click="scale(zoom * 1.25)">放大</button>
      <button type="button" @click="reset">完整显示</button>
      <span>触摸板双指或滚轮滑动查看 · 捏合或按钮缩放</span>
    </div>
    <div ref="viewport" class="photo-review-viewer__viewport" :class="{ 'is-zoomed': zoom > 1 }" tabindex="0" aria-label="岩壁照片，可缩放和拖动"
      @wheel="wheel" @pointerdown="down" @pointermove="move" @pointerup="up" @pointercancel="up"
      @click.capture="click" @keydown="key">
      <div class="photo-review-viewer__image" :style="imageStyle"><slot /></div>
    </div>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { photoWheelGesture } from '../utils/photoViewportGesture.js'
const props = defineProps({ width: { type:Number, required:true }, height: { type:Number, required:true }, imageKey:String })
const viewport = ref(null), size = ref({ width:0, height:0 }), zoom = ref(1), offset = ref({ x:0, y:0 })
const fit = computed(() => Math.min(size.value.width / props.width, size.value.height / props.height))
const imageStyle = computed(() => ({ width:`${props.width * fit.value}px`, height:`${props.height * fit.value}px`, transform:`translate(${offset.value.x}px, ${offset.value.y}px) scale(${zoom.value})` }))
const pointers = new Map()
let observer, moved = false, start, pinchDistance = 0
function clamp() {
  const x = Math.max(0, (props.width * fit.value * zoom.value - size.value.width) / 2)
  const y = Math.max(0, (props.height * fit.value * zoom.value - size.value.height) / 2)
  offset.value = { x:Math.max(-x, Math.min(x, offset.value.x)), y:Math.max(-y, Math.min(y, offset.value.y)) }
}
function reset() { zoom.value = 1; offset.value = {x:0,y:0} }
function scale(value, anchor = {x:0,y:0}) {
  const next = Math.min(8, Math.max(1, value)), factor = next / zoom.value
  offset.value = { x:anchor.x - (anchor.x-offset.value.x)*factor, y:anchor.y - (anchor.y-offset.value.y)*factor }
  zoom.value = next; clamp()
}
function wheel(event) {
  const rect = viewport.value.getBoundingClientRect()
  const gesture = photoWheelGesture(event, zoom.value, rect.height)
  if (gesture.type === 'page') return
  if (gesture.type === 'zoom') {
    event.preventDefault()
    scale(zoom.value * gesture.factor, {x:event.clientX-rect.left-rect.width/2,y:event.clientY-rect.top-rect.height/2})
    return
  }
  const before = offset.value
  offset.value = {x:before.x+gesture.x,y:before.y+gesture.y}; clamp()
  if (offset.value.x !== before.x || offset.value.y !== before.y) event.preventDefault()
}
function down(event) {
  if (event.button !== 0) return
  if (!pointers.size) { moved = false; start = {x:event.clientX,y:event.clientY} }
  pointers.set(event.pointerId, {x:event.clientX,y:event.clientY})
  if (pointers.size === 2) { const [a,b] = [...pointers.values()]; pinchDistance = Math.hypot(a.x-b.x,a.y-b.y); moved = true }
}
function move(event) {
  const old = pointers.get(event.pointerId)
  if (!old) return
  pointers.set(event.pointerId, {x:event.clientX,y:event.clientY})
  if (pointers.size === 2) {
    const [a,b] = [...pointers.values()], distance = Math.hypot(a.x-b.x,a.y-b.y)
    if (pinchDistance > 0) scale(zoom.value * distance/pinchDistance)
    pinchDistance = distance; moved = true
  } else if (zoom.value > 1 && (moved || Math.hypot(event.clientX-start.x,event.clientY-start.y)>5)) {
    offset.value = {x:offset.value.x+event.clientX-old.x,y:offset.value.y+event.clientY-old.y}; clamp(); moved = true
  }
  if (moved) viewport.value.setPointerCapture(event.pointerId)
}
function up(event) { pointers.delete(event.pointerId); if (viewport.value.hasPointerCapture(event.pointerId)) viewport.value.releasePointerCapture(event.pointerId) }
function click(event) { if (moved) { event.preventDefault(); event.stopPropagation(); moved = false } }
function key(event) {
  if (event.target !== viewport.value) return
  if (['+','=','-','0','ArrowLeft','ArrowRight','ArrowUp','ArrowDown'].includes(event.key)) event.preventDefault()
  if (event.key === '+' || event.key === '=') scale(zoom.value*1.25)
  else if (event.key === '-') scale(zoom.value/1.25)
  else if (event.key === '0') reset()
  else if (event.key.startsWith('Arrow')) { offset.value = {x:offset.value.x + ({ArrowLeft:40,ArrowRight:-40}[event.key]||0),y:offset.value.y+({ArrowUp:40,ArrowDown:-40}[event.key]||0)}; clamp() }
}
watch(() => props.imageKey, reset)
onMounted(() => {
  observer = new ResizeObserver(([entry]) => { size.value = {width:entry.contentRect.width,height:entry.contentRect.height}; clamp() }); observer.observe(viewport.value)
  window.addEventListener('pointerup', up); window.addEventListener('pointercancel', up)
})
onBeforeUnmount(() => { observer?.disconnect(); window.removeEventListener('pointerup', up); window.removeEventListener('pointercancel', up) })
</script>

<style scoped>
.photo-review-viewer { min-height:0; display:flex; flex-direction:column; flex:1; }
.photo-review-viewer__tools { display:flex; align-items:center; flex-wrap:wrap; gap:8px; padding:8px 0; }
.photo-review-viewer__tools button { min-height:44px; padding:6px 12px; color:inherit; background:var(--surface, #fff); border:1px solid var(--line, #d2cdc3); border-radius:8px; cursor:pointer; }
.photo-review-viewer__tools button:disabled { opacity:.45; cursor:default; }
.photo-review-viewer__tools output { min-width:4ch; font-variant-numeric:tabular-nums; }
.photo-review-viewer__tools span { font-size:12px; }
.photo-review-viewer__viewport { flex:1; min-height:180px; position:relative; display:flex; align-items:center; justify-content:center; overflow:hidden; background:#e7e3da; touch-action:pan-y; user-select:none; cursor:grab; }
.photo-review-viewer__viewport.is-zoomed { touch-action:none; }
.photo-review-viewer__viewport:active { cursor:grabbing; }
.photo-review-viewer__image { flex:none; transform-origin:center; }
.photo-review-viewer__image :deep(img) { pointer-events:none; -webkit-user-drag:none; }
</style>
