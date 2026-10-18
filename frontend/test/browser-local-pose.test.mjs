import test from 'node:test'
import assert from 'node:assert/strict'
import {createHash} from 'node:crypto'
import {loadModel} from '../src/browser-replay/modelCache.js'
import {detectorInput,poseInput,decodePose,decodeDetector,continueTarget} from '../src/browser-replay/poseMath.js'

const bytes=Uint8Array.from([4,8,15,16,23,42]),file={name:'test',url:'/model/test.onnx',bytes:bytes.length,sha256:createHash('sha256').update(bytes).digest('hex')}
function storage(initial){
  const map=new Map(initial?[[file.url,new Response(initial)]]:[])
  const cache={match:async key=>map.get(key)?.clone(),put:async(key,response)=>map.set(key,response),delete:async key=>map.delete(key)}
  return {cache,open:async()=>cache}
}
test('verified cache avoids network and rejects a stale or corrupted cache',async()=>{
  const good=storage(bytes),progress=[]
  await loadModel(file,{cacheStorage:good,fetcher:()=>assert.fail('cache hit must not fetch'),onProgress:p=>progress.push(p)})
  assert.equal(progress.at(-1).cached,true)
  const corrupt=storage(Uint8Array.from([1,2,3,4,5,6]));let count=0
  await loadModel(file,{cacheStorage:corrupt,fetcher:async()=>{count++;return new Response(bytes)}})
  assert.equal(count,1)
  assert.deepEqual(new Uint8Array(await (await corrupt.cache.match(file.url)).arrayBuffer()),bytes)
})
test('network response is verified before it can enter persistent cache',async()=>{
  const cache=storage()
  await assert.rejects(loadModel(file,{cacheStorage:cache,fetcher:async()=>new Response(Uint8Array.from([1,2,3,4,5,6]))}),/校验失败/)
  assert.equal(await cache.cache.match(file.url),undefined)
  await assert.rejects(loadModel(file,{cacheStorage:cache,fetcher:async()=>new Response(new Uint8Array(7))}),/大小/)
  await assert.rejects(loadModel(file,{cacheStorage:cache,fetcher:async()=>new Response('',{status:503})}),/503/)
})
test('storage denial or quota failure still permits verified local inference',async()=>{
  const denied={open:async()=>{throw new Error('denied')}},updates=[]
  const buffer=await loadModel(file,{cacheStorage:denied,fetcher:async()=>new Response(bytes),onProgress:p=>updates.push(p)})
  assert.deepEqual(new Uint8Array(buffer),bytes);assert.equal(updates.at(-1).stored,false)
  const quota=storage();quota.cache.put=async()=>{throw new Error('quota')}
  await loadModel(file,{cacheStorage:quota,fetcher:async()=>new Response(bytes)})
})
test('BGR tensor conversion preserves the established native model channel order',()=>{
  const frame={width:1,height:1,data:Uint8ClampedArray.from([10,20,30,255])}
  const detector=detectorInput(frame)
  assert.equal(detector.data[0],30);assert.equal(detector.data[640*640],20);assert.equal(detector.data[2*640*640],10)
  const pose=poseInput({width:2,height:2,data:Uint8ClampedArray.from(Array(4).fill([10,20,30,255]).flat())},[0,0,1,1]),mid=192*288+144
  assert.ok(Math.abs(pose.data[mid]-(30-123.675)/58.395)<1e-6)
  assert.throws(()=>poseInput(frame,[0,0,0,1]),/区域无效/)
})
test('SimCC uses the native mean score and preserves invalid observations separately',()=>{
  const x={dims:[1,133,576],data:new Float32Array(133*576)},y={dims:[1,133,768],data:new Float32Array(133*768)}
  for(let k=0;k<133;k++){x.data[k*576+288]=.8;y.data[k*768+384]=.4}
  const pose=decodePose(x,y,[50,100],[100,200],100,200)
  assert.deepEqual(pose.points[0],[.5,.5]);assert.ok(Math.abs(pose.scores[0]-.6)<1e-6);assert.equal(pose.eligible[0],true)
  x.data.fill(-1);y.data.fill(-1)
  const absent=decodePose(x,y,[50,100],[100,200],100,200)
  assert.equal(absent.eligible[0],false);assert.equal(absent.scores[0],-1)
  assert.throws(()=>decodePose({...x,dims:[1,17,576]},y,[0,0],[1,1],1,1),/格式/)
})
test('packed detections reject nonfinite, reversed and low-confidence boxes',()=>{
  const tensor={dims:[1,4,5],data:Float32Array.from([1,2,20,30,.9,1,2,20,30,.1,20,2,1,30,.8,1,2,NaN,30,.8])}
  assert.equal(decodeDetector(tensor,1,100,100).length,1)
  const overlapping={dims:[1,2,5],data:Float32Array.from([1,2,20,30,.9,2,3,21,31,.8])}
  assert.equal(decodeDetector(overlapping,1,100,100).length,2,'embedded native NMS must not be replaced by another suppression pass')
})
test('tracking does not initialize from the largest person or jump to a distant person',()=>{
  assert.equal(continueTarget([{box:[80,80,100,100],score:.99}],[0,0,20,20]),null)
  assert.equal(continueTarget([{box:[0,0,20,20]},{box:[1,0,21,20]}],[0,0,20,20]),null)
  assert.deepEqual(continueTarget([{box:[1,0,21,20]}],[0,0,20,20]).box,[1,0,21,20])
})
