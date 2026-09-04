import assert from 'node:assert/strict'
import test from 'node:test'
import { PHOTO_BOARD, photoHoles, fitPhotoObjects, union, withinBoard, translateObjects, scaleObjects, patchObject, createHistory, zoomCamera } from '../src/utils/photoBoard.js'
import { createDraftAutosave } from '../src/utils/photoDraftAutosave.js'

const source = () => [{ id:'a', source_bbox_px:[100,100,100,200], z_index:0 }, { id:'b', source_bbox_px:[600,700,200,100], z_index:1 }]
test('600 physical reference holes, A–AD and exact edge distances', () => {
  const holes = photoHoles()
  assert.equal(holes.length,600); assert.equal(holes[0].id,'A1'); assert.equal(holes.at(-1).id,'AD20')
  assert.deepEqual([holes[0].x,holes[0].y,holes.at(-1).x,holes.at(-1).y],[200,100,6000,3900])
  assert.equal(PHOTO_BOARD.board_width_mm,6200); assert.equal(PHOTO_BOARD.board_height_mm,4100)
})
test('fit preserves relative geometry, flips y and centers union', () => {
  const objects=fitPhotoObjects(source()), box=union(objects)
  assert.ok(withinBoard(objects)); assert.equal(objects[0].scale_mm_per_px,objects[1].scale_mm_per_px)
  assert.ok(objects[0].center_y_mm>objects[1].center_y_mm)
  assert.ok(Math.abs(box.bottom-100)<1e-6); assert.ok(Math.abs(box.top-3900)<1e-6)
  assert.ok(Math.abs((box.left+box.right)/2-3100)<1e-6)
})
test('group movement clamps without altering relative positions and never snaps', () => {
  const objects=fitPhotoObjects(source()), moved=translateObjects(objects,10000,-10000)
  assert.ok(withinBoard(moved)); assert.equal(union(moved).right,6200)
  assert.ok(Math.abs((moved[0].center_x_mm-moved[1].center_x_mm)-(objects[0].center_x_mm-objects[1].center_x_mm))<1e-6)
  const precise=translateObjects(objects,3.7,1.2); assert.ok(Math.abs(precise[0].center_x_mm-objects[0].center_x_mm-3.7)<1e-6)
})
test('scale and rotate reject overflow and keep texture aspect', () => {
  const objects=fitPhotoObjects(source()); assert.equal(scaleObjects(objects,5),objects)
  const smaller=scaleObjects(objects,.5); assert.ok(withinBoard(smaller)); assert.equal(smaller[0].scale_mm_per_px,objects[0].scale_mm_per_px/2)
  const rotated=patchObject(smaller[0],{rotation_deg:45}); assert.equal(rotated.rotation_deg,45)
  assert.equal(patchObject(rotated,{center_x_mm:-1}),rotated)
  assert.equal(patchObject(rotated,{scale_mm_per_px:0}),rotated)
})
test('history restores transforms and roles; a fresh edit clears redo', () => {
  const h=createHistory(); const first=fitPhotoObjects(source()); h.push(first)
  const next=translateObjects(first,20,20); next[0].roles=['start']
  assert.deepEqual(h.undo(next),first); assert.deepEqual(h.redo(first),next)
  h.undo(next); h.push(next); assert.equal(h.canRedo,false)
})
test('zoom focal point stays fixed and resets do not edit objects', () => {
  const camera=zoomCamera({zoom:1,x:0,y:0},2,{x:100,y:50})
  assert.deepEqual(camera,{zoom:2,x:-100,y:-50}); assert.equal(zoomCamera(camera,99,{x:0,y:0}).zoom,8)
})

function fixture(save) {
  let scheduled, stored, state, saved
  const autosave=createDraftAutosave({save, onSaved:(data,current)=>{saved={data,current}}, onState:s=>{state=s}, persist:d=>{stored=d}, schedule:fn=>{scheduled=fn;return 1}, unschedule:()=>{scheduled=null}})
  autosave.reset(1)
  return { autosave, get stored(){return stored}, get state(){return state}, get saved(){return saved}, get scheduled(){return scheduled} }
}
test('autosave debounces then sends expected version and clears recovery after success', async () => {
  const calls=[]; const f=fixture(async (draft,v)=>{calls.push([draft,v]);return {...draft,version:v+1}})
  f.autosave.change({name:'a'}); f.autosave.change({name:'b'})
  assert.equal(calls.length,0); assert.equal(f.stored.name,'b'); await f.scheduled()
  assert.equal(calls.length,1); assert.equal(calls[0][1],1); assert.equal(f.state,'saved'); assert.equal(f.stored,null)
})
test('an edit during an in-flight save survives the response and uses the new version', async () => {
  let resolve; const calls=[]
  const f=fixture((draft,version)=>{calls.push({draft,version}); return new Promise(r=>{resolve=r})})
  f.autosave.change({name:'a'}); const saving=f.autosave.flush(); f.autosave.change({name:'b'}); resolve({name:'a',version:2}); await saving
  assert.equal(f.stored.name,'b'); assert.equal(f.stored.version,2); assert.equal(f.saved.current,false)
  const again=f.autosave.flush(); assert.equal(calls[1].version,2); resolve({name:'b',version:3}); await again; assert.equal(f.autosave.dirty,false)
})
test('conflict blocks automatic overwrite and lease failures retain changes', async () => {
  for (const status of [409,423,401,500]) {
    const f=fixture(async()=>{throw {response:{status}}}); f.autosave.change({name:'local'}); await f.autosave.flush()
    assert.equal(f.autosave.dirty,true); assert.equal(f.stored.name,'local')
    assert.equal(f.state,status===409?'conflict':status===500?'error':'lease')
  }
})
test('lease loss cancels automatic save; restore with a stale version stays blocked', async () => {
  let calls=0; const f=fixture(async()=>{calls++})
  f.autosave.setAllowed(false); f.autosave.change({name:'local'}); await f.autosave.flush(); assert.equal(calls,0)
  f.autosave.setAllowed(true); f.autosave.restore({name:'recovered',version:1},true); await f.autosave.flush(); assert.equal(calls,0); assert.equal(f.state,'conflict')
})
