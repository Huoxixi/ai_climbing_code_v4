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
