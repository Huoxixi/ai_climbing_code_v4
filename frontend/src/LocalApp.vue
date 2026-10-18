<template>
  <LocalShell :active="activePage" :title="title" :hold-count="status.count" :dirty="status.dirty" :save-label="status.label" :show-sync="isPhotoPage" @update:active="changePage" @close-settings="changePage(settingsReturnPage,{replace:true})">
    <div v-if="!isPhotoPage && activePage!=='climb-replay' && (photoWork.state.uploading || (photoWork.state.session && !['saved','abandoned'].includes(photoWork.state.session.status)))" class="photo-task-notice" role="status">
      <span>{{ photoWork.state.uploading ? '照片正在上传，可以继续使用其他功能' : photoWork.state.session.stage || '照片草稿' }}</span>
      <button type="button" @click="returnPhotoWork">查看当前线路</button>
      <span v-if="photoWork.state.connectionLost">暂时断开，正在重新连接</span>
    </div>
    <SettingsPage v-if="activePage==='settings'"  />
    <ClimbReplayPage v-else-if="activePage==='climb-replay'" />
    <PhotoRouteWorkflowPage v-else :key="activePage" :entry="activePage==='my-records'?'records':'capture'" ref="photoPage" @navigate="changePage" />
  </LocalShell>
</template>
<script setup>
import { computed, inject, nextTick, onBeforeUnmount, onMounted, provide, ref } from 'vue'
import LocalShell from './components/LocalShell.vue'
import SettingsPage from './components/LocalSettingsPage.vue'
import ClimbReplayPage from './components/LocalClimbReplayPage.vue'
import PhotoRouteWorkflowPage from './components/PhotoRouteWorkflowPage.vue'
import { createPhotoWorkflow } from './composables/usePhotoWorkflow'
import { localWorkspaceHash } from './utils/localWorkspace.js'
const pageFromHash=()=>localWorkspaceHash(location.hash).replace(/^#\/?/,'').split('/')[0]
const activePage=ref(pageFromHash()),settingsReturnPage=ref(activePage.value==='settings'?'photo-routes':activePage.value),photoPage=ref(null)
const photoWork=createPhotoWorkflow(inject('pilotAccess').session.username||'local')
provide('photoWorkflow',photoWork)
const isPhotoPage=computed(()=>['photo-routes','my-records'].includes(activePage.value))
const status=computed(()=>({count:photoWork.state.session?.route?.members.length||0,dirty:!!photoWork.state.pendingChange,label:photoWork.state.saving?'保存中…':photoWork.state.session?.stage||'已同步'}))
const title=computed(()=>({'photo-routes':'拍照定线','my-records':'我的记录','climb-replay':'AI 复盘',settings:'设置'}[activePage.value]))
async function changePage(page,{fromHistory=false,replace=false}={}){
  if(!['photo-routes','my-records','climb-replay','settings'].includes(page))page='photo-routes'
  if(page===activePage.value){
    if(page==='photo-routes')await photoPage.value?.openCurrent()
    if(page==='my-records')await photoPage.value?.openLibrary()
    return
  }
  if(isPhotoPage.value && photoPage.value && !(await photoPage.value.beforeLeave())){
    if(fromHistory)history.replaceState(null,'',`#/${activePage.value}`)
    return
  }
  if(page==='settings')settingsReturnPage.value=activePage.value
  activePage.value=page
  if(!fromHistory)history[replace?'replaceState':'pushState'](null,'',`#/${page}`)
}
function hashChanged(){
  const hash=localWorkspaceHash(location.hash)
  if(hash!==location.hash)history.replaceState(null,'',hash)
  changePage(pageFromHash(),{fromHistory:true})
}
async function returnPhotoWork(){await changePage('photo-routes');await nextTick();if(activePage.value==='photo-routes'){await photoPage.value?.returnCurrent();if(photoWork.state.session?.status==='ready')await photoWork.change('viewed').catch(()=>{})}}
onMounted(()=>{photoWork.init();window.addEventListener('hashchange',hashChanged)})
onBeforeUnmount(()=>{photoWork.close();window.removeEventListener('hashchange',hashChanged)})
</script>
