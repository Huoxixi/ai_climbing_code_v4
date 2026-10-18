const DB_NAME='climbing-browser-history-v1'
export const LOCAL_HISTORY_OWNER='00000000000000000000000000000000'
let opening
const validOwner=owner=>{if(typeof owner!=='string'||!/^[a-f0-9]{32}$/.test(owner))throw new Error('本机记录标识无效，请刷新页面后重试。');return owner}
function database(){
  if(!opening)opening=new Promise((resolve,reject)=>{
    const request=indexedDB.open(DB_NAME,1)
    request.onupgradeneeded=()=>{
      const db=request.result
      const records=db.createObjectStore('records',{keyPath:['owner','id']});records.createIndex('owner','owner')
      db.createObjectStore('content',{keyPath:['owner','id']})
    }
    request.onsuccess=()=>{const db=request.result;db.onversionchange=()=>{db.close();opening=null};resolve(db)}
    request.onerror=()=>{opening=null;reject(new Error('浏览器无法打开本机记录，请检查存储设置。'))}
    request.onblocked=()=>{opening=null;reject(new Error('其他标签页正在更新本机记录，请关闭旧标签页后重试。'))}
  })
  return opening
}
function completed(transaction){
  return new Promise((resolve,reject)=>{
    transaction.oncomplete=()=>resolve()
    transaction.onabort=()=>reject(new Error(transaction.error?.name==='QuotaExceededError'?'本机空间不足，记录尚未保存。请释放空间后重新保存。':'本机记录保存失败。原有记录仍保留，请重试。'))
    transaction.onerror=()=>{} // onabort reports the final transaction outcome.
  })
}
function result(request){return new Promise((resolve,reject)=>{request.onsuccess=()=>resolve(request.result);request.onerror=()=>reject(new Error('本机记录读取失败，请重试。'))})}
export async function saveReplay(owner,{id=crypto.randomUUID(),name,video,analysis}){
  validOwner(owner)
  if(!(video instanceof Blob)||!video.size||!analysis?.complete||!Array.isArray(analysis.pose_samples))throw new Error('分析未完成或原视频不可用，暂不能保存记录。')
  const metadata={owner,id,name:String(name||'攀岩复盘').slice(0,200),kind:'replay',created_at:Date.now(),duration:analysis.video.duration_seconds,bytes:video.size,observed:analysis.pose_samples.filter(s=>s.observed).length,samples:analysis.pose_samples.length}
  const db=await database(),tx=db.transaction(['records','content'],'readwrite'),done=completed(tx)
  try{tx.objectStore('records').put(metadata);tx.objectStore('content').put({owner,id,video,analysis})}catch(e){tx.abort();await done;throw e}
  await done;return metadata
}
export async function listHistory(owner){
  validOwner(owner);const db=await database(),tx=db.transaction('records','readonly')
  return (await result(tx.objectStore('records').index('owner').getAll(IDBKeyRange.only(owner)))).sort((a,b)=>b.created_at-a.created_at)
}
export async function readHistory(owner,id){
  validOwner(owner);const db=await database(),tx=db.transaction(['records','content'],'readonly')
  const [metadata,content]=await Promise.all([result(tx.objectStore('records').get([owner,id])),result(tx.objectStore('content').get([owner,id]))])
  if(!metadata||!content)throw new Error('这条本机记录不存在或已被清理。')
  return {...metadata,...content}
}
// Keep legacy records in place; this browser now presents one local library.
export async function listLocalHistory(){
  const db=await database(),tx=db.transaction('records','readonly')
  return (await result(tx.objectStore('records').getAll())).sort((a,b)=>b.created_at-a.created_at)
}
export async function removeHistory(owner,id){
  validOwner(owner);const db=await database(),tx=db.transaction(['records','content'],'readwrite'),done=completed(tx)
  tx.objectStore('records').delete([owner,id]);tx.objectStore('content').delete([owner,id]);await done
}
export async function localStorageInfo(){
  try{const estimate=await navigator.storage?.estimate();return {usage:estimate?.usage||0,quota:estimate?.quota||0,persisted:await navigator.storage?.persisted?.()||false}}catch{return {usage:0,quota:0,persisted:false}}
}
export async function requestPersistentStorage(){return !!(await navigator.storage?.persist?.())}
