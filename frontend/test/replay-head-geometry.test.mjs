import test from 'node:test'
import assert from 'node:assert/strict'
import {headGeometry,projectHead,drawHead} from '../src/services/replayHeadGeometry.js'
function pose(){
  const kpts_xy=Array.from({length:17},()=>[.5,.6])
  for(const [i,p]of Object.entries({0:[.5,.37],1:[.48,.36],2:[.52,.36],3:[.46,.38],4:[.54,.38],5:[.43,.5],6:[.57,.5],11:[.44,.75],12:[.56,.75]}))kpts_xy[i]=p
  return{observed:true,kpts_xy,kpts_score:Array(17).fill(.9)}
}
const freeze=o=>{if(o&&typeof o==='object'){Object.values(o).forEach(freeze);Object.freeze(o)}return o}
test('head is circular in portrait and landscape source pixels',()=>{
  for(const [w,h]of [[1000,800],[720,1280]]){
    const g=headGeometry(pose(),w,h),center=[g.center[0]*w,g.center[1]*h]
    const radii=g.outline.map(p=>Math.hypot(p[0]*w-center[0],p[1]*h-center[1]))
    assert.ok(Math.max(...radii)-Math.min(...radii)<1e-10)
  }
})
test('wall perspective keeps the displayed head circular',()=>{
  const g=headGeometry(pose(),1000,800),project=p=>[p[0]*1000/(1+p[0]*.2),p[1]*800/(1+p[0]*.2)]
  const art=projectHead(g,project),center=project(g.center)
  const radii=art.outline.map(p=>Math.hypot(p[0]-center[0],p[1]-center[1]))
  assert.ok(Math.max(...radii)-Math.min(...radii)<1e-10)
})
test('drawing reads frozen evidence without adding or moving any joint',()=>{
  const p=freeze(pose()),before=JSON.stringify(p),calls=[]
  const ctx=new Proxy({canvas:{width:1000,getBoundingClientRect:()=>({width:390})}},
    {get:(o,k)=>k in o?o[k]:(...args)=>calls.push([k,...args])})
  drawHead(ctx,p,1000,800,xy=>[xy[0]*1000,xy[1]*800])
  assert.equal(JSON.stringify(p),before);assert.ok(calls.some(c=>c[0]==='stroke'))
})
test('uncertain, missing, duplicate or implausible face evidence stays empty',()=>{
  for(const change of ['missing','one','duplicate','far','flags','nan']){
    const p=pose()
    if(change==='missing')p.observed=false
    if(change==='one')p.kpts_score.splice(1,4,0,0,0,0)
    if(change==='duplicate')p.kpts_xy.splice(0,5,...Array(5).fill([.5,.37]))
    if(change==='far')p.kpts_xy.splice(0,5,...Array.from({length:5},(_,i)=>[.1+i*.01,.9]))
    if(change==='flags')p.joint_eligibility=Array(17).fill(false)
    if(change==='nan')p.kpts_xy[5]=[NaN,.5]
    assert.equal(headGeometry(p,1000,800),null,change)
  }
})
test('side view keeps head proportions; qualified raw scores are not probabilities',()=>{
  const p=pose(),a=headGeometry(p,1000,800)
  p.kpts_xy[5]=[.49,.5];p.kpts_xy[6]=[.51,.5]
  assert.deepEqual(headGeometry(p,1000,800),a)
  p.kpts_score.fill(2.3);assert.equal(headGeometry(p,1000,800),null)
  p.joint_eligibility=Array(17).fill(true);assert.ok(headGeometry(p,1000,800))
})
test('CSS minimum is bounded and has no effect on source geometry',()=>{
  const g=freeze(headGeometry(pose(),1000,800)),snapshot=JSON.stringify(g),project=p=>[p[0]*50,p[1]*40]
  const a=projectHead(g,project),center=project(g.center)
  const radius=points=>Math.min(...points.map(p=>Math.hypot(p[0]-center[0],p[1]-center[1])))
  assert.ok(Math.abs(radius(a.outline)/radius(g.outline.map(project))-1.6)<1e-10)
  assert.equal(JSON.stringify(g),snapshot)
})
