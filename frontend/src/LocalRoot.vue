<template>
  <div v-if="loading || !session.authenticated" class="pilot-loading">
    <div class="pilot-loading-card">
      <strong>{{ loading ? '正在检查登录状态' : signedOut ? '已退出登录' : '暂时无法连接本地服务' }}</strong>
      <p v-if="signedOut">本地账号 owner · 负责人</p>
      <p>照片和线路进度已保留。</p>
      <el-button v-if="!loading" type="primary" @click="localLogin">{{ signedOut ? '登录本地账号' : '重新连接' }}</el-button>
    </div>
  </div>
  <LocalApp v-else :key="session.username" />
</template>
<script setup>
import { onMounted, provide, reactive, ref } from 'vue'
import LocalApp from './LocalApp.vue'
import apiClient from './services/apiClient'
import { localWorkspaceHash } from './utils/localWorkspace.js'
const loading=ref(true), signedOut=ref(sessionStorage.getItem('local-account-signed-out')==='true')
const session=reactive({authenticated:false,username:'',displayName:'',authEnabled:false})
provide('localWorkspaceOnly',true)
provide('pilotAccess',{session,lease:reactive({active:false,ownedByMe:false}),logout})
sessionStorage.setItem('climbing-active-workspace','boulder')
history.replaceState(null,'',localWorkspaceHash(location.hash))
async function loadSession(){
  loading.value=true
  try{
    const {data}=await apiClient.get('/api/auth/session')
    Object.assign(session,{authenticated:!!data.authenticated && !signedOut.value,username:data.username||'',displayName:data.display_name||'',authEnabled:data.auth_enabled!==false})
  }catch{session.authenticated=false}finally{loading.value=false}
}
async function localLogin(){signedOut.value=false;sessionStorage.removeItem('local-account-signed-out');await loadSession()}
async function logout(){
  await apiClient.post('/api/auth/logout')
  sessionStorage.setItem('local-account-signed-out','true')
  signedOut.value=true;session.authenticated=false
  history.replaceState(null,'','#/photo-routes')
}
onMounted(loadSession)
</script>
