<template>
  <div ref="stage" class="replay-cinema" :class="{ 'showing-summary': summary }" :style="stageStyle">
    <div class="picture-area">
    <div class="replay-frame" :style="frameStyle">
      <video ref="video" :src="src" :controls="!frame" :class="{ 'composite-source': frame }" playsinline preload="metadata" aria-label="攀爬复盘视频"
        @timeupdate="updateTime" @seeking="$emit('seeking')" @seeked="drawAndSeek" @ended="ended"
        @loadedmetadata="loaded" @loadeddata="draw" @play="playing" @pause="paused" @error="$emit('error')" />
      <canvas v-if="frame" ref="canvas" :width="frame.width" :height="frame.height" :aria-label="selection ? '所选复盘画面' : originalSource ? '左侧原视频，右侧岩点、骨架与中心移动路线' : '保留的历史复盘画面'" />
      <slot />
    </div>
    <aside v-if="$slots.tools" class="picture-tools"><slot name="tools" /></aside>
    </div>
    <div v-if="frame" class="media-controls">
      <button type="button" :aria-label="isPlaying ? '暂停复盘视频' : '播放复盘视频'" @click="togglePlay"><component :is="isPlaying ? VideoPause : VideoPlay" aria-hidden="true" /></button>
      <input type="range" min="0" :max="mediaDuration || 1" step=".01" :value="time" aria-label="复盘视频进度" @input="scrub" />
      <output>{{ clock(time) }} / {{ clock(mediaDuration) }}</output>
      <button type="button" aria-label="全屏复盘" @click="fullscreen"><FullScreen aria-hidden="true" /></button>
    </div>
  </div>
</template>
<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { VideoPlay, VideoPause, FullScreen } from '@element-plus/icons-vue'
import { drawAnalysisView } from '../services/replayAnalysisView.js'
const props = defineProps({ src: String, summary: Boolean, expandedSummary: Boolean, frame: Object, originalSource:Boolean, visualization:Object, selection:Object, backgroundUrl:String, backgroundInfo:Object, holds: { type: Array, default: () => [] }, contacts: { type: Array, default: () => [] } })
const emit = defineEmits(['timeupdate','seeking','seeked','ended','loadedmetadata','play','pause','error','fullscreen','background-error','background-ready'])
const video = ref(null), canvas = ref(null), stage = ref(null), isPlaying = ref(false), time = ref(0), mediaDuration = ref(0)
let animation
let resizeObserver
let background = null, backgroundGeneration = 0
watch(()=>props.backgroundUrl, url=>{
  const token=++backgroundGeneration
  background=null
  if(!url){draw();return}
  const image=new Image()
  image.onload=()=>{if(token===backgroundGeneration){background=image;draw();emit('background-ready')}}
  image.onerror=()=>{if(token===backgroundGeneration){background=null;draw();emit('background-error')}}
  image.src=url
},{immediate:true})
const availableHeight = ref(null)
const stageStyle = computed(() => ({ '--frame-limit': availableHeight.value ? `${availableHeight.value}px` : 'calc(100dvh - 200px)', '--frame-ratio': props.frame ? props.frame.width / props.frame.height : 2 }))
function fitViewport() {
  if (!stage.value) return
  const viewport = window.visualViewport?.height || window.innerHeight
  const top = Math.max(0, stage.value.getBoundingClientRect().top - (window.visualViewport?.offsetTop || 0))
  const view = stage.value.closest('.replay-view')
  const reserved = ['.action-strip','.replay-controls','.picture-choices'].reduce((total,selector)=>total+(view?.querySelector(selector)?.getBoundingClientRect().height || 0),0)
  availableHeight.value = Math.floor(Math.max(80, viewport - top - reserved - 60))
}
const frameStyle = computed(() => props.frame ? { aspectRatio: `${props.frame.width} / ${props.frame.height}`, '--frame-ratio': props.frame.width / props.frame.height } : {})
const clock = value => `${Math.floor(value / 60)}:${Math.floor(value % 60).toString().padStart(2,'0')}`
function draw() {
  if (!canvas.value || !props.frame || !video.value || video.value.readyState < 2) return
  const ctx = canvas.value.getContext('2d'), f = props.frame
  if(props.originalSource){drawAnalysisView(ctx,video.value,f,props.holds,props.contacts,props.visualization,video.value.currentTime,props.selection,background,props.backgroundInfo);return}
  ctx.fillStyle = '#0e100f'; ctx.fillRect(0,0,f.width,f.height)
  ctx.drawImage(video.value, ...f.oldVideo, ...f.video)
  // Rebuild the fixed map from saved real contours. Old baked narrow maps
  // cannot be stretched without distorting their relationship to the person.
  ctx.save(); ctx.beginPath(); ctx.rect(...f.panel); ctx.clip()
  const colors = { left_hand: '#51c4e7', right_hand: '#e96fb6', left_foot: '#e7b16c', right_foot: '#8acc65' }
  const sourceFrame = video.value.currentTime * (f.source.fps || 30)
  for (const hold of props.holds) {
    if (!hold.polygon?.length || hold.polygon.length < 3) continue
    const active = props.contacts.find(c => colors[c.limb] && String(c.hold_id) === String(hold.id)
      && Number.isFinite(c.start_source_frame) && Number.isFinite(c.end_source_frame)
      && c.start_source_frame <= sourceFrame && sourceFrame <= c.end_source_frame)
    ctx.beginPath()
    hold.polygon.forEach(([x,y],i) => ctx[i ? 'lineTo' : 'moveTo'](f.map[0]+x*f.map[2], f.map[1]+y*f.map[3]))
    ctx.closePath(); ctx.strokeStyle = colors[active?.limb] || '#818780'; ctx.lineWidth = Math.max(2,f.source.width/240)
    if (active) { ctx.fillStyle = ctx.strokeStyle; ctx.fill() }
    ctx.stroke()
  }
  ctx.fillStyle = '#e9ece9'; ctx.font = `${Math.max(16,f.source.width/35)}px MiSans, sans-serif`
  ctx.fillText('线路动作图', f.panel[0]+18, 32)
  ctx.restore()
}
function loopDraw() { draw(); if (!video.value?.paused) animation = requestAnimationFrame(loopDraw) }
function playing() { isPlaying.value = true; cancelAnimationFrame(animation); loopDraw(); emit('play') }
function paused() { isPlaying.value = false; cancelAnimationFrame(animation); draw(); emit('pause') }
function updateTime() { time.value = video.value?.currentTime || 0; draw(); emit('timeupdate') }
function drawAndSeek() { updateTime(); emit('seeked') }
function loaded() { mediaDuration.value = Number.isFinite(video.value?.duration) ? video.value.duration : 0; fitViewport(); draw(); emit('loadedmetadata') }
function ended() { isPlaying.value = false; draw(); emit('ended') }
function togglePlay() { if (video.value.paused) video.value.play().catch(() => {}); else video.value.pause() }
function scrub(event) { video.value.currentTime = Number(event.target.value) }
function fullscreen() { emit('fullscreen') }
watch(() => [props.frame, props.src], async () => { await nextTick(); fitViewport(); draw() })
watch(() => [props.visualization,props.contacts,props.holds,props.selection], draw, {deep:true})
onMounted(() => {
  fitViewport()
  resizeObserver = new ResizeObserver(fitViewport)
  resizeObserver.observe(stage.value)
  const view = stage.value.closest('.replay-view')
  if(view) resizeObserver.observe(view)
  window.addEventListener('resize', fitViewport)
  window.visualViewport?.addEventListener('resize', fitViewport)
  document.addEventListener('fullscreenchange', fitViewport)
})
onBeforeUnmount(() => {
  cancelAnimationFrame(animation); resizeObserver?.disconnect()
  window.removeEventListener('resize', fitViewport)
  window.visualViewport?.removeEventListener('resize', fitViewport)
  document.removeEventListener('fullscreenchange', fitViewport)
})
defineExpose({ video })
</script>
<style scoped>
.replay-cinema{position:relative;background:#0e100f;display:flex;flex-direction:column;align-items:center;width:100%}
.picture-area{position:relative;display:flex;align-items:center;justify-content:center;width:100%;min-width:0}
.picture-tools{width:56px;flex:none;align-self:stretch;display:flex;align-items:flex-start;justify-content:center;padding-top:12px;box-sizing:border-box;background:#0e100f}
.picture-area:has(.picture-tools)>.replay-frame{width:calc(100% - 56px)}
.replay-frame{position:relative;width:100%;max-width:calc(var(--frame-limit) * var(--frame-ratio,2));overflow:hidden;flex:none}
video{display:block;width:100%;max-height:var(--frame-limit,72vh);object-fit:contain;transition:filter .3s ease-out}
video.composite-source{position:absolute;width:1px;height:1px;opacity:0;pointer-events:none}
canvas{display:block;width:100%;height:100%;transition:filter .3s ease-out}
.showing-summary :is(canvas,video:not(.composite-source)){filter:blur(12px) brightness(.35)}
.media-controls{display:flex;align-items:center;gap:12px;min-height:44px;width:100%;max-width:calc(var(--frame-limit) * var(--frame-ratio,2));padding:0 12px;box-sizing:border-box;color:#f2f2f2;background:#181a1b}
.media-controls button{display:grid;place-items:center;width:44px;height:44px;flex:none;background:transparent;border:0;color:inherit;cursor:pointer}.media-controls svg{width:20px;height:20px}
.media-controls input{flex:1;min-width:24px;accent-color:#edcb52;cursor:pointer}.media-controls output{font-size:12px;font-variant-numeric:tabular-nums;white-space:nowrap}
.media-controls button:hover{background:#303333}.media-controls :focus-visible{outline:2px solid #edcb52;outline-offset:-2px}
.replay-cinema:fullscreen{justify-content:center}.replay-cinema:fullscreen :is(.replay-frame,.media-controls){max-width:calc((100dvh - 44px) * var(--frame-ratio, 2))}
@media(max-width:650px){.media-controls{gap:4px;padding:0 4px}.media-controls output{font-size:11px}}
@media(prefers-reduced-motion:reduce){video,canvas{transition:none}}
</style>
