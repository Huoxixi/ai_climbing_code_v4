import { computed, reactive } from 'vue'
import api from '../services/apiClient.js'
import { isHeifPhoto } from '../utils/mediaNormalize.js'

const root = '/api/photo-routes/workflow'
function pendingStore(user, value, write = false) {
  return new Promise((resolve,reject) => {
    const request=indexedDB.open('photo-route-pending',1)
    request.onupgradeneeded=()=>request.result.createObjectStore('photos')
    request.onerror=()=>reject(request.error)
    request.onsuccess=()=>{
      const db=request.result, transaction=db.transaction('photos',write?'readwrite':'readonly'), store=transaction.objectStore('photos')
      let operation
      try { operation=write ? (value ? store.put({id:value.id,file:value.file},user) : store.delete(user)) : store.get(user) }
      catch(error) { db.close(); reject(error); return }
      let result
      operation.onsuccess=()=>{ result=operation.result }
      transaction.oncomplete=()=>{ db.close(); resolve(result) }
      transaction.onerror=()=>{ db.close(); reject(transaction.error) }
    }
  })
}

export function createPhotoWorkflow(user) {
  const state=reactive({session:null,pending:null,pendingChange:null,preview:'',uploading:false,uploadProgress:0,saving:false,interacting:false,error:'',loaded:false,connectionLost:false})
  const recoveryKey='photo-route-change:'+user
  let timer, disposed=false, reading=false, mutation=Promise.resolve(), pendingWrite=Promise.resolve(), generation=0, queued=0
  const busy=computed(()=>state.uploading || state.session?.status==='processing')
  function apply(value) {
    if (disposed) return
    if (value && state.session?.id===value.id && value.version<state.session.version) return
    state.session=value
  }
  function preview(file) { if(state.preview) URL.revokeObjectURL(state.preview); state.preview=file && !isHeifPhoto(file)?URL.createObjectURL(file):'' }
  async function refresh() {
    if(reading || state.uploading || state.saving || state.interacting || disposed) return
    reading=true
    const started=generation
    try {
      const value=(await api.get(root+'/current')).data
      if(started===generation && (value || !['saved','abandoned'].includes(state.session?.status))) apply(value)
      state.connectionLost=false
    } catch { state.connectionLost=true }
    finally { reading=false }
  }
  async function init() {
    await refresh()
    try {
      const pending=await pendingStore(user)
      if(!state.session && pending) { state.pending=pending; preview(pending.file) }
      else if(state.session && pending) await pendingStore(user,null,true)
    } catch { state.error='浏览器未允许暂存照片；关闭页面前请确认上传。' }
    try {
      const recovery=JSON.parse(localStorage.getItem(recoveryKey)||'null')
      if(recovery && !state.session) apply((await api.get(`${root}/${recovery.sid}`)).data)
      if(recovery && state.session?.id===recovery.sid) {
        state.pendingChange=recovery
        await change(recovery.action,recovery.payload).catch(()=>{})
      }
    } catch { state.error='未能恢复未完成的修改，请保持页面打开并重试。' }
    state.loaded=true; timer=setInterval(refresh,1800)
  }
  async function choose(file) {
    if(state.uploading || (state.session && !['saved','abandoned'].includes(state.session.status))) return
    if(!file || !file.size) { state.error='照片内容为空，请重新选择照片。'; return }
    generation++
    state.session=null; state.error=''; state.pending={id:crypto.randomUUID(),file}; preview(file)
    pendingWrite=pendingStore(user,state.pending,true)
    try { await pendingWrite } catch { state.error='照片已选中，但浏览器暂存失败；请保持页面打开直到确认上传。' }
  }
  async function discardPending() {
    if(state.uploading || !state.pending) return
    generation++; state.pending=null; preview(null); state.error=''
    await pendingWrite.catch(()=>{})
    pendingWrite=pendingStore(user,null,true)
    try { await pendingWrite } catch { state.error='已返回，但照片草稿未能清除；重新打开页面时可能需要再次返回。' }
  }
  async function upload() {
    if(!state.pending || state.uploading) return
    if(!state.pending.file || !state.pending.file.size) { state.error='照片内容为空，请返回并重新选择照片。'; return }
    state.uploading=true; state.uploadProgress=0; state.error=''; generation++
    try {
      const body=new FormData(); body.append('photo',state.pending.file); body.append('request_id',state.pending.id)
      apply((await api.post(root+'/upload',body,{timeout:120000,onUploadProgress:event=>{if(event.total)state.uploadProgress=Math.round(event.loaded/event.total*100)}})).data)
      state.pending=null; preview(null); await pendingWrite.catch(()=>{}); try { await pendingStore(user,null,true) } catch { /* Server already owns the uploaded photo. */ }
    } catch(error) { state.error=typeof error.response?.data?.detail==='string'?error.response.data.detail:'上传未完成，照片已保留，请重试'; }
    finally { state.uploading=false }
  }
  function change(action, payload={}) {
    state.saving=true; queued++; generation++
    const sid=state.session?.id
    mutation=mutation.catch(()=>{}).then(async()=>{
      if(!state.session || state.session.id!==sid) return
      try {
        const recovery=state.pendingChange
        if(recovery && action!=='abandon' && (recovery.action!==action || JSON.stringify(recovery.payload)!==JSON.stringify(payload))) throw new Error('请先重试未保存的修改')
        const request=recovery && action!=='abandon'?recovery:{sid,action,payload,body:{version:state.session.version,request_id:crypto.randomUUID(),...payload}}
        if(action!=='viewed') {
          localStorage.setItem(recoveryKey,JSON.stringify(request))
          state.pendingChange=request
        }
        const value=(await api.post(`${root}/${state.session.id}/${action}`,request.body)).data
        if(action!=='viewed') {localStorage.removeItem(recoveryKey);state.pendingChange=null}
        apply(value); state.error=''; return value
      } catch(error) {
        state.error=typeof error.response?.data?.detail==='string'?error.response.data.detail:'保存未完成，修改已在浏览器保留，请重试'
        throw error
      }
    }).finally(()=>{queued--; state.saving=queued>0})
    return mutation
  }
  async function beforeLeave() { try { await mutation; return true } catch { return false } }
  function close() { disposed=true; clearInterval(timer); if(state.preview)URL.revokeObjectURL(state.preview) }
  return {state,busy,init,refresh,choose,discardPending,upload,change,beforeLeave,close}
}
