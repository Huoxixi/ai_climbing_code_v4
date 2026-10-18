<template>
  <div class="web-app">
    <header class="web-header">
      <button class="web-brand" type="button" @click="navigate('replay')">攀岩助手<span>网页版</span></button>
      <nav aria-label="主导航"><button v-for="item in tabs" :key="item.id" type="button" :aria-current="page===item.id?'page':undefined" @click="navigate(item.id)"><component :is="item.icon"/><span>{{item.label}}</span></button></nav>
      <div class="web-tools"><a href="/downloads/climbing-assistant-windows.exe" download><Download/><span>下载桌面版</span></a><button type="button" aria-label="本机存储" @click="navigate('storage')"><Setting/></button></div>
    </header>
    <div class="web-main">
      <BrowserReplay v-show="page==='replay'" :key="opened?opened.owner+':'+opened.id:'new:'+newSequence" :record="opened" embedded @busy="working=$event" @saved="historyChanged" @back="navigate('history')" />
      <section v-if="page==='history'" class="web-page records-page" aria-labelledby="records-title">
        <div class="web-page-heading"><h1 id="records-title">我的记录</h1><button class="web-primary" type="button" :disabled="working||openingRecord" @click="newReplay">新建复盘</button></div>
        <p class="muted">视频和复盘结果只保存在当前浏览器，无需账号。同一浏览器中的记录在这里统一展示；换设备或清除网站数据后不会自动恢复。</p>
        <p v-if="historyError" class="web-error" role="alert">{{historyError}}</p>
        <p v-if="readingHistory" role="status">正在读取本机记录…</p>
        <div v-else-if="!records.length" class="records-empty"><Collection aria-hidden="true"/><h2>还没有本机记录</h2><p>完成一次复盘后，会自动保存在这里。</p><button class="web-primary" type="button" :disabled="working" @click="newReplay">选择攀岩视频</button></div>
        <ul v-else class="record-list"><li v-for="record in records" :key="record.owner+':'+record.id"><div class="record-symbol"><VideoCamera/></div><div class="record-description"><strong>{{record.name}}</strong><span>{{date(record.created_at)}} · {{Number(record.duration||0).toFixed(1)}} 秒 · {{formatBytes(record.bytes)}}</span><small>{{record.observed}} / {{record.samples}} 个时刻有骨架观测</small></div><button class="web-secondary" type="button" :disabled="working||openingRecord" @click="openRecord(record)">打开</button><button type="button" class="web-icon-button" :disabled="working||openingRecord" :aria-label="'删除记录：'+record.name" @click="pendingDelete=record"><Delete/></button></li></ul>
      </section>
      <section v-if="page==='storage'" class="web-page settings-page" aria-labelledby="storage-title">
        <div class="web-page-heading"><h1 id="storage-title">本机存储</h1></div>
        <section><h2>当前浏览器</h2><p>当前网站使用约 {{formatBytes(storage.usage)}}<span v-if="storage.quota">，浏览器存储额度约 {{formatBytes(storage.quota)}}</span>。包含模型缓存和本机记录。</p><p class="muted">{{storage.persisted?'浏览器已允许持久存储。主动清除网站数据仍会删除本机记录。':'可申请保留本机数据，减少浏览器自动清理；是否允许由浏览器决定。'}} 换浏览器或换电脑不会同步视频和历史记录。</p><button v-if="!storage.persisted" type="button" class="web-secondary" @click="persistStorage">申请保留本机数据</button></section>
        <section><h2>桌面版</h2><a class="desktop-link" href="/downloads/climbing-assistant-windows.exe" download><Download/>下载 Windows 安装包</a><p class="muted">0.1.17 · 2026.10.10 安装包</p><a class="desktop-link" href="/browser-models/NOTICE.txt" target="_blank" rel="noopener">开源许可</a></section>
        <p v-if="storageMessage" role="status">{{storageMessage}}</p><p v-if="storageError" class="web-error" role="alert">{{storageError}}</p>
      </section>
    </div>
    <dialog ref="deleteDialog" class="web-dialog" aria-labelledby="delete-title" @cancel.prevent="pendingDelete=null"><h2 id="delete-title">删除这条本机记录？</h2><p>{{pendingDelete?.name}}</p><p class="muted">仅删除这条记录在当前浏览器中保存的视频副本和复盘结果，原视频文件不受影响。删除后无法从网站恢复。</p><div class="dialog-actions"><button type="button" class="web-secondary" :disabled="deleting" @click="pendingDelete=null">取消</button><button type="button" class="web-danger" :disabled="deleting" @click="deleteRecord">确认删除</button></div></dialog>
  </div>
</template>
<script setup>
import {onBeforeUnmount,onMounted,ref,watch} from 'vue'
import {VideoCamera,Collection,Setting,Delete,Download} from '@element-plus/icons-vue'
import BrowserReplay from './BrowserReplay.vue'
import {listLocalHistory,readHistory,removeHistory,localStorageInfo,requestPersistentStorage} from './localHistory.js'
const tabs=[{id:'replay',label:'视频复盘',icon:VideoCamera},{id:'history',label:'我的记录',icon:Collection}]
const page=ref('replay'),working=ref(false),opened=ref(null),newSequence=ref(0),records=ref([]),readingHistory=ref(false),openingRecord=ref(false),historyError=ref(''),pendingDelete=ref(null),deleteDialog=ref(),deleting=ref(false)
const storage=ref({usage:0,quota:0,persisted:false}),storageMessage=ref(''),storageError=ref('')
const date=value=>new Intl.DateTimeFormat('zh-CN',{dateStyle:'medium',timeStyle:'short'}).format(new Date(value))
const formatBytes=bytes=>bytes>=1024**3?(bytes/1024**3).toFixed(2)+' GB':(bytes/1024**2).toFixed(1)+' MB'
async function navigate(value){page.value=value;if(value==='history')await refreshHistory();if(value==='storage')storage.value=await localStorageInfo()}
async function refreshHistory(){readingHistory.value=true;historyError.value='';try{records.value=await listLocalHistory()}catch(e){historyError.value=e.message}finally{readingHistory.value=false}}
function historyChanged(){if(page.value==='history')refreshHistory()}
function newReplay(){if(working.value||openingRecord.value)return;opened.value=null;newSequence.value++;page.value='replay'}
async function openRecord(record){if(working.value||openingRecord.value)return;openingRecord.value=true;historyError.value='';try{opened.value=await readHistory(record.owner,record.id);page.value='replay'}catch(e){historyError.value=e.message}finally{openingRecord.value=false}}
async function deleteRecord(){const record=pendingDelete.value;if(!record||deleting.value)return;deleting.value=true;try{await removeHistory(record.owner,record.id);if(opened.value?.id===record.id&&opened.value?.owner===record.owner)opened.value=null;pendingDelete.value=null;await refreshHistory()}catch(e){historyError.value=e.message;pendingDelete.value=null}finally{deleting.value=false}}
watch(pendingDelete,value=>{if(value){if(deleteDialog.value&&!deleteDialog.value.open)deleteDialog.value.showModal()}else deleteDialog.value?.close()},{flush:'post'})
async function persistStorage(){storageMessage.value='';storageError.value='';try{const persisted=await requestPersistentStorage();storage.value=await localStorageInfo();storageMessage.value=persisted?'已允许保留本机数据。':'浏览器暂未允许持久存储，现有记录未被删除。'}catch{storageError.value='浏览器暂不支持此设置，现有记录保留。'}}
function beforeUnload(event){if(working.value){event.preventDefault();event.returnValue=''}}
onMounted(()=>window.addEventListener('beforeunload',beforeUnload))
onBeforeUnmount(()=>window.removeEventListener('beforeunload',beforeUnload))
</script>
