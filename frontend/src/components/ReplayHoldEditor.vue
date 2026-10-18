<template>
  <section class="hold-editor" aria-label="单帧岩点精修">
    <div class="editor-heading"><h3>单帧精修</h3><button type="button" :disabled="saving" @click="close">关闭精修</button></div>
    <div v-if="!props.stillImage" class="editor-frame-controls">
      <button type="button" :disabled="busy || !frame || frame.frame_index <= 0" @click="step(-1)">上一帧</button>
      <label>画面时间 <input v-model.number="requestedTime" type="number" min="0" :max="duration" step="0.01" /></label>
      <button type="button" :disabled="busy" @click="loadFrame()">读取画面</button>
      <button type="button" :disabled="busy || !frame || frame.frame_index >= frame.frame_count - 1" @click="step(1)">下一帧</button>
      <button type="button" :disabled="busy" @click="loadFrame(referenceTime)">回参考帧</button>
    </div>
    <p v-if="loading" role="status">正在读取清晰单帧…</p>
    <template v-if="frame">
<div class="editor-layout"><div class="editor-media">      <p class="editor-frame-caption">{{ frame.width }} × {{ frame.height }} · {{ frame.quality }} · 第 {{ frame.frame_index + 1 }} 帧 · {{ frame.time_seconds.toFixed(3) }} 秒</p>
      <p v-if="!frame.aligned" class="editor-error" role="alert">当前帧无法对齐墙面。可保留描边，或回参考帧重新描画；未对齐的轮廓不能保存。</p>
      <p class="editor-hint">{{ hint }}</p>
      <div v-if="zoom > 1" class="editor-overview">
        <button type="button" aria-label="点击整帧缩略图定位放大区域" @click="locate"><img :src="frame.image_data_url" alt="整帧定位缩略图" /></button>
        <span>点击整帧定位放大区域</span>
      </div>
      <div ref="viewport" class="editor-viewport" :data-zoom-animating="zoomAnimating" @wheel.ctrl.prevent="wheel" @keydown.esc.prevent="cancelGesture">
        <div class="editor-image" :style="frameStyle">
          <img :src="frame.image_data_url" alt="当前待编辑视频帧" draggable="false" />
          <svg ref="surface" :viewBox="`0 0 ${frame.width} ${frame.height}`" preserveAspectRatio="xMidYMid meet" tabindex="0" role="application" aria-label="岩点轮廓画布"
            :class="`tool-${tool}`" @pointerdown="start" @pointermove="move" @pointerup="end" @pointercancel="cancelGesture" >
            <polygon v-for="hold in frame.holds" :key="hold.id" :points="svgPoints(hold.polygon)" class="existing-contour" :class="{ selected:hold.id === editHoldId }" />
            <polygon v-if="closed && polygon.length" :points="svgPoints(polygon)" class="edited-contour" />
            <polyline v-else :points="svgPoints(polygon)" class="open-contour" />
            <polyline v-if="stroke.length" :points="svgPoints(stroke)" class="brush-preview" :style="{ strokeWidth:tool === 'lines' ? 2 / displayZoom : brushSize }" />
          </svg>
        </div>
      </div>
</div><TaskPanel class="editor-inspector" title="轮廓工具">      <div class="editor-tools" aria-label="轮廓工具">
        <button v-for="item in tools" :key="item.id" type="button" :aria-pressed="tool === item.id" :disabled="busy" @click="setTool(item.id)">{{ item.label }}</button>
        <label>笔宽 <input v-model.number="brushSize" type="range" min="2" max="60" aria-label="画笔原帧像素宽度" /><span>{{ brushSize }} px</span></label>
      </div>
      <div class="editor-view-controls">
        <label>放大 <select v-model.number="zoom" aria-label="单帧放大倍数"><option v-for="n in [1, 2, 4, 8]" :key="n" :value="n">{{ n === 1 ? '适合窗口' : `${n}×` }}</option></select></label>
        <button type="button" :disabled="busy || !history.length" @click="undo">撤销</button>
        <button type="button" :disabled="busy || !future.length" @click="redo">重做</button>
        <button type="button" :disabled="busy || !polygon.length" @click="clear">清空轮廓</button>
      </div>
      <div class="editor-refine-controls">
        <label>已有岩点 <select v-model.number="editHoldId" aria-label="选择要修改轮廓的岩点" :disabled="busy" @change="selectHold">
          <option :value="0">新增岩点</option><option v-for="hold in frame.holds" :key="hold.id" :value="hold.id">岩点 {{ hold.id }}</option>
        </select></label>
      </div>
      <div v-if="candidates.length > 1" class="editor-candidates" aria-label="局部岩点候选">
        <button v-for="(candidate, index) in candidates" :key="candidate.proposal_id" type="button" :aria-pressed="proposal?.proposal_id === candidate.proposal_id" @click="choose(candidate)">候选 {{ index + 1 }}</button>
      </div>
      <button v-if="working" type="button" @click="cancelRequest">取消本次请求</button>
      <template #footer><div class="editor-feedback" aria-live="polite" aria-atomic="true">
        <p v-if="error" class="editor-error" role="alert">{{ error }}</p>
        <p v-else-if="working">{{ saving ? '正在保存轮廓…' : '正在本地处理轮廓…' }}</p>
        <p v-else-if="notice">{{ notice }}</p>
      </div></template>
</TaskPanel></div>    </template>
    <p v-if="error && !frame" class="editor-error" role="alert">{{ error }}</p>
    <footer v-if="frame" class="editor-savebar" aria-label="轮廓保存">
      <span>{{ proposal?.touches_crop ? '轮廓贴近边缘，请核对。' : proposal ? '核对高亮轮廓后保存。' : '修改完成后，先核对轮廓。' }}</span>
      <button v-if="proposal" type="button" class="editor-save-action" :aria-label="editHoldId ? '确认保存轮廓修改' : '确认保存这个岩点'" :aria-busy="saving" :disabled="busy" @click="save"><Loading v-if="saving" class="is-loading" aria-hidden="true" /><Check v-else aria-hidden="true" />{{ saving ? '正在保存…' : '确认保存' }}</button>
      <button v-else type="button" class="editor-save-action" :disabled="busy || polygon.length < 3 || !closed || !frame.aligned" @click="previewManual">核对当前轮廓</button>
    </footer>
  </section>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch, nextTick } from 'vue'
import { Check, Loading } from '@element-plus/icons-vue'
import TaskPanel from './ui/TaskPanel.vue'
import replayService from '../services/climbReplayService'
import { imagePoint, contourFromBinary, simplifyContour } from '../services/holdEditorGeometry.js'
import { useSmoothNumber } from '../services/useSmoothNumber.js'
const props = defineProps({ job:Object, editorService:Object, stillImage:Boolean, initialTime:{ type:Number, default:0 }, initialHoldId:{ type:Number, default:0 }, initialPolygon:{ type:Array, default:()=>[] } })
const service = props.editorService || replayService
const emit = defineEmits(['saved', 'close', 'busy'])
const frame = ref(null), requestedTime = ref(props.initialTime), viewport = ref(null), surface = ref(null)
const polygon = ref([]), closed = ref(false), tool = ref('freehand'), zoom = ref(1), brushSize = ref(10)
const { visible:displayZoom, animating:zoomAnimating, reset:resetZoom } = useSmoothNumber(zoom)
const selectionMode = ref(false)
const history = ref([]), future = ref([]), stroke = ref([])
const candidates = ref([]), proposal = ref(null), editHoldId = ref(props.initialHoldId)
const loading = ref(false), working = ref(false), saving = ref(false), error = ref(''), notice = ref('')
const tools = [{ id:'freehand', label:'自由描边' }, { id:'lines', label:'画线圈选' }, { id:'brush', label:'补画' }, { id:'erase', label:'擦除' }, { id:'pan', label:'平移画面' }]
const canvasSize=ref({width:0,height:0})
const frameStyle=computed(()=>{if(!frame.value || !canvasSize.value.width)return {width:`${displayZoom.value*100}%`,aspectRatio:`${frame.value?.width || 1}/${frame.value?.height || 1}`};const scale=Math.min(canvasSize.value.width/frame.value.width,canvasSize.value.height/frame.value.height)*displayZoom.value;return {width:`${frame.value.width*scale}px`,height:`${frame.value.height*scale}px`,minWidth:'0'}})
let canvasObserver
watch(viewport,async element=>{canvasObserver?.disconnect();if(!element)return;await nextTick();canvasObserver=new ResizeObserver(()=>{canvasSize.value={width:element.clientWidth,height:element.clientHeight}});canvasObserver.observe(element)},{flush:'post'})
onBeforeUnmount(()=>canvasObserver?.disconnect())
const duration = computed(() => props.job.video?.duration_seconds || 90)
const referenceTime = computed(() => (props.job.hold_edit_draft || props.job.hold_draft || props.job.result)?.hold_evidence?.reference_frame / (props.job.video?.fps || 30) || 0)
const busy = computed(() => working.value || saving.value || loading.value)
const hint = computed(() => ({ freehand:'按住并沿岩点外缘描画，松开后闭合。', lines:'每次拖动画一条直线，接着上一条的终点继续画，连回起点后自动识别圈内岩点。', brush:'沿现有轮廓边缘补画缺失部分。', erase:'从轮廓外缘擦除多余部分，保留一个连续岩点。', pan:'拖动画面查看细节。触屏双指可缩放，Ctrl＋滚轮可放大。' })[tool.value])
let controller, activeRequestId, sequence = 0, gesture = null, lastHoldId = props.initialHoldId
let pendingSeed = props.initialPolygon.map(point => [...point])
const pointers = new Map()
const svgPoints = points => points.map(p => `${p[0]*frame.value.width},${p[1]*frame.value.height}`).join(' ')
const snapshot = () => ({ polygon:structuredClone(polygon.value.map(p => [...p])), closed:closed.value, holdId:editHoldId.value, selectionMode:selectionMode.value })
function remember() { history.value = [...history.value.slice(-39), snapshot()]; future.value = []; invalidate() }
function invalidate() { proposal.value = null; candidates.value = []; notice.value = '' }
function restore(value) { polygon.value = value.polygon; closed.value = value.closed; selectionMode.value = Boolean(value.selectionMode); editHoldId.value=value.holdId; lastHoldId=value.holdId; invalidate() }
function undo() { const previous = history.value.at(-1); if (!previous) return; future.value.push(snapshot()); history.value = history.value.slice(0,-1); restore(previous) }
function redo() { const next = future.value.pop(); if (!next) return; history.value.push(snapshot()); restore(next) }
function clear() { remember(); polygon.value = []; closed.value = false; selectionMode.value = false }
function setTool(id) { tool.value = id }
function confirmDiscard() { return !polygon.value.length || window.confirm('当前轮廓尚未保存，是否放弃这次描边？') }
function close() { if (confirmDiscard()) emit('close') }
function cancelRequest() { sequence++; controller?.abort(); if(activeRequestId)service.editorCancel(props.job.id,activeRequestId).catch(()=>{});activeRequestId=null; loading.value = false; working.value = false; emit('busy', false); notice.value = '已取消本次请求，当前描边保留。' }
async function loadFrame(time = requestedTime.value, index = null, preserve = false) {
  if (!preserve && !confirmDiscard()) return
  controller?.abort(); controller = new AbortController(); const seq = ++sequence
  loading.value = true; emit('busy', true); error.value = ''
  try {
    const value = await service.editorFrame(props.job.id, index === null ? { time_seconds:time } : { frame_index:index }, controller.signal)
    if (seq !== sequence) return
    frame.value = value; requestedTime.value = value.time_seconds
    polygon.value = []; closed.value = false; history.value = []; future.value = []; tool.value = 'freehand'; invalidate()
    if (editHoldId.value) selectHold()
    else if (pendingSeed.length >= 3) { polygon.value = pendingSeed; closed.value = true; pendingSeed = [] }
  } catch (e) { if (seq === sequence && !controller.signal.aborted) error.value = e.response?.data?.detail || '读取画面失败，请重新加载或换一帧。' }
  finally { if (seq === sequence) { loading.value = false; emit('busy', false) } }
}
function step(delta) { loadFrame(0, frame.value.frame_index + delta) }
function selectHold() {
  if (polygon.value.length && !confirmDiscard()) { editHoldId.value=lastHoldId; return }
  const hold=frame.value?.holds.find(h=>h.id===editHoldId.value)
  lastHoldId=editHoldId.value
  // Changing the target is an explicit discard. Never let undo restore another
  // hold's geometry under the newly selected identity.
  history.value=[];future.value=[];invalidate()
  polygon.value=hold?hold.polygon.map(p=>[...p]):[]
  closed.value=Boolean(hold);tool.value='freehand'
}
function wheel(event) { const levels=[1,2,4,8]; zoom.value=event.deltaY<0?(levels.find(n=>n>zoom.value)||8):([...levels].reverse().find(n=>n<zoom.value)||1) }
function locate(event) { const rect=event.currentTarget.getBoundingClientRect();viewport.value.scrollLeft=(event.clientX-rect.left)/rect.width*surface.value.clientWidth-viewport.value.clientWidth/2;viewport.value.scrollTop=(event.clientY-rect.top)/rect.height*surface.value.clientHeight-viewport.value.clientHeight/2 }
function point(event) { return imagePoint(event.clientX,event.clientY,surface.value.getBoundingClientRect()) }
const screenDistance = (a,b) => { const rect=surface.value.getBoundingClientRect();return Math.hypot((a[0]-b[0])*rect.width,(a[1]-b[1])*rect.height) }
function start(event) {
  if (zoomAnimating.value || busy.value || (event.pointerType === 'mouse' && event.button !== 0)) return
  pointers.set(event.pointerId, [event.clientX,event.clientY]); event.currentTarget.setPointerCapture(event.pointerId)
  if (pointers.size === 2) { cancelGesture(false); const p = [...pointers.values()]; gesture = { kind:'pinch', distance:Math.hypot(p[0][0]-p[1][0],p[0][1]-p[1][1]), zoom:zoom.value }; return }
  const p = point(event); error.value = ''
  if (tool.value === 'pan') { gesture = { kind:'pan', x:event.clientX,y:event.clientY,left:viewport.value.scrollLeft,top:viewport.value.scrollTop }; return }
  if (tool.value === 'lines') {
    if(closed.value){remember();polygon.value=[];closed.value=false}
    selectionMode.value=true
    if(polygon.value.length && screenDistance(p,polygon.value.at(-1))>24){error.value='请从上一条线的终点继续画。';return}
    gesture={kind:'lines',start:polygon.value.at(-1)||p};stroke.value=[gesture.start,p];return
  }
  selectionMode.value=false
  if (['brush','erase'].includes(tool.value) && (!closed.value || polygon.value.length < 3)) { error.value='请先描出闭合轮廓，再补画或擦除。'; return }
  gesture = { kind:tool.value, start:p }; stroke.value = [p]
}
function move(event) {
  if (!pointers.has(event.pointerId)) return
  pointers.set(event.pointerId,[event.clientX,event.clientY])
  if (!gesture) return
  if (gesture.kind === 'pinch') { const p=[...pointers.values()]; if (p.length===2) { zoom.value=Math.max(1,Math.min(8,gesture.zoom*Math.hypot(p[0][0]-p[1][0],p[0][1]-p[1][1])/Math.max(1,gesture.distance))); resetZoom(zoom.value) }; return }
  if (gesture.kind === 'pan') { viewport.value.scrollLeft=gesture.left-event.clientX+gesture.x; viewport.value.scrollTop=gesture.top-event.clientY+gesture.y; return }
  const p=point(event)
  if (gesture.kind === 'lines') { stroke.value=[gesture.start,p] }
  else if (Math.hypot(...p.map((v,i)=>v-stroke.value.at(-1)[i])) > .0005) stroke.value.push(p)
}
function end(event) {
  if (!pointers.has(event.pointerId)) return
  move(event); pointers.delete(event.pointerId)
  if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId)
  if (!gesture) return
  if (gesture.kind === 'freehand') { const path=simplifyContour(stroke.value); if (path.length >= 3) { remember(); polygon.value=path; closed.value=true; tool.value='brush' } }
  if(gesture.kind==='lines' && screenDistance(gesture.start,stroke.value.at(-1))>=3){
    const endpoint=stroke.value.at(-1);remember()
    if(!polygon.value.length)polygon.value=[gesture.start]
    if(polygon.value.length>=3 && screenDistance(endpoint,polygon.value[0])<=18){
      closed.value=true;void requestPreview()
    }else polygon.value=[...polygon.value,endpoint]
  }
  if (['brush','erase'].includes(gesture.kind)) applyBrush(gesture.kind)
  gesture=null; stroke.value=[]
}
function cancelGesture(reset = true) { gesture=null; stroke.value=[]; if (reset) pointers.clear() }
function applyBrush(kind) {
  const canvas=document.createElement('canvas'); canvas.width=frame.value.width; canvas.height=frame.value.height
  const ctx=canvas.getContext('2d',{willReadFrequently:true});ctx.fillStyle='#fff';ctx.beginPath()
  polygon.value.forEach((p,i)=>ctx[i?'lineTo':'moveTo'](p[0]*canvas.width,p[1]*canvas.height));ctx.closePath();ctx.fill()
  ctx.globalCompositeOperation=kind==='erase'?'destination-out':'source-over';ctx.strokeStyle='#fff';ctx.lineWidth=brushSize.value;ctx.lineCap='round';ctx.lineJoin='round';ctx.beginPath()
  stroke.value.forEach((p,i)=>ctx[i?'lineTo':'moveTo'](p[0]*canvas.width,p[1]*canvas.height));ctx.stroke()
  const rgba=ctx.getImageData(0,0,canvas.width,canvas.height).data, binary=new Uint8Array(canvas.width*canvas.height)
  for(let i=0;i<binary.length;i++)binary[i]=rgba[i*4+3]>127?1:0
  try { const p=simplifyContour(contourFromBinary(binary,canvas.width,canvas.height)); if(p.length>512)throw new Error('轮廓顶点过多，请撤销后重新描画更平滑的边缘。');remember();polygon.value=p;closed.value=true }
  catch(e){error.value=e.message}
}
async function requestPreview() {
  controller?.abort();controller=new AbortController();const seq=++sequence;working.value=true;emit('busy',true);error.value=''
  activeRequestId=crypto.randomUUID().replaceAll('-','')
  try {
    const value=await service.editorPreview(props.job.id,{frame_token:frame.value.frame_token,request_id:activeRequestId,mode:selectionMode.value?'region':'manual',hold_id:editHoldId.value||null,polygon:polygon.value},controller.signal)
    if(seq!==sequence)return
    if(!value.candidates?.length){error.value='未返回可用轮廓，请继续手绘或换帧。';return}
    candidates.value=value.candidates;choose(value.candidates[0])
  }catch(e){if(seq===sequence&&!controller.signal.aborted)error.value=e.response?.data?.detail||'本地处理失败，描边已保留，可继续手绘或重试。'}
  finally{if(seq===sequence){activeRequestId=null;working.value=false;emit('busy',false)}}
}
const previewManual=()=>requestPreview()
function choose(candidate){history.value=[...history.value.slice(-39),snapshot()];future.value=[];proposal.value=candidate;polygon.value=candidate.source_polygon.map(p=>[...p]);closed.value=true;selectionMode.value=false;tool.value='brush'}
async function save(){saving.value=true;emit('busy',true);error.value='';try{const job=await service.editorConfirm(props.job.id,proposal.value.proposal_id);emit('saved',job);polygon.value=[];closed.value=false;editHoldId.value=0;lastHoldId=0;history.value=[];future.value=[];invalidate();await loadFrame(frame.value.time_seconds,frame.value.frame_index,true);notice.value=props.stillImage ? '岩点已保存，可继续精修或返回选择路线。' : '已保存到岩点草稿，可继续补点；全部完成后再确认并分析。'}catch(e){error.value=e.response?.data?.detail||'保存失败，轮廓已保留，请重试。'}finally{saving.value=false;emit('busy',false)}}
defineExpose({ requestClose: close })
function beforeLeave(event){if(polygon.value.length){event.preventDefault();event.returnValue=''}}
onMounted(()=>{window.addEventListener('beforeunload',beforeLeave);loadFrame(requestedTime.value,null,true)})
onBeforeUnmount(()=>{window.removeEventListener('beforeunload',beforeLeave);controller?.abort();if(activeRequestId)service.editorCancel(props.job.id,activeRequestId).catch(()=>{});sequence++;emit('busy',false)})
</script>

<style scoped>
.hold-editor{padding:18px 0;border-top:1px solid var(--ui-line);display:grid;gap:12px;color:var(--ui-ink)}
.editor-heading,.editor-frame-controls,.editor-tools,.editor-view-controls,.editor-refine-controls,.editor-candidates{display:flex;align-items:center;flex-wrap:wrap;gap:8px}
.editor-heading{justify-content:space-between}.editor-heading h3{margin:0;font-size:16px}.hold-editor p{margin:0;line-height:1.6;font-size:13px}
.hold-editor button,.hold-editor select,.hold-editor input[type=number]{font:inherit;font-size:13px;min-height:40px;border:1px solid var(--ui-line);border-radius:8px;background:var(--ui-surface);color:var(--ui-ink);padding:8px 12px}
.hold-editor button{cursor:pointer}.hold-editor button:hover:not(:disabled){background:var(--ui-surface-subtle)}.hold-editor button:disabled{opacity:.5;cursor:not-allowed}.hold-editor button[aria-pressed=true]{background:var(--ui-brand-soft);border-color:var(--ui-brand-ink);color:var(--ui-brand-ink)}
.hold-editor label{display:flex;gap:6px;align-items:center;font-size:13px}.hold-editor input[type=number]{width:92px}.hold-editor input[type=range]{width:92px;accent-color:var(--ui-brand-ink)}
.hold-editor :focus-visible{outline:2px solid var(--ui-brand-ink);outline-offset:3px}.editor-frame-caption,.editor-hint{color:var(--ui-ink-muted)}.hold-editor .editor-error{color:var(--ui-danger,#a32d26)}
.editor-layout{display:grid;gap:12px;grid-template-columns:minmax(0,1fr)}.editor-media{position:relative;min-width:0}.editor-viewport{height:55vh;overflow:auto;max-height:65vh;min-height:180px;background:#171c1b;overscroll-behavior:contain;scrollbar-color:#708079 #171c1b}
.editor-feedback{box-sizing:border-box;height:88px;min-height:88px;overflow:auto;margin-top:12px;padding:8px 0;border-top:1px solid var(--ui-line);overflow-wrap:anywhere}
.editor-overview{position:absolute;z-index:2;right:16px;bottom:16px;font-size:12px;color:var(--ui-ink-muted)}.editor-overview button{padding:0;border-radius:0;cursor:crosshair}.editor-overview img{display:block;max-width:96px;max-height:96px}.editor-overview span{display:none}
.editor-image{position:relative;min-width:100%}.editor-image img{display:block;width:100%;height:100%;user-select:none}.editor-image svg{position:absolute;inset:0;width:100%;height:100%;touch-action:none;cursor:crosshair}
.editor-image .tool-pan{cursor:grab}.existing-contour{fill:none;stroke:#d3dbd6;stroke-width:1;vector-effect:non-scaling-stroke}.existing-contour.selected{stroke:#ffcc4d;stroke-width:2}
.edited-contour{fill:rgba(255,204,77,.24);stroke:#ffcc4d;stroke-width:2;vector-effect:non-scaling-stroke}.open-contour{fill:none;stroke:#ffcc4d;stroke-width:2;vector-effect:non-scaling-stroke}
.brush-preview{fill:none;stroke:rgba(255,204,77,.7);stroke-linecap:round;stroke-linejoin:round}
.editor-savebar{position:sticky;bottom:0;z-index:5;flex:none;display:flex;align-items:center;justify-content:flex-end;gap:12px;padding:12px 0;background:var(--ui-ground,var(--ui-surface));border-top:1px solid var(--ui-line)}.editor-savebar>span{margin-right:auto;font-size:13px;color:var(--ui-ink-muted)}.hold-editor .editor-save-action{display:inline-flex;align-items:center;justify-content:center;gap:8px;min-width:160px;min-height:48px;border:0;background:var(--ui-brand);color:var(--ui-brand-ink);font-weight:600}.hold-editor .editor-save-action:hover:not(:disabled){background:var(--ui-brand-hover)}.editor-save-action svg{width:18px;height:18px}.editor-save-action .is-loading{animation:editor-spin 1s linear infinite}@keyframes editor-spin{to{transform:rotate(360deg)}}@media(prefers-reduced-motion:reduce){.editor-save-action .is-loading{animation:none}}
@media(max-width:600px){.editor-frame-controls{align-items:stretch}.editor-tools button,.editor-refine-controls button{min-height:44px}.editor-viewport{max-height:55vh}.editor-savebar{flex-wrap:wrap}.editor-savebar>span{width:100%}.hold-editor .editor-save-action{width:100%}}
</style>
