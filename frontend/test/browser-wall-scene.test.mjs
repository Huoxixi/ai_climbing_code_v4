import test from 'node:test'
import assert from 'node:assert/strict'
import {backgroundTimes} from '../src/browser-replay/wallScene.js'
import {projectWallPoint,wallTransformAt,validWallScene,WALL_SCENE_VERSION} from '../src/browser-replay/wallGeometry.js'

test('empty-wall search prioritizes both ends, covers the entire source and retains isolated edge frames',()=>{
  const times=[...backgroundTimes(120)]
  assert.equal(times[0],0);assert.ok(times[1]>119.96&&times[1]<120)
  assert.ok(times.some(t=>t>90&&t<110))
  assert.ok(times.some(t=>Math.abs(t-1/30)<1e-6))
  assert.ok(times.every(t=>t>=0&&t<120));assert.equal(times.length,new Set(times.map(t=>Math.round(t*3000))).size)
})
test('short sources produce real positions rather than the end sentinel',()=>{
  assert.ok([...backgroundTimes(.03)].every(t=>t>=0&&t<.03))
})
test('presentation timestamps cover every actual VFR frame including a one-frame empty tail',()=>{
  const frames=[0,.033,.066,.5,.504,.508,.512,.999],times=[...backgroundTimes(1,frames)]
  assert.equal(times.length,frames.length)
  for(const frame of frames)assert.ok(times.some(t=>t>=frame&&t<frame+.001))
  assert.ok(times[1]>.999&&times[1]<1)
})
test('wall projection preserves normalized geometry across output sizes and rejects singular transforms',()=>{
  const p=[.25,.4],matrix=[1.1,.02,.05,-.01,.9,.1,.01,-.02,1]
  const q=projectWallPoint(p,matrix),d=.01*p[0]-.02*p[1]+1
  assert.ok(Math.abs(q[0]-(1.1*p[0]+.02*p[1]+.05)/d)<1e-10)
  assert.equal(projectWallPoint(p,[1,0,0,0,1,0,0,0,0]),null)
  assert.equal(projectWallPoint([NaN,0],matrix),null)
})
test('failed and missing registrations cannot borrow a neighboring valid pose transform',()=>{
  const matrix=[1,0,0,0,1,0,0,0,1],analysis={wall_scene:{version:WALL_SCENE_VERSION,status:'ready',registrations:[{time_seconds:1,matrix},{time_seconds:1.1,matrix:null}]}}
  assert.deepEqual(wallTransformAt(analysis,{time_seconds:1}),matrix)
  assert.equal(wallTransformAt(analysis,{time_seconds:1.1}),null)
  assert.equal(wallTransformAt(analysis,{time_seconds:1.2}),null)
  assert.equal(wallTransformAt(analysis,null),null)
})
test('wall exports require actual persisted image bytes and the current scene version',()=>{
  const scene={version:WALL_SCENE_VERSION,status:'ready',registrations:[],image:new Blob(['pixels'])}
  assert.equal(validWallScene(scene),true)
  assert.equal(validWallScene({...scene,image:{}}),false)
  assert.equal(validWallScene({...scene,version:'old'}),false)
})
