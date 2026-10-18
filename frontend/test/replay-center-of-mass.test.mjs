import test from 'node:test'
import assert from 'node:assert/strict'
import {centerOfMass} from '../src/services/replayCenterOfMass.js'
const sample=()=>({observed:true,kpts_xy:Array.from({length:17},(_,i)=>({5:[.35,.3],6:[.55,.3],7:[.29,.4],8:[.61,.4],9:[.27,.5],10:[.63,.5],11:[.4,.6],12:[.5,.6],13:[.37,.74],14:[.53,.74],15:[.36,.88],16:[.54,.88]}[i]||[.45,.22])),kpts_score:Array(17).fill(.95)})
test('leg elevation shifts the mass point with the torso unchanged',()=>{
  const a=sample(),b=sample()
  b.kpts_xy[13]=[.5,.52];b.kpts_xy[15]=[.48,.6]
  assert.ok(centerOfMass(b)[1]<centerOfMass(a)[1]-.02)
  assert.ok(Math.abs(centerOfMass(a)[0]-.45)<1e-12)
})
test('missing limbs, missing head and unobserved poses have no replacement dot',()=>{
  for(const i of [9,13,15]){const a=sample();a.kpts_score[i]=.1;assert.equal(centerOfMass(a),null)}
  const a=sample();for(const i of [0,3,4])a.kpts_score[i]=.1
  assert.equal(centerOfMass(a),null)
  assert.equal(centerOfMass({...sample(),observed:false}),null)
})
test('mass point follows camera-frame translation without torso-only substitution',()=>{
  const a=sample(),b=sample();b.kpts_xy=b.kpts_xy.map(([x,y])=>[x+.1,y+.02])
  const before=centerOfMass(a),after=centerOfMass(b)
  assert.ok(Math.abs(after[0]-before[0]-.1)<1e-12)
  assert.ok(Math.abs(after[1]-before[1]-.02)<1e-12)
})
