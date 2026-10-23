import test from 'node:test'
import assert from 'node:assert/strict'
import {readFileSync} from 'node:fs'
import module from '@techstark/opencv-js'
import {rotateInput,undoRotation,selectImageObservation,temporalUpdates,ImageDisplayWindow} from '../src/browser-replay/acceptedPose.js'
const read=name=>JSON.parse(readFileSync(new URL('./fixtures/'+name,import.meta.url)))
const cases=read('accepted-19.2-selection.json')
test('browser selection agrees with independent accepted Python output and preserves raw/eligibility',()=>{
  for(const item of cases){
    const before=structuredClone(item.primary),result=selectImageObservation(item.primary,item.candidate,item.size)
    assert.deepEqual(result.points,item.expected.points,item.name)
    assert.deepEqual(result.scores,item.expected.scores,item.name)
    assert.deepEqual(result.eligible,before.eligible)
    assert.deepEqual(result.primary_native,before)
    assert.deepEqual(item.primary,before)
    assert.deepEqual(result.image_observation_refinement.selected_joints,item.chosen)
    for(const j of [5,6,11,12,13,14,15,16])assert.deepEqual(result.points[j],before.points[j])
  }
})
test('15 degree tensor transform agrees with independent OpenCV reference',async()=>{
  const cv=await module,data=Float32Array.from({length:3*288*384},(_,i)=>Math.fround(Math.fround(i%251)/51)-2),rotated=rotateInput({data,dims:[1,3,384,288]},cv)
  const reference=read('accepted-19.2-rotation.json'),diff=reference.indices.map((id,i)=>Math.abs(rotated.data[id]-reference.values[i]))
  // C++ and WASM OpenCV interpolation differ at float precision near borders;
  // 0.0002 normalized units is less than 0.012 source intensity levels.
  assert.ok(Math.max(...diff)<.0002,`max tensor difference ${Math.max(...diff)}`)
  const input={dims:[1,3,384,288],center:[300,400],scale:[450,600]},center={points:[[.5,.5]]}
  assert.deepEqual(undoRotation(center,input,[600,800]).points,center.points)
})
function fixture(){
  const points=Array.from({length:133},()=>[150/320,160/240])
  for(const [j,x,y]of [[5,110,65],[6,170,65],[11,115,145],[12,165,145],[7,90,90],[8,190,90],[9,75,115],[10,205,115],[13,110,170],[14,170,170],[15,100,200],[16,180,200]])points[j]=[x/320,y/240]
  return {points,scores:Array(133).fill(.9),eligible:Array(133).fill(true)}
}
test('actual image tracking reduces supported jitter, follows motion, clears gaps and releases Mats',async()=>{
  const cv=await module,window=new ImageDisplayWindow(cv),pose=fixture(),image={width:320,height:240,data:new Uint8ClampedArray(320*240*4)}
  let state=19
  for(let i=0;i<image.data.length;i+=4){state=(Math.imul(state,1664525)+1013904223)>>>0;const v=state>>>24;image.data.set([v,v,v,255],i)}
  const jitter=structuredClone(pose);jitter.points[15][0]+=6/320
  assert.equal(window.push(image,pose,{time:0,index:0,track:1}),null)
  assert.equal(window.push(image,jitter,{time:.1,index:1,track:1}),null)
  const result=window.push(image,pose,{time:.2,index:2,track:1})
  assert.equal(result.index,1);assert.ok(Math.abs(result.payload.updates.find(u=>u.joint===15).xy[0]*320-102)<.01)
  assert.equal(jitter.points[15][0]*320,106)
  const tracks=[0,1].map(()=>({points:pose.points.map(p=>[p[0]*320,p[1]*240]),valid:Array(133).fill(true)}))
  const records=[0,.1,.2].map(time=>({time,track:1,pose:structuredClone(pose)}))
  assert.deepEqual(temporalUpdates(records,tracks,[320,240],1),[])
  records[2].time=.9;assert.deepEqual(temporalUpdates(records,tracks,[320,240],1),[])
  records[2].time=.2;records[2].track=2;assert.deepEqual(temporalUpdates(records,tracks,[320,240],1),[])
  window.clear();assert.equal(window.window.length,0)
  assert.equal(window.push(image,pose,{time:1,index:10,track:1}),null);window.clear()
})
