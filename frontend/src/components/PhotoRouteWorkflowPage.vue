<template>
  <section class="photo-work">
    <header class="photo-work__header"><div><h1>抱石线路</h1><p>选一种颜色，整理一条线路。</p></div><button @click="openLibrary">线路库</button></header>
    <p v-if="state.error || localError" class="photo-work__error" role="alert">{{ localError || state.error }}<button v-if="failedMembers" @click="persistMembers(failedMembers)">重试保存</button></p>
    <button v-if="state.pendingChange && !state.saving" @click="act(state.pendingChange.action,state.pendingChange.payload)">重试未完成的修改</button>
    <p v-if="!state.loaded" role="status">正在恢复照片与线路进度…</p>
    <template v-else-if="detail">
      <div class="photo-work__heading"><h2>{{ detail.name }}</h2><button @click="returnCurrent">返回当前线路</button></div>
      <p role="status">{{ noteState }}</p>
      <div class="photo-work__layout">
        <PhotoReviewViewport v-if="detailBoard" :width="detailBoard.width" :height="detailBoard.height" :image-key="detail.id">
          <div class="photo-work__image"><img :src="photoV2AssetUrl(detailBoard.original_asset)" alt="已保存线路原图" /><svg :viewBox="`0 0 ${detailBoard.width} ${detailBoard.height}`"><polygon v-for="obj in detailObjects" :key="obj.id" :points="points(obj)" tabindex="0" role="button" :aria-label="'选择岩点 '+obj.id" @click="noteObject=obj.id" @keydown.enter="noteObject=obj.id" /></svg></div>
        </PhotoReviewViewport>
        <aside class="photo-work__tools"><h2>线路已保存</h2><p>下面的信息都可以留空，以后再补充。</p>
          <label>线路名称<input v-model="detail.name" @input="queueNotes" /></label>
          <label>难度<input v-model="detail.difficulty" @input="queueNotes" /></label>
          <label>定线者<input v-model="detail.setter" @input="queueNotes" /></label>
          <label>自由备注<textarea v-model="detail.notes" rows="4" placeholder="类型、动作、想法……想记什么就写什么" @input="queueNotes" /></label>
          <template v-if="noteMember"><h3>所选岩点备注</h3><label><input type="checkbox" :checked="noteMember.roles.includes('start')" @change="role('start')" />起点</label><label><input type="checkbox" :checked="noteMember.roles.includes('end')" @change="role('end')" />终点</label>
            <label>标签<input :value="noteMember.tags.join('，')" @change="noteMember.tags=$event.target.value.split(/[,，]/).map(x=>x.trim()).filter(Boolean); queueNotes()" /></label>
            <label>岩点备注<textarea v-model="noteMember.note" @input="queueNotes" /></label>
          </template><p v-else>点选照片中的岩点，可添加起终点、标签或备注。</p>
          <button v-if="noteState==='备注保存失败'" @click="saveNotes">重试保存备注</button>
        </aside>
      </div>
    </template>
    <template v-else-if="view==='library'"><div class="photo-work__heading"><h2>线路库</h2><button @click="view='current'">返回当前线路</button></div>
      <button v-for="route in library" :key="route.id" class="photo-work__library-item" @click="openDetail(route)">{{route.name}} · {{route.difficulty || '未填写难度'}}</button><p v-if="!library.length">保存后的线路会出现在这里。</p>
    </template>
    <template v-else-if="!session || ['saved','abandoned'].includes(session.status)">
      <input ref="input" class="photo-work__file" type="file" accept="image/jpeg,image/png,image/webp" @change="choose" />
      <div v-if="state.pending" class="photo-work__pending"><img :src="state.preview" alt="待上传照片预览" /><div><h2>确认这张照片</h2><p>确认后分析可选颜色。提取时会使用云端 AI 处理照片或局部裁剪。</p><button :disabled="state.uploading || !editable" @click="input.click()">更换照片</button><button class="photo-work__primary" :disabled="state.uploading || !editable" @click="workflow.upload">{{state.uploading?'正在上传…':'确认上传'}}</button></div></div>
      <div v-else class="photo-work__upload"><h2>从一张照片开始</h2><p>选择后可先预览，确认前不会上传。</p><button class="photo-work__primary" :disabled="!editable" @click="input.click()">选择照片</button></div>
      <p v-if="state.uploading" role="status">已上传 {{state.uploadProgress}}%<progress :value="state.uploadProgress" max="100" aria-label="照片上传进度" /></p>
      <div v-if="!state.pending" class="photo-work__samples"><button v-for="sample in samples" :key="sample.name" :disabled="!editable || state.uploading" @click="workflow.choose(photoSampleFile(sample.url,sample.name))"><img :src="sample.url" :alt="sample.name" /><span>{{sample.name}}</span></button></div>
    </template>
    <template v-else-if="session.status==='awaiting_color'"><h2>想提取哪一种颜色？</h2><div class="photo-work__layout"><PhotoReviewViewport :width="board.width" :height="board.height" :image-key="board.id"><img class="photo-work__plain" :src="photoV2AssetUrl(board.original_asset)" alt="已上传照片" /></PhotoReviewViewport><aside class="photo-work__tools"><p>一次提取一条线路。选择后自动在后台处理。</p><button v-for="color in session.colors" :key="color" :disabled="state.saving || !editable" @click="act('color',{color})">{{color}}</button><button @click="abandon">放弃当前线路</button></aside></div></template>
    <template v-else-if="session.status==='processing' || session.status==='failed'"><div class="photo-work__processing"><span v-if="session.status==='processing'" class="photo-work__spinner" aria-hidden="true"></span><h2>{{session.stage}}</h2><p>{{session.error || '照片和已完成的步骤已保存，可以继续使用其他功能。'}}</p><progress :value="session.progress" max="100" :aria-label="session.stage" /><button v-if="session.status==='failed'" @click="act('retry')">重试</button><button @click="abandon">放弃当前线路</button></div></template>
    <template v-else-if="session.status==='ready'">
      <div class="photo-work__heading"><h2>{{session.color}}线路</h2><span>{{members.length}} 个岩点 · {{state.saving?'保存中…':'进度已保存'}}</span></div>
      <p v-if="session.ai.status==='unavailable'" class="photo-work__notice">{{session.ai.message}} <button :disabled="state.saving" @click="act('retry')">重试 AI 复核</button></p>
      <div class="photo-work__layout">
        <PhotoReviewViewport :width="board.width" :height="board.height" :image-key="board.id">
          <div class="photo-work__image" @click="photoClick"><img :src="photoV2AssetUrl(board.original_asset)" alt="线路原图，点击岩点调整" /><svg :viewBox="`0 0 ${board.width} ${board.height}`"><polygon v-for="obj in board.objects" :key="obj.id" :class="{'is-selected':selected===obj.id,'is-excluded':!members.includes(obj.id)}" :points="points(obj)" tabindex="0" role="button" :aria-label="(members.includes(obj.id)?'已保留岩点 ':'可加入岩点 ')+obj.id" @click="select($event,obj)" @keydown.enter="selected=obj.id" /></svg></div>
        </PhotoReviewViewport>
        <aside class="photo-work__tools"><h2>调整线路</h2><p>已自动保留识别到的岩点。满意后直接保存，只有需要调整时才操作。</p>
          <button :disabled="!selected || state.saving || !editable" @click="toggle">{{!selected || members.includes(selected)?'移出线路':'加入线路'}}</button>
          <button :aria-pressed="adding" :disabled="state.saving || !editable" @click="adding=!adding; calibration=false">{{adding?'请点击原图中的岩点':'补加岩点'}}</button>
          <button :disabled="!undo.length || state.saving || !editable" @click="undoChange">撤销</button>
          <button class="photo-work__primary" :disabled="!members.length || state.saving || !editable" @click="save">保存线路</button>
          <details class="photo-work__advanced"><summary>高级工具</summary><p>仅在需要精确定位到电子岩板时使用。</p><button @click="calibration=!calibration; calibrationPoints=[]; adding=false">{{calibration?'请依次点左下、右下、右上、左上四角孔位':'标定四角孔位'}}</button>
            <template v-if="selectedObject"><label>孔位<input v-model="anchorInput" placeholder="例如 A1, B2" /></label><button @click="anchors">保存孔位</button><label>轮廓坐标<textarea v-model="contourInput" rows="3" /></label><button @click="contour">保存轮廓修正</button></template>
          </details><button @click="abandon">放弃当前线路</button>
        </aside>
      </div>
    </template>
  </section>
</template>

<script setup>
import { computed, inject, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { ElMessageBox } from 'element-plus'
import api from '../services/apiClient'
import PhotoReviewViewport from './PhotoReviewViewport.vue'
import { photoRouteV2Service as service, photoV2AssetUrl } from '../services/photoRouteService'
import { photoSampleFile } from '../utils/photoSample'
import one from '../assets/boulder-samples/boulder-1.jpg?inline'
import two from '../assets/boulder-samples/boulder-2.jpg?inline'
const workflow=inject('photoWorkflow'), access=inject('pilotAccess'), state=workflow.state
const session=computed(()=>state.session), board=computed(()=>session.value?.board)
const editable=computed(()=>!access.session.authEnabled || access.lease.ownedByMe)
const samples=[{name:'抱石路线1',url:one},{name:'抱石路线2',url:two}]
const input=ref(null), selected=ref(''), adding=ref(false), members=ref([]), undo=ref([]), failedMembers=ref(null)
const calibration=ref(false), calibrationPoints=ref([]), anchorInput=ref(''), contourInput=ref(''), localError=ref('')
const view=ref('current'), library=ref([]), detail=ref(null), detailBoard=ref(null), noteObject=ref(''), noteState=ref('备注已保存')
let notesTimer, notesPromise
const noteKey='photo-route-notes:'+(access.session.username || 'local')
onMounted(async()=>{
  try {
    const recovery=JSON.parse(localStorage.getItem(noteKey)||'null')
    if(recovery){await openDetail(recovery);noteState.value='等待保存备注';notesTimer=setTimeout(saveNotes,800)}
  } catch {localError.value='未能恢复备注，请保持页面打开后重试'}
})
const selectedObject=computed(()=>board.value?.objects.find(obj=>obj.id===selected.value))
const noteMember=computed(()=>detail.value?.members.find(m=>m.object_id===noteObject.value))
const detailObjects=computed(()=>detailBoard.value?.objects.filter(obj=>detail.value?.members.some(m=>m.object_id===obj.id)) || [])
watch(()=>session.value?.route,route=>{if(!failedMembers.value) members.value=route?.members.map(m=>m.object_id)||[]},{immediate:true})
watch(()=>session.value?.id,()=>{undo.value=[];selected.value='';failedMembers.value=null})
watch(selectedObject,obj=>{anchorInput.value=obj?.anchors.map(a=>a.hole_id).join(', ')||''; contourInput.value=JSON.stringify(obj?.contour||[])})
const points=obj=>obj.contour.map(p=>p.join(',')).join(' ')
async function act(action,payload={}) { try{return await workflow.change(action,payload)}catch{return null} }
function choose(event){const file=event.target.files?.[0];event.target.value='';if(file)workflow.choose(file)}
function select(event,obj){if(!adding.value&&!calibration.value){event.stopPropagation();selected.value=obj.id}}
async function persistMembers(ids) {failedMembers.value=[...ids]; members.value=[...ids];const value=await act('members',{member_ids:ids});if(value){failedMembers.value=null;members.value=value.route.members.map(m=>m.object_id)}}
function toggle(){undo.value.push([...members.value]);persistMembers(members.value.includes(selected.value)?members.value.filter(id=>id!==selected.value):[...members.value,selected.value])}
function undoChange(){persistMembers(undo.value.pop())}
async function photoClick(event){
  if(!editable.value || (!adding.value&&!calibration.value))return
  const rect=event.currentTarget.getBoundingClientRect(), point=[(event.clientX-rect.left)/rect.width,(event.clientY-rect.top)/rect.height]
  if(adding.value){adding.value=false;undo.value.push([...members.value]);await act('add',{point});return}
  calibrationPoints.value.push([point[0]*board.value.width,point[1]*board.value.height])
  if(calibrationPoints.value.length===4){try{await service.calibrate(board.value.id,{photo_points:calibrationPoints.value,board_hole_ids:['A1','AD1','AD20','A20']});await workflow.refresh()}catch{localError.value='标定未保存，请检查四个孔位后重试'}calibration.value=false}
}
async function anchors(){try{await service.patchObject(board.value.id,selected.value,{expected_version:selectedObject.value.object_version,anchors:anchorInput.value.toUpperCase().split(/[,，\s]+/).filter(Boolean).map(hole_id=>({hole_id,confidence:1,confirmed:true}))});await workflow.refresh()}catch{localError.value='孔位未保存，请检查输入'}}
async function contour(){try{await service.patchObject(board.value.id,selected.value,{expected_version:selectedObject.value.object_version,contour:JSON.parse(contourInput.value)});await workflow.refresh()}catch{localError.value='轮廓未保存，请检查坐标'}}
async function abandon(){try{await ElMessageBox.confirm('放弃后可以开始下一条线路，已保存的线路不会改变。','放弃当前线路',{confirmButtonText:'放弃',cancelButtonText:'继续编辑'});await act('abandon')}catch{}}
async function save(){const result=await act('save',{member_ids:members.value});if(result)await openDetail(result.route)}
async function returnCurrent(){if(await beforeLeave()){detail.value=null;view.value='current'}}
async function openLibrary(){if(!(await beforeLeave()))return;library.value=(await service.routes({status:'completed'}));detail.value=null;view.value='library'}
async function openDetail(route){detail.value=JSON.parse(JSON.stringify(route));detailBoard.value=await service.board(route.board_version_id);noteObject.value='';noteState.value='备注已保存'}
function role(value){const roles=noteMember.value.roles;noteMember.value.roles=roles.includes(value)?roles.filter(r=>r!==value):[...roles,value];queueNotes()}
function queueNotes(){
  detail.value.request_id=crypto.randomUUID()
  noteState.value='等待保存备注'
  try{localStorage.setItem(noteKey,JSON.stringify(detail.value))}catch{localError.value='浏览器未能暂存备注，请保持页面打开直到保存完成'}
  clearTimeout(notesTimer);notesTimer=setTimeout(saveNotes,800)
}
async function saveNotes(){
  clearTimeout(notesTimer);if(notesPromise)await notesPromise
  if(!detail.value || noteState.value==='备注已保存')return true
  const pending=JSON.parse(JSON.stringify(detail.value));noteState.value='正在保存备注'
  notesPromise=(async()=>{try{const result=(await api.put(`/api/photo-routes/workflow/routes/${pending.id}/notes`,pending)).data;detail.value.version=result.version;noteState.value=JSON.stringify({...detail.value,version:pending.version})===JSON.stringify(pending)?'备注已保存':'等待保存备注';if(noteState.value!=='备注已保存')queueNotes();else localStorage.removeItem(noteKey);return true}catch{noteState.value='备注保存失败';return false}})()
  const result=await notesPromise;notesPromise=null;return result
}
async function beforeLeave(){if(failedMembers.value)return false;return (await saveNotes()) && await workflow.beforeLeave()}
function beforeUnload(event){if(failedMembers.value || ['等待保存备注','正在保存备注','备注保存失败'].includes(noteState.value)){event.preventDefault();event.returnValue=''}}
window.addEventListener('beforeunload',beforeUnload)
onBeforeUnmount(()=>{clearTimeout(notesTimer);window.removeEventListener('beforeunload',beforeUnload)})
defineExpose({beforeLeave,returnCurrent})
</script>

<style scoped>
.photo-work{color:var(--ui-ink,#222);background:var(--ui-paper,#f8f6ef);padding:24px;min-height:80dvh}
.photo-work__header,.photo-work__heading{display:flex;justify-content:space-between;align-items:center;gap:16px;margin-bottom:20px}.photo-work h1{font-size:28px;margin:0 0 8px}.photo-work h2{font-size:20px}.photo-work p{line-height:1.6}.photo-work button{border:1px solid var(--ui-line-strong,#cfcac0);border-radius:8px;background:white;color:inherit;min-height:44px;padding:10px 16px;cursor:pointer}.photo-work button:hover{background:#fff4cb}.photo-work button:disabled{opacity:.5;cursor:default}.photo-work button:focus-visible{outline:3px solid #b08000;outline-offset:2px}.photo-work .photo-work__primary{background:#f8c82c;border-color:#f8c82c;font-weight:700}.photo-work__layout{display:grid;grid-template-columns:minmax(0,1fr) 300px;gap:24px;min-height:380px;height:calc(100dvh - 250px);max-height:850px}.photo-work__tools{overflow-y:auto;overscroll-behavior:contain;scrollbar-gutter:stable;display:flex;flex-direction:column;gap:12px;padding:4px 12px}.photo-work__tools label{display:flex;flex-direction:column;gap:6px}.photo-work input:not([type=checkbox]),.photo-work textarea{width:100%;box-sizing:border-box;padding:10px;border:1px solid #cfcac0;border-radius:6px;font:inherit}.photo-work input[type=checkbox]{width:20px;height:20px;accent-color:#9d7300}.photo-work__image{position:relative;width:100%;height:100%}.photo-work__image img,.photo-work__plain{width:100%;height:100%;display:block}.photo-work__image svg{position:absolute;inset:0;width:100%;height:100%}.photo-work__image polygon{fill:#f8c82c22;stroke:#eab600;stroke-width:3;cursor:pointer;vector-effect:non-scaling-stroke}.photo-work__image polygon.is-excluded{fill:transparent;stroke:#fff9;stroke-dasharray:4 4;stroke-width:1}.photo-work__image polygon.is-selected{stroke:#111;stroke-width:4}.photo-work__pending{display:flex;gap:24px;align-items:center}.photo-work__pending>img{width:40%;height:45dvh;object-fit:contain}.photo-work__pending button{margin-right:12px}.photo-work__upload{padding:30px 0}.photo-work__samples{display:flex;gap:16px;margin-top:24px}.photo-work__samples button{display:flex;flex-direction:column;gap:8px;max-width:180px}.photo-work__samples img{width:100%;height:150px;object-fit:contain}.photo-work__file{display:none}.photo-work__processing{padding:40px 0;max-width:600px}.photo-work__processing progress{display:block;width:100%;accent-color:#eab600;margin:20px 0}.photo-work__spinner{display:inline-block;width:28px;height:28px;border:3px solid #e4dfd2;border-top-color:#b08100;border-radius:50%;animation:photo-work-spin 1s linear infinite}.photo-work__error{color:#963a2c;background:#fff1ee;padding:12px}.photo-work__notice{padding:12px;background:#fff4cb}.photo-work__advanced{border-top:1px solid #d2ccc0;padding-top:18px}.photo-work__advanced summary{cursor:pointer;min-height:44px}.photo-work__library-item{display:block;width:100%;margin:12px 0;text-align:left}@keyframes photo-work-spin{to{transform:rotate(360deg)}}@media(prefers-reduced-motion:reduce){.photo-work__spinner{animation:none}}@media(max-width:860px){.photo-work{padding:16px 12px 90px}.photo-work__layout{display:flex;flex-direction:column;height:auto;max-height:none}.photo-work__layout>:first-child{height:46dvh;flex:none;min-height:250px}.photo-work__tools{max-height:55dvh;padding:0}.photo-work__pending{flex-direction:column;align-items:stretch}.photo-work__pending>img{width:100%;height:35dvh}}
</style>
