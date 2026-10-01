import test from 'node:test'
import assert from 'node:assert/strict'
import api from '../src/services/apiClient.js'
import {createPhotoWorkflow} from '../src/composables/usePhotoWorkflow.js'

function setup(handler) {
  const saved=new Map(), photos=new Map()
  globalThis.localStorage={getItem:k=>saved.get(k)||null,setItem:(k,v)=>saved.set(k,v),removeItem:k=>saved.delete(k)}
  globalThis.indexedDB={open(){
    const request={}
    queueMicrotask(()=>{
      request.result={close(){},transaction(){
        const tx={objectStore(){return {
          put(value,key){const copy=structuredClone(value);photos.set(key,copy);return finish(copy)},
          get(key){return finish(photos.get(key))},delete(key){photos.delete(key);return finish()}
        }}}
        function finish(value){const op={result:value};queueMicrotask(()=>{op.onsuccess?.();tx.oncomplete?.()});return op}
        return tx
      }}
      request.onsuccess()
    })
    return request
  }}
  api.defaults.adapter=async config=>({data:await handler(config),status:200,statusText:'OK',headers:{},config})
  return {saved,photos}
}
const ready={id:'session',version:4,status:'ready',route:{members:[{object_id:'a'}]}}
const tick=()=>new Promise(resolve=>setTimeout(resolve,0))

test('chosen photo survives structured-clone storage and reopen without upload',async()=>{
  let posts=0; setup(config=>{if(config.method==='post')posts++;return null})
  const first=createPhotoWorkflow('owner');await first.init()
  await first.choose(new File(['image bytes'],'sample.jpg',{type:'image/jpeg'}));first.close()
  const restored=createPhotoWorkflow('owner');await restored.init()
  assert.equal(await restored.state.pending.file.text(),'image bytes');assert.equal(posts,0);restored.close()
})

test('returning from photo confirmation clears only the unuploaded draft',async()=>{
  const {photos}=setup(()=>null)
  const flow=createPhotoWorkflow('owner');await flow.init()
  await flow.choose(new File(['image bytes'],'sample.jpg',{type:'image/jpeg'}))
  assert.equal(photos.has('owner'),true)
  await flow.discardPending()
  assert.equal(flow.state.pending,null);assert.equal(flow.state.preview,'');assert.equal(photos.has('owner'),false)
  flow.close()
})

test('sample upload sends the selected file bytes instead of an empty multipart field',async()=>{
  let uploaded
  setup(async config=>{
    if(config.method==='post') {
      uploaded=config.data.get('photo')
      return ready
    }
    return null
  })
  const flow=createPhotoWorkflow('owner');await flow.init()
  await flow.choose(new File(['real sample bytes'],'sample.jpg',{type:'image/jpeg'}))
  await flow.upload()
  assert.equal(uploaded.name,'sample.jpg')
  assert.equal(uploaded.size,17)
  assert.equal(await uploaded.text(),'real sample bytes')
  assert.equal(flow.state.error,'')
  flow.close()
})

test('empty photo is rejected before confirmation or network upload',async()=>{
  let posts=0
  setup(config=>{if(config.method==='post')posts++;return null})
  const flow=createPhotoWorkflow('owner');await flow.init()
  await flow.choose(new File([],'empty.jpg',{type:'image/jpeg'}))
  assert.equal(flow.state.pending,null)
  assert.equal(flow.state.error,'照片内容为空，请重新选择照片。')
  await flow.upload()
  assert.equal(posts,0)
  flow.close()
})

test('a stale poll cannot replace the result of a mutation',async()=>{
  let resolvePoll
  setup(config=>config.method==='get'?new Promise(resolve=>{resolvePoll=resolve}):{...ready,version:5})
  const flow=createPhotoWorkflow('owner');flow.state.session=ready
  const polling=flow.refresh();await tick();await flow.change('members',{member_ids:['a']})
  resolvePoll(null);await polling;assert.equal(flow.state.session.version,5);flow.close()
})

test('lost response retries the identical version and request ID after reopening',async()=>{
  const bodies=[];let failure=true
  setup(config=>{
    if(config.method==='get')return ready
    bodies.push(JSON.parse(config.data));if(failure)throw new Error('offline')
    return {...ready,version:5}
  })
  const first=createPhotoWorkflow('owner');await first.init()
  await assert.rejects(first.change('members',{member_ids:[]}));first.close();failure=false
  const restored=createPhotoWorkflow('owner');await restored.init()
  assert.deepEqual(bodies[0],bodies[1]);assert.equal(restored.state.pendingChange,null);restored.close()
})

test('queued requests keep saving state until the last request finishes',async()=>{
  const releases=[]
  setup(()=>new Promise(resolve=>releases.push(resolve)))
  const flow=createPhotoWorkflow('owner');flow.state.session=ready
  const a=flow.change('viewed'),b=flow.change('viewed');await tick()
  releases.shift()({...ready,version:5});await a;await tick();assert.equal(flow.state.saving,true)
  releases.shift()({...ready,version:6});await b;assert.equal(flow.state.saving,false);flow.close()
})

test('polling does not replace an object while its board position is being adjusted',async()=>{
  let gets=0
  setup(config=>{if(config.method==='get')gets++;return ready})
  const flow=createPhotoWorkflow('owner');flow.state.session=ready;flow.state.interacting=true
  await flow.refresh();assert.equal(gets,0)
  flow.state.interacting=false;await flow.refresh();assert.equal(gets,1);flow.close()
})
