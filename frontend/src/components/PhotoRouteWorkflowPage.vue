<template>
  <section class="photo-work" :class="[`photo-work--${surfaceState}`, {'is-busy':state.saving || state.uploading}]">
    <header class="photo-work__header"><div><h1>抱石线路</h1><p v-if="surfaceState === 'awaiting_color'">点一个岩点，整理出一条线路。</p></div><button @click="openLibrary">线路库</button></header>
    <p v-if="state.connectionLost" class="photo-work__offline" role="status"><strong>当前离线</strong><span>照片和未完成修改仍保留在本机，恢复网络后会继续同步。</span></p>
    <p v-if="!editable" class="photo-work__permission" role="status"><strong>当前为只读模式</strong><span>照片与线路可以查看，取得编辑权后才能修改。</span></p>
    <p v-if="(state.error && !state.pending) || localError" class="photo-work__error" role="alert">{{ localError || state.error }}<button v-if="failedMembers" :disabled="!editable" @click="persistMembers(failedMembers)">重试保存</button></p>
    <button v-if="state.pendingChange && !state.saving" :disabled="!editable" @click="act(state.pendingChange.action,state.pendingChange.payload)">重试未完成的修改</button>
    <div v-if="!state.loaded" class="photo-work__processing photo-work__processing--center" role="status"><span class="photo-work__spinner" aria-hidden="true"></span><h2>正在恢复进度</h2><p>照片、轮廓和未完成的修改都会保留。</p></div>
    <template v-else-if="detail">
      <div class="photo-work__heading"><h2>{{ detail.name }}</h2><button @click="returnCurrent">返回上一页</button></div>
      <p role="status">{{ noteState }}</p>
      <div class="photo-work__layout">
        <PhotoReviewViewport v-if="detailBoard" :width="detailBoard.width" :height="detailBoard.height" :image-key="detail.id">
          <div class="photo-work__image"><img :src="photoV2AssetUrl(detailBoard.original_asset)" alt="已保存线路原图" /><svg :viewBox="`0 0 ${detailBoard.width} ${detailBoard.height}`"><polygon v-for="obj in detailObjects" :key="obj.id" class="is-route-contour is-glow" :class="{'is-selected':noteObject===obj.id}" :points="points(obj)" tabindex="0" role="button" :aria-label="photoObjectLabel(obj, detailBoard, { member: true, action: 'view' })" @click="noteObject=obj.id" @keydown.enter="noteObject=obj.id" @keydown.space.prevent="noteObject=obj.id" /></svg></div>
        </PhotoReviewViewport>
        <aside class="photo-work__tools"><h2>线路已保存</h2><p>下面的信息都可以留空，以后再补充。</p><p class="photo-work__quiet-note">删除只移出当前线路，原图和岩点识别结果仍会保留。</p>
          <div class="photo-work__save-bar">
            <button class="photo-work__primary" :disabled="noteState==='正在保存备注' || noteState==='备注已保存' || !editable" @click="saveNotes">
              <span v-if="noteState==='正在保存备注'" class="photo-work__button-spinner" aria-hidden="true"></span>{{ noteSaveLabel }}
            </button>
            <span role="status" aria-live="polite">{{ noteSaveStatus }}</span>
          </div>
          <label>线路名称<input v-model="detail.name" :disabled="!editable" @input="queueNotes" /></label>
          <label>难度<input v-model="detail.difficulty" :disabled="!editable" @input="queueNotes" /></label>
          <label>定线者<input v-model="detail.setter" :disabled="!editable" @input="queueNotes" /></label>
          <label>自由备注<textarea v-model="detail.notes" rows="4" :disabled="!editable" placeholder="类型、动作、想法……想记什么就写什么" @input="queueNotes" /></label>
          <template v-if="noteMember"><h3>所选岩点备注</h3><label class="photo-work__checkbox-row"><input type="checkbox" :checked="noteMember.roles.includes('start')" :disabled="!editable" @change="role('start')" />起点</label><label class="photo-work__checkbox-row"><input type="checkbox" :checked="noteMember.roles.includes('end')" :disabled="!editable" @change="role('end')" />终点</label>
            <label>标签<input :value="noteMember.tags.join('，')" :disabled="!editable" @change="updateMemberTags" /></label>
            <label>岩点备注<textarea v-model="noteMember.note" :disabled="!editable" @input="queueNotes" /></label>
          </template><p v-else>点选照片中的岩点，可添加起终点、标签或备注。</p>
          <button v-if="noteState==='备注保存失败'" :disabled="!editable" @click="saveNotes">重试保存备注</button>
        </aside>
      </div>
    </template>
    <template v-else-if="view==='library'"><div class="photo-work__heading"><h2>线路库</h2><button @click="returnFromLibrary">返回上一页</button></div>
      <button v-for="route in library" :key="route.id" class="photo-work__library-item" @click="openDetail(route)">{{route.name}} · {{route.difficulty || '未填写难度'}}</button><p v-if="!library.length">保存后的线路会出现在这里。</p>
    </template>
    <template v-else-if="!session || ['saved','abandoned'].includes(session.status)">
      <input ref="cameraInput" class="photo-work__file" type="file" accept="image/jpeg,image/png,image/webp" capture="environment" @change="choose" />
      <input ref="albumInput" class="photo-work__file" type="file" accept="image/jpeg,image/png,image/webp" @change="choose" />
      <div v-if="state.pending" class="photo-work__pending"><img :src="state.preview" alt="待上传照片预览" /><div class="photo-work__pending-sheet">
        <button class="photo-work__back" type="button" :disabled="state.uploading" @click="leaveConfirmation">
          <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M15 18l-6-6 6-6" /></svg><span>返回</span>
        </button>
        <h2>确认这张照片</h2><p>原图会完整保留。确认后识别照片中的岩点边缘，再由你逐个检查。</p>
        <p v-if="state.error" class="photo-work__inline-error" role="alert"><strong>照片仍保留在本机。</strong><span>{{ state.error }}</span></p>
        <div class="photo-work__actions"><button :disabled="state.uploading || !editable" @click="albumInput.click()">更换照片</button><button class="photo-work__primary" :disabled="state.uploading || !editable" @click="workflow.upload"><span v-if="state.uploading" class="photo-work__button-spinner" aria-hidden="true"></span>{{state.uploading?'正在上传…':state.error?'重新上传':'确认上传'}}</button></div>
      </div></div>
      <div v-else class="photo-work__upload"><div class="photo-work__upload-copy"><h2>记录一条刚刚爬过的线路</h2><p>拍下整面墙，系统识别岩点轮廓后由你确认。原始照片始终保留。</p></div><div class="photo-work__capture-actions"><button class="photo-work__primary" :disabled="!editable" @click="cameraInput.click()">拍摄墙面</button><button :disabled="!editable" @click="albumInput.click()">从相册选择</button></div></div>
      <p v-if="state.uploading" role="status">已上传 {{state.uploadProgress}}%<progress :value="state.uploadProgress" max="100" aria-label="照片上传进度" /></p>
      <div v-if="!state.pending" class="photo-work__samples"><button v-for="sample in samples" :key="sample.name" :disabled="!editable || state.uploading" @click="chooseSample(sample)"><img :src="sample.url" :alt="sample.name" /><span>{{sample.name}}</span></button></div>
    </template>
    <template v-else-if="session.status==='awaiting_color'">
      <h2>点击岩点选择线路颜色</h2>
      <div class="photo-work__layout">
        <PhotoReviewViewport :width="board.width" :height="board.height" :image-key="board.id">
          <div class="photo-work__image" @click="previewClick"><img :src="photoV2AssetUrl(board.original_asset)" alt="已上传照片" />
            <svg :viewBox="`0 0 ${board.width} ${board.height}`" aria-label="所选颜色的岩点预览">
              <polygon v-for="obj in board.objects" :key="obj.id" :points="points(obj)" :class="{'is-selected':previewObject===obj.id,'is-route-contour':previewColor && obj.color_group===previewColor,'is-glow':previewColor && obj.color_group===previewColor,'is-muted':previewColor && obj.color_group!==previewColor}" tabindex="0" role="button" :aria-label="photoObjectLabel(obj, board)" @keydown.enter="chooseSeed(obj)" @keydown.space.prevent="chooseSeed(obj)" />
            </svg>
          </div>
        </PhotoReviewViewport>
        <aside class="photo-work__tools">
          <p><strong>先点击照片中的一个岩点。</strong>系统会按它的识别颜色选出整条线路，也可以在下面改选其他颜色。</p>
          <p v-if="selectedPreviewObject" class="photo-work__selection" role="status">已选择一个{{selectedPreviewObject.color_group}}岩点 · 当前路线颜色：{{previewColor || '待选择'}}</p>
          <button v-for="group in colorGroups" :key="group.color" class="photo-work__color" :aria-pressed="previewColor===group.color" :disabled="state.saving || !editable" @click="previewColor=group.color; previewObject=''">
            <span class="photo-work__swatch" :style="{background:group.swatch}" aria-hidden="true"></span><span>{{group.color}}</span><span class="photo-work__count">{{group.count}} 个</span>
          </button>
          <p role="status">{{previewColor ? `正在预览${previewColor} · ${previewObjects.length} 个岩点` : '请先点击一个岩点选择路线颜色'}}</p>
          <template v-if="session.flow_version>=2 && previewObject">
            <label>为所选岩点指定颜色<select v-model="assignedColor"><option value="" disabled>选择颜色</option><option v-for="color in assignableColors" :key="color">{{color}}</option></select></label>
            <button :disabled="!assignedColor || state.saving || !editable" @click="assignColor">保存岩点颜色</button>
          </template>
          <p v-else-if="previewColor==='待确认'">点击照片中的岩点，为它指定颜色后再提取。</p>
          <button class="photo-work__primary" :disabled="!previewObjects.length || previewColor==='待确认' || state.saving || !editable" @click="act('color',{color:previewColor,member_ids:previewObjects.map(obj=>obj.id),board_version:board.version})">提取{{previewColor && previewColor!=='待确认' ? previewColor : ''}}线路</button>
          <button :disabled="state.saving || !editable" @click="abandon">放弃当前线路</button>
        </aside>
      </div>
    </template>
    <template v-else-if="session.status==='processing' || session.status==='failed'">
      <div class="photo-work__processing" :class="{'is-failed':session.status==='failed'}">
        <span v-if="session.status==='processing'" class="photo-work__spinner" aria-hidden="true"></span>
        <h2>{{session.status==='failed'?'这次没有识别完成':session.stage}}</h2>
        <p>{{session.error || '照片和已完成的步骤已保存，可以继续使用其他功能。'}}</p>
        <p v-if="session.status==='failed' && session.route">已有岩点和线路已保留，可以返回编辑，换个位置补选。</p>
        <progress v-if="session.status==='processing'" :value="session.progress" max="100" :aria-label="session.stage" />
        <TransitionGroup v-if="session.status==='processing'" name="photo-stage" tag="ol" class="photo-work__stage-list" aria-label="识别步骤">
          <li v-for="step in visibleProcessingSteps" :key="step.label" :class="{'is-done':session.progress>=step.complete,'is-current':session.progress<step.complete}" :aria-current="session.progress<step.complete?'step':undefined">
            <span class="photo-work__stage-dot" aria-hidden="true"></span><span>{{step.label}}</span><small>{{session.progress>=step.complete?'已完成':'进行中'}}</small>
          </li>
        </TransitionGroup>
        <div class="photo-work__recovery"><button v-if="session.status==='failed' && session.route" class="photo-work__primary" :disabled="state.saving || !editable" @click="act('resume')">返回编辑</button><button v-if="session.status==='failed'" :disabled="state.saving || !editable" @click="act('retry')">重试识别</button><button :disabled="state.saving || !editable" @click="abandon">放弃当前线路</button></div>
      </div>
    </template>
    <template v-else-if="session.status==='ready'">
      <div class="photo-work__heading"><h2>{{session.color}}线路</h2><span>{{members.length}} 个岩点 · {{state.saving?'保存中…':'进度已保存'}}</span></div>
      <p v-if="session.ai.status==='unavailable'" class="photo-work__notice">{{session.ai.message}} <button :disabled="state.saving || !editable" @click="act('retry')">重试 AI 复核</button></p>
      <div class="photo-work__layout">
        <PhotoReviewViewport :width="board.width" :height="board.height" :image-key="board.id">
          <div class="photo-work__image" @click="photoClick"><img :src="photoV2AssetUrl(board.original_asset)" alt="线路原图，点击岩点调整" /><svg :viewBox="`0 0 ${board.width} ${board.height}`"><polygon v-for="obj in visibleObjects" :key="obj.id" :class="{'is-selected':selected===obj.id,'is-route-contour':members.includes(obj.id),'is-glow':showGlow && members.includes(obj.id),'is-hidden-contour':!showGlow && members.includes(obj.id),'is-excluded':!members.includes(obj.id)}" :points="points(obj)" tabindex="0" role="button" :aria-label="photoObjectLabel(obj, board, { member: members.includes(obj.id) })" @keydown.enter="selected=obj.id" @keydown.space.prevent="selected=obj.id" /></svg></div>
        </PhotoReviewViewport>
        <aside class="photo-work__tools"><h2>审查线路岩点</h2>
          <p>黄线是识别到的岩点边缘；放大后点按，可将岩点加入或移出线路。</p><p role="status">{{selected ? (members.includes(selected) ? "已选中线路中的岩点" : "已选中其他候选岩点") : "请先点击一个岩点"}}</p><label class="photo-work__toggle"><span>显示荧光轮廓</span><input v-model="showGlow" type="checkbox" /></label><label class="photo-work__checkbox-row"><input v-model="showOther" type="checkbox" /> 显示其他候选岩点</label>
          <details class="photo-work__hold-list"><summary>岩点列表（{{visibleObjects.length}}）</summary><div><button v-for="obj in visibleObjects" :key="obj.id" :class="{'is-selected':selected===obj.id}" :aria-pressed="selected===obj.id" @click="selected=obj.id">{{ photoObjectLabel(obj, board, { member: members.includes(obj.id) }) }}</button></div></details>
          <button class="photo-work__desktop-review-action" :disabled="!selected || state.saving || !editable" @click="toggle">{{!selected || members.includes(selected)?'移出当前线路':'加入线路'}}</button>
          <button :aria-pressed="adding" :disabled="state.saving || !editable" @click="adding=!adding">{{adding?'请点击照片中的遗漏岩点':'添加遗漏岩点'}}</button>
          <button class="photo-work__primary photo-work__desktop-review-action" :disabled="!members.length || state.saving || !editable" @click="save">保存线路</button>
          <details v-if="selectedObject" class="photo-work__advanced"><summary>轮廓修正</summary><p>仅在识别边缘不准确时修改所选岩点轮廓。</p><label>轮廓坐标<textarea v-model="contourInput" rows="3" :disabled="!editable" /></label><button :disabled="state.saving || !editable" @click="contour">保存轮廓修正</button></details><button :disabled="state.saving || !editable" @click="abandon">放弃当前线路</button>
        </aside>
      </div>
      <div class="photo-work__mobile-command" role="group" aria-label="线路复核操作">
        <span aria-live="polite">{{ selected ? (members.includes(selected) ? '所选岩点在线路中' : '所选岩点尚未加入') : '先点一个岩点' }}</span>
        <button :disabled="!selected || state.saving || !editable" @click="toggle">{{!selected || members.includes(selected)?'移出线路':'加入线路'}}</button>
        <button class="photo-work__primary" :disabled="!members.length || state.saving || !editable" @click="save">保存线路</button>
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
import { pickPhotoObject } from '../utils/photoHitTest.js'
import { photoObjectLabel } from '../utils/photoObjectLabel.js'
import { isPhotoFlowScreen, parsePhotoWorkflowHash, photoWorkflowHash, photoWorkflowScreen } from '../utils/photoWorkflowRoute.js'
import one from '../assets/boulder-samples/boulder-1.jpg?inline'
import two from '../assets/boulder-samples/boulder-2.jpg?inline'
const workflow=inject('photoWorkflow'), access=inject('pilotAccess'), state=workflow.state
const session=computed(()=>state.session), board=computed(()=>session.value?.board)
const editable=computed(()=>!access.session.authEnabled || access.lease.ownedByMe)
const samples=[{name:'抱石路线1',url:one},{name:'抱石路线2',url:two}]
const previewColor=ref(''), previewObject=ref(''), assignedColor=ref('')
const assignableColors=['红色','橙色','黄色','绿色','蓝色','紫色','粉色','黑色','白色','灰色']
const colorGroups=computed(()=>session.value?.color_groups || [])
const previewObjects=computed(()=>board.value?.objects.filter(obj=>obj.color_group===previewColor.value)||[])
const selectedPreviewObject=computed(()=>board.value?.objects.find(obj=>obj.id===previewObject.value))
function chooseSeed(obj){previewObject.value=obj.id;if(obj.color_group!=='待确认')previewColor.value=obj.color_group}
async function assignColor(){
  const value=await act('assign-color',{color:assignedColor.value,member_ids:[previewObject.value]})
  if(value){previewColor.value=assignedColor.value;previewObject.value='';assignedColor.value=''}
}
const cameraInput=ref(null), albumInput=ref(null), selected=ref(''), adding=ref(false), members=ref([]), failedMembers=ref(null), showOther=ref(false), showGlow=ref(true)
const visibleObjects=computed(()=>board.value?.objects.filter(obj=>showOther.value || members.value.includes(obj.id)) || [])
const contourInput=ref(''), localError=ref('')
const view=ref('current'), library=ref([]), detail=ref(null), detailBoard=ref(null), noteObject=ref(''), noteState=ref('备注已保存')
const noteSaveLabel=computed(()=>({
  '备注已保存':'已保存',
  '等待保存备注':'保存修改',
  '正在保存备注':'正在保存…',
  '备注保存失败':'重试保存',
}[noteState.value] || '保存修改'))
const noteSaveStatus=computed(()=>({
  '备注已保存':'所有修改均已保存',
  '等待保存备注':'有修改尚未保存',
  '正在保存备注':'正在保存，请稍候',
  '备注保存失败':'保存失败，请重试',
}[noteState.value] || noteState.value))
const surfaceState=computed(()=>{
  if(detail.value)return 'saved'
  if(view.value==='library')return 'library'
  if(!state.loaded)return 'restoring'
  if(!session.value || ['saved','abandoned'].includes(session.value.status))return state.pending?'capture-preview':'home'
  return session.value.status
})
const processingSteps=[
  {label:'上传照片',start:0,complete:20},
  {label:'检查照片',start:20,complete:45},
  {label:'识别岩点轮廓',start:45,complete:80},
  {label:'准备人工复核',start:80,complete:100},
]
const visibleProcessingSteps=computed(()=>{
  const progress=Number(session.value?.progress || 0)
  return processingSteps.filter(step=>progress>=step.start)
})
let notesTimer, notesPromise
const noteKey='photo-route-notes:'+(access.session.username || 'local')
onMounted(async()=>{
  window.addEventListener('hashchange',applyPhotoLocation)
  try {
    const recovery=JSON.parse(localStorage.getItem(noteKey)||'null')
    if(recovery){await openDetail(recovery,'replace');noteState.value='等待保存备注';if(editable.value)notesTimer=setTimeout(saveNotes,800)}
  } catch {localError.value='未能恢复备注，请保持页面打开后重试'}
})
const selectedObject=computed(()=>board.value?.objects.find(obj=>obj.id===selected.value))
const noteMember=computed(()=>detail.value?.members.find(m=>m.object_id===noteObject.value))
const detailObjects=computed(()=>detailBoard.value?.objects.filter(obj=>detail.value?.members.some(m=>m.object_id===obj.id)) || [])
watch(()=>session.value?.route,route=>{if(!failedMembers.value) members.value=route?.members.map(m=>m.object_id)||[]},{immediate:true})
watch(()=>session.value?.id,()=>{selected.value='';failedMembers.value=null;previewColor.value='';previewObject.value='';assignedColor.value=''})
watch(selectedObject,obj=>{contourInput.value=JSON.stringify(obj?.contour||[])})
const points=obj=>obj.contour.map(p=>p.join(',')).join(' ')
function previewClick(event){
  const rect=event.currentTarget.getBoundingClientRect()
  const point=[(event.clientX-rect.left)*board.value.width/rect.width,(event.clientY-rect.top)*board.value.height/rect.height]
  const hit=pickPhotoObject(board.value.objects,point,6*board.value.width/rect.width)
  if(hit)chooseSeed(hit);else previewObject.value=''
}
async function act(action,payload={}) {
  if(!editable.value){localError.value='当前为只读模式，取得编辑权后才能修改。';return null}
  try{return await workflow.change(action,payload)}catch{return null}
}
function writePhotoLocation(screen,routeId='',mode='push'){
  const next=photoWorkflowHash(screen,routeId)
  if(location.hash===next)return
  const previous=location.hash
  history[mode==='replace'?'replaceState':'pushState']({...(history.state||{}),photoScreen:screen,photoParent:previous},'',next)
}
function navigateBack(fallback='home'){
  if(history.state?.photoParent)history.back()
  else{writePhotoLocation(fallback,'','replace');applyPhotoLocation()}
}
async function choose(event){const file=event.target.files?.[0];event.target.value='';if(file){await workflow.choose(file);if(state.pending)writePhotoLocation('confirm')}}
async function chooseSample(sample){await workflow.choose(photoSampleFile(sample.url,sample.name));if(state.pending)writePhotoLocation('confirm')}
async function leaveConfirmation(){await workflow.discardPending();navigateBack('home')}

async function persistMembers(ids) {if(!editable.value || state.saving)return;failedMembers.value=[...ids]; members.value=[...ids];const value=await act('members',{member_ids:ids});if(value){failedMembers.value=null;members.value=value.route.members.map(m=>m.object_id)}}
function toggle(){if(!editable.value || !selected.value || state.saving)return;persistMembers(members.value.includes(selected.value)?members.value.filter(id=>id!==selected.value):[...members.value,selected.value])}

async function photoClick(event){
  if(!editable.value || state.saving)return
  const rect=event.currentTarget.getBoundingClientRect(), point=[(event.clientX-rect.left)/rect.width,(event.clientY-rect.top)/rect.height]
  if(!adding.value){
    const hit=pickPhotoObject(visibleObjects.value,[point[0]*board.value.width,point[1]*board.value.height],6*board.value.width/rect.width)
    selected.value=hit?.id || ''; return
  }
  if(adding.value){adding.value=false;await act('add',{point});return}
}
async function contour(){if(!editable.value || state.saving)return;try{await service.patchObject(board.value.id,selected.value,{expected_version:selectedObject.value.object_version,contour:JSON.parse(contourInput.value)});await workflow.refresh()}catch{localError.value='轮廓未保存，请检查坐标'}}
async function abandon(){if(!editable.value || state.saving)return;try{await ElMessageBox.confirm('放弃后可以开始下一条线路，已保存的线路不会改变。','放弃当前线路',{confirmButtonText:'放弃',cancelButtonText:'继续编辑'});await act('abandon')}catch{}}
async function save(){if(!editable.value || state.saving)return;const result=await act('save',{member_ids:members.value});if(result)await openDetail(result.route)}
async function returnCurrent(){if(await beforeLeave()){detail.value=null;view.value='current';navigateBack(photoWorkflowScreen(state))}}
async function returnFromLibrary(){if(await beforeLeave()){view.value='current';navigateBack(photoWorkflowScreen(state))}}
async function openLibrary(historyMode='push'){if(!(await beforeLeave()))return;library.value=(await service.routes({status:'completed'}));detail.value=null;view.value='library';writePhotoLocation('library','',historyMode)}
async function openDetail(route,historyMode='push'){detail.value=JSON.parse(JSON.stringify(route));detailBoard.value=await service.board(route.board_version_id);noteObject.value='';noteState.value='备注已保存';writePhotoLocation('route',route.id,historyMode)}
async function applyPhotoLocation(){
  if(!state.loaded)return
  const target=parsePhotoWorkflowHash(location.hash)
  if(target.screen==='outside')return
  if(target.screen==='confirm'){
    if(!state.pending){writePhotoLocation(photoWorkflowScreen(state),'','replace');return}
    detail.value=null;view.value='current';return
  }
  if(state.pending)await workflow.discardPending()
  if(target.screen==='library'){await openLibrary('replace');return}
  if(target.screen==='route'){
    try{await openDetail(await service.route(target.routeId),'replace')}
    catch{localError.value='这条线路暂时无法打开，已返回线路库';await openLibrary('replace')}
    return
  }
  detail.value=null;view.value='current'
  const expected=photoWorkflowScreen(state)
  if(isPhotoFlowScreen(target.screen)&&target.screen!==expected)writePhotoLocation(expected,'','replace')
}
function role(value){if(!editable.value || !noteMember.value)return;const roles=noteMember.value.roles;noteMember.value.roles=roles.includes(value)?roles.filter(r=>r!==value):[...roles,value];queueNotes()}
function updateMemberTags(event){if(!editable.value || !noteMember.value)return;noteMember.value.tags=event.target.value.split(/[,，]/).map(value=>value.trim()).filter(Boolean);queueNotes()}
function queueNotes(){
  if(!editable.value || !detail.value)return
  detail.value.request_id=crypto.randomUUID()
  noteState.value='等待保存备注'
  try{localStorage.setItem(noteKey,JSON.stringify(detail.value))}catch{localError.value='浏览器未能暂存备注，请保持页面打开直到保存完成'}
  clearTimeout(notesTimer);notesTimer=setTimeout(saveNotes,800)
}
async function saveNotes(){
  clearTimeout(notesTimer);if(notesPromise)await notesPromise
  if(!editable.value)return true
  if(!detail.value || noteState.value==='备注已保存')return true
  const pending=JSON.parse(JSON.stringify(detail.value));noteState.value='正在保存备注'
  notesPromise=(async()=>{try{const result=(await api.put(`/api/photo-routes/workflow/routes/${pending.id}/notes`,pending)).data;detail.value.version=result.version;noteState.value=JSON.stringify({...detail.value,version:pending.version})===JSON.stringify(pending)?'备注已保存':'等待保存备注';if(noteState.value!=='备注已保存')queueNotes();else localStorage.removeItem(noteKey);return true}catch{noteState.value='备注保存失败';return false}})()
  const result=await notesPromise;notesPromise=null;return result
}
async function beforeLeave(){if(failedMembers.value)return false;return (await saveNotes()) && await workflow.beforeLeave()}
function beforeUnload(event){if(failedMembers.value || ['等待保存备注','正在保存备注','备注保存失败'].includes(noteState.value)){event.preventDefault();event.returnValue=''}}
window.addEventListener('beforeunload',beforeUnload)
watch(()=>state.loaded,loaded=>{if(loaded)applyPhotoLocation()},{immediate:true})
watch(editable,canEdit=>{if(canEdit && detail.value && noteState.value==='等待保存备注')queueNotes()})
watch(()=>session.value?.status,status=>{if(!state.loaded||!status)return;const current=parsePhotoWorkflowHash(location.hash).screen;if(current==='confirm'||isPhotoFlowScreen(current))writePhotoLocation(photoWorkflowScreen(state),'','replace')})
onBeforeUnmount(()=>{state.interacting=false;clearTimeout(notesTimer);window.removeEventListener('beforeunload',beforeUnload);window.removeEventListener('hashchange',applyPhotoLocation)})
defineExpose({beforeLeave,returnCurrent})
</script>

<style scoped>
.photo-work{min-height:80dvh;padding:24px;color:var(--ui-ink);background:var(--ui-ground);accent-color:var(--ui-brand)}
.photo-work ::selection{color:var(--ui-brand-ink);background:var(--ui-brand)}
.photo-work__header,.photo-work__heading{display:flex;justify-content:space-between;align-items:center;gap:16px;margin-bottom:20px}
.photo-work h1{margin:0 0 6px;font-size:28px;line-height:1.2;letter-spacing:-.02em}.photo-work h2{margin:0;font-size:20px;line-height:1.35;letter-spacing:-.01em}.photo-work h3{margin:8px 0 0;font-size:15px}.photo-work p{margin:0;line-height:1.6}
.photo-work button{min-height:44px;padding:10px 16px;border:1px solid var(--ui-line-strong);border-radius:var(--ui-radius-control);background:var(--ui-surface);color:inherit;font:inherit;cursor:pointer;transition:transform 120ms cubic-bezier(.2,.8,.2,1),background-color 120ms ease,border-color 120ms ease,box-shadow 120ms ease}
.photo-work button:hover{background:var(--ui-brand-soft)}.photo-work button:active:not(:disabled){transform:scale(.975);background:var(--ui-brand-hover)}.photo-work button:disabled{opacity:.52;cursor:default}.photo-work button:focus-visible,.photo-work input:focus-visible,.photo-work textarea:focus-visible,.photo-work select:focus-visible{outline:2px solid var(--ui-focus);outline-offset:2px;box-shadow:0 0 0 4px var(--ui-focus-halo)}
.photo-work .photo-work__primary{border-color:var(--ui-brand);background:var(--ui-brand);color:var(--ui-brand-ink);font-weight:700}.photo-work .photo-work__primary:hover{border-color:var(--ui-brand-hover);background:var(--ui-brand-hover)}
.photo-work__actions,.photo-work__capture-actions,.photo-work__recovery{display:flex;flex-wrap:wrap;gap:12px}.photo-work__actions .photo-work__primary,.photo-work__capture-actions .photo-work__primary{flex:1}
.photo-work__button-spinner{display:inline-block;width:16px;height:16px;margin-right:8px;border:2px solid rgba(45,37,0,.25);border-top-color:var(--ui-brand-ink);border-radius:50%;vertical-align:-3px;animation:photo-work-spin .75s linear infinite}
.photo-work .photo-work__back{align-self:flex-start;display:inline-flex;align-items:center;gap:4px;margin-left:-10px;padding:8px 10px;border-color:transparent;background:transparent;font-weight:650}.photo-work .photo-work__back:hover{border-color:var(--ui-line);background:var(--ui-brand-soft)}.photo-work__back svg{width:20px;height:20px;fill:none;stroke:currentColor;stroke-width:2;stroke-linecap:round;stroke-linejoin:round}
.photo-work__offline,.photo-work__permission{display:flex;align-items:center;gap:12px;margin:0 0 14px;padding:11px 14px;border-radius:var(--ui-radius-small);font-size:13px}.photo-work__offline{background:#fff1ce;color:#59400b}.photo-work__permission{background:#eceae5;color:#484b50}.photo-work__offline span,.photo-work__permission span{color:inherit;opacity:.82}
.photo-work__quiet-note{color:var(--ui-ink-muted);font-size:12px}
.photo-work__layout{display:grid;grid-template-columns:minmax(0,1fr) 320px;gap:24px;min-height:380px;height:calc(100dvh - 250px);max-height:850px}.photo-work__layout>.photo-canvas-shell{min-width:0;height:100%;overflow:hidden}
.photo-work__tools{display:flex;flex-direction:column;gap:12px;overflow-y:auto;overscroll-behavior:contain;scrollbar-gutter:stable;padding:4px 12px 16px}.photo-work__tools label{display:flex;flex-direction:column;gap:6px}.photo-work__tools::-webkit-scrollbar{width:8px}.photo-work__tools::-webkit-scrollbar-thumb{border:2px solid transparent;border-radius:8px;background:var(--ui-line-strong);background-clip:padding-box}
.photo-work__save-bar{position:sticky;top:-4px;z-index:3;display:grid;grid-template-columns:minmax(140px,1fr) auto;align-items:center;gap:10px;margin:0 -4px;padding:10px 4px 12px;background:var(--ui-ground);border-bottom:1px solid var(--ui-line)}.photo-work__save-bar button{width:100%}.photo-work__save-bar>span{color:var(--ui-ink-muted);font-size:12px;white-space:nowrap}
.photo-work select,.photo-work input:not([type=checkbox]),.photo-work textarea{box-sizing:border-box;width:100%;padding:11px 12px;border:1px solid var(--ui-line-strong);border-radius:var(--ui-radius-control);background:var(--ui-surface);color:var(--ui-ink);font:inherit}.photo-work textarea{resize:vertical}.photo-work input::placeholder,.photo-work textarea::placeholder{color:var(--ui-ink-faint)}.photo-work input[type=checkbox]{flex:none;width:20px;height:20px;accent-color:#a77a00}.photo-work input:disabled,.photo-work textarea:disabled,.photo-work select:disabled{background:var(--ui-surface-subtle);color:var(--ui-ink-muted);cursor:not-allowed}.photo-work__checkbox-row{min-height:44px;flex-direction:row!important;align-items:center;gap:10px!important;cursor:pointer}
.photo-work__image{position:relative;width:100%;height:100%;overflow:hidden;background:#2b2b29}.photo-work__image img,.photo-work__plain{display:block;width:100%;height:100%;object-fit:contain}.photo-work__image svg{position:absolute;inset:0;width:100%;height:100%;overflow:visible}
.photo-work__image polygon{fill:transparent;stroke:rgba(255,255,255,.72);stroke-width:1.25;stroke-linejoin:round;cursor:pointer;vector-effect:non-scaling-stroke;transition:fill 140ms ease,stroke 140ms ease,filter 140ms ease,opacity 140ms ease}
.photo-work__image polygon:focus-visible{outline:none;stroke:#fff;stroke-width:4;filter:drop-shadow(0 0 2px #1c1e21) drop-shadow(0 2px 7px rgba(244,196,48,.92))}
.photo-work__image polygon.is-route-contour{fill:rgba(244,196,48,.05);stroke:var(--ui-brand);stroke-width:2.5}.photo-work__image polygon.is-route-contour.is-glow{filter:drop-shadow(0 0 2px rgba(255,222,70,.95)) drop-shadow(0 2px 6px rgba(244,196,48,.7))}.photo-work__image polygon.is-selected{fill:rgba(244,196,48,.12);stroke:#fff7c7;stroke-width:3.5;filter:drop-shadow(0 0 2px #2d2500) drop-shadow(0 2px 7px rgba(244,196,48,.9))}.photo-work__image polygon.is-excluded{fill:transparent;stroke:rgba(255,255,255,.68);stroke-width:1;stroke-dasharray:5 5;filter:none}.photo-work__image polygon.is-muted{fill:transparent;stroke:#6f6a60;stroke-width:1;stroke-opacity:.28;stroke-dasharray:5 5;filter:none}
.photo-work__image polygon.is-hidden-contour:not(.is-selected){opacity:0}
.photo-work__pending{display:grid;grid-template-columns:minmax(260px,1fr) minmax(280px,420px);gap:28px;align-items:center}.photo-work__pending>img{width:100%;height:55dvh;object-fit:contain;background:#282826;border-radius:var(--ui-radius-card)}.photo-work__pending-sheet{display:flex;flex-direction:column;gap:16px}.photo-work__upload{display:grid;place-items:center;min-height:52dvh;padding:32px;text-align:center}.photo-work__upload-copy{max-width:520px}.photo-work__upload h2{font-size:clamp(26px,4vw,42px)}.photo-work__upload p{max-width:52ch;margin:14px auto 24px;color:var(--ui-ink-muted)}.photo-work__capture-actions{justify-content:center}.photo-work__capture-actions button{min-width:156px}
.photo-work__samples{display:flex;gap:16px;justify-content:center;margin-top:24px}.photo-work__samples button{display:flex;flex-direction:column;gap:8px;max-width:180px;text-align:left}.photo-work__samples img{width:100%;height:150px;object-fit:cover;border-radius:8px}.photo-work__file{display:none}
.photo-work__processing{box-sizing:border-box;display:flex;align-items:center;justify-content:center;flex-direction:column;width:min(100%,560px);min-height:calc(100dvh - 260px);margin:0 auto;padding:48px 20px;text-align:center}.photo-work__processing--center{margin:auto;text-align:center}.photo-work__processing h2{margin:20px 0 8px;font-size:clamp(24px,3vw,34px)}.photo-work__processing>p{max-width:52ch;color:var(--ui-ink-muted)}.photo-work__processing progress{display:block;width:min(100%,460px);height:9px;margin:28px 0 18px;overflow:hidden;border:0;border-radius:999px;background:var(--ui-line);accent-color:var(--ui-brand)}.photo-work__processing progress::-webkit-progress-bar{border-radius:999px;background:var(--ui-line)}.photo-work__processing progress::-webkit-progress-value{border-radius:999px;background:var(--ui-brand)}.photo-work__processing progress::-moz-progress-bar{border-radius:999px;background:var(--ui-brand)}.photo-work__spinner{display:inline-block;width:42px;height:42px;border:4px solid var(--ui-line);border-top-color:#9f7500;border-radius:50%;animation:photo-work-spin .9s linear infinite}.photo-work__stage-list{display:flex;flex-direction:column;width:min(100%,420px);gap:8px;margin:0;padding:0;list-style:none;font-size:14px;text-align:left}.photo-work__stage-list li{display:grid;grid-template-columns:12px 1fr auto;align-items:center;gap:10px;min-height:32px;padding:4px 0;color:var(--ui-ink-muted)}.photo-work__stage-list small{font-size:12px;color:inherit}.photo-work__stage-dot{width:8px;height:8px;border-radius:50%;background:var(--ui-line-strong)}.photo-work__stage-list li.is-current{color:var(--ui-ink);font-weight:650}.photo-work__stage-list li.is-current .photo-work__stage-dot{background:var(--ui-brand);box-shadow:0 2px 9px rgba(244,196,48,.55);animation:photo-stage-pulse 1.4s ease-in-out infinite}.photo-work__stage-list li.is-done{color:var(--ui-ink-muted)}.photo-work__stage-list li.is-done .photo-work__stage-dot{background:#5b6b55}.photo-work__recovery{justify-content:center;margin-top:28px}.photo-stage-enter-active{transition:opacity 220ms ease,transform 280ms cubic-bezier(.16,1,.3,1),clip-path 280ms cubic-bezier(.16,1,.3,1)}.photo-stage-enter-from{opacity:0;transform:translateY(8px);clip-path:inset(0 0 100% 0)}
.photo-work__error{display:flex;justify-content:space-between;gap:12px;margin:0 0 14px;padding:12px;border-radius:var(--ui-radius-small);background:#fff0ed;color:#8c3027}.photo-work__inline-error{display:grid;gap:2px;padding:12px;border-radius:var(--ui-radius-small);background:#fff0ed;color:#8c3027}.photo-work__notice{padding:12px;border-radius:var(--ui-radius-small);background:var(--ui-brand-soft)}.photo-work__advanced,.photo-work__hold-list{margin-top:6px;padding-top:18px;border-top:1px solid var(--ui-line)}.photo-work__advanced summary,.photo-work__hold-list summary{display:flex;align-items:center;min-height:44px;cursor:pointer;font-weight:600}.photo-work__hold-list>div{display:grid;gap:6px;padding-top:8px}.photo-work__hold-list button{width:100%;text-align:left}.photo-work__hold-list button.is-selected{border-color:#806000;background:var(--ui-brand-soft)}.photo-work__library-item{display:block;width:100%;margin:12px 0;text-align:left}
.photo-work__color{display:flex;align-items:center;gap:12px;text-align:left}.photo-work__color[aria-pressed=true]{border-color:#806000;background:var(--ui-brand-soft);box-shadow:inset 0 0 0 1px #806000}.photo-work__swatch{flex:none;width:22px;height:22px;border:1px solid #746e60;border-radius:50%}.photo-work__count{margin-left:auto;font-variant-numeric:tabular-nums}.photo-work__selection{padding:10px 12px;border-radius:var(--ui-radius-small);background:var(--ui-brand-soft)}
.photo-work__toggle{flex-direction:row!important;align-items:center;justify-content:space-between;min-height:44px}.photo-work__toggle input{appearance:none;position:relative;width:48px!important;height:28px!important;margin:0;border-radius:14px;background:var(--ui-line-strong);transition:background-color 120ms ease}.photo-work__toggle input::after{position:absolute;top:3px;left:3px;width:22px;height:22px;border-radius:50%;background:#fff;box-shadow:0 2px 6px rgba(0,0,0,.18);content:"";transition:transform 140ms cubic-bezier(.2,.8,.2,1)}.photo-work__toggle input:checked{background:var(--ui-brand)}.photo-work__toggle input:checked::after{transform:translateX(20px)}
.photo-work__mobile-command{display:none}
@keyframes photo-work-spin{to{transform:rotate(360deg)}}@keyframes photo-stage-pulse{50%{transform:scale(1.35);box-shadow:0 2px 12px rgba(244,196,48,.75)}}
@media(prefers-reduced-motion:reduce){.photo-work button,.photo-work__image polygon,.photo-work__toggle input,.photo-work__toggle input::after,.photo-stage-enter-active{transition:none}.photo-work__spinner,.photo-work__button-spinner,.photo-work__stage-list li.is-current .photo-work__stage-dot{animation:none}}
@media(max-width:860px){
  .photo-work{box-sizing:border-box;min-height:calc(100dvh - var(--ui-shell-top) - var(--ui-shell-bottom));padding:16px 12px calc(88px + env(safe-area-inset-bottom));overflow-x:hidden}
  .photo-work__header{margin-bottom:18px}.photo-work__header h1{font-size:26px}.photo-work__header p{font-size:13px;color:var(--ui-ink-muted)}
  .photo-work--processing .photo-work__header,.photo-work--failed .photo-work__header,.photo-work--awaiting_color .photo-work__header,.photo-work--ready .photo-work__header,.photo-work--capture-preview .photo-work__header{display:none}
  .photo-work__heading{align-items:flex-start;margin-bottom:14px}.photo-work__heading h2{font-size:22px}
  .photo-work__offline,.photo-work__permission{align-items:flex-start;flex-direction:column;gap:2px}
  .photo-work__layout{display:flex;flex-direction:column;gap:0;height:auto;max-height:none}.photo-work__layout>:first-child{flex:none;width:calc(100% + 24px);height:58dvh;min-height:360px;margin-left:-12px;border-radius:0}.photo-work__layout>.photo-canvas-shell{height:auto}
  .photo-work__tools{position:relative;z-index:2;max-height:none;margin:-20px -12px 0;padding:18px 20px calc(22px + env(safe-area-inset-bottom));overflow:visible;border-radius:20px 20px 0 0;background:var(--ui-surface);box-shadow:0 -12px 28px rgba(28,30,33,.12)}
  .photo-work__tools>h2:first-child{font-size:20px}.photo-work__tools>button.photo-work__primary{width:100%;min-height:48px;margin-top:4px}
  .photo-work__save-bar{top:0;grid-template-columns:1fr;margin:0 -8px;padding:10px 8px;background:var(--ui-surface)}.photo-work__save-bar>span{text-align:center;white-space:normal}
  .photo-work__pending{display:flex;flex-direction:column;gap:0;margin:-16px -12px 0}.photo-work__pending>img{width:100%;height:60dvh;border-radius:0;object-fit:contain}.photo-work__pending-sheet{position:relative;margin-top:-20px;padding:20px 20px calc(24px + env(safe-area-inset-bottom));border-radius:20px 20px 0 0;background:var(--ui-surface);box-shadow:0 -12px 28px rgba(28,30,33,.12)}.photo-work__actions{display:grid;grid-template-columns:1fr 1.6fr}.photo-work__actions button{width:100%}
  .photo-work__upload{min-height:48dvh;padding:18px 8px}.photo-work__upload h2{font-size:30px;line-height:1.18}.photo-work__capture-actions{display:grid;width:100%;max-width:350px;grid-template-columns:1fr}.photo-work__capture-actions button{width:100%;min-width:0}.photo-work__samples{display:grid;grid-template-columns:1fr 1fr;gap:10px}.photo-work__samples button{max-width:none;padding:8px}.photo-work__samples img{height:120px}
  .photo-work__processing{min-height:calc(100dvh - var(--ui-shell-bottom) - 32px);padding:32px 8px}.photo-work__processing.is-failed{padding-top:30px}.photo-work__stage-list{width:min(100%,340px)}.photo-work__recovery{display:grid;width:min(100%,340px);grid-template-columns:1fr}.photo-work__recovery button{width:100%}
  .photo-work--ready{padding-bottom:calc(184px + env(safe-area-inset-bottom))}.photo-work--ready .photo-work__tools{padding-bottom:calc(132px + env(safe-area-inset-bottom))}
  .photo-work__desktop-review-action{display:none}
  .photo-work__mobile-command{position:fixed;z-index:90;right:12px;bottom:calc(var(--ui-shell-bottom) + 8px);left:12px;display:grid;grid-template-columns:1fr 1fr;gap:8px;padding:10px;border:1px solid var(--ui-line);border-radius:14px;background:rgba(255,255,255,.98);box-shadow:0 12px 30px rgba(28,30,33,.2)}.photo-work__mobile-command>span{grid-column:1/-1;color:var(--ui-ink-muted);font-size:12px;text-align:center}.photo-work__mobile-command button{width:100%;min-height:48px;padding-inline:10px}
}
</style>
