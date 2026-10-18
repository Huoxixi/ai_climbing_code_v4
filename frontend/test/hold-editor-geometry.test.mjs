import test from 'node:test'
import assert from 'node:assert/strict'
import { imagePoint, contourFromBinary, simplifyContour } from '../src/services/holdEditorGeometry.js'

test('zoomed, scrolled image coordinates map to the same original point', () => {
  assert.deepEqual(imagePoint(120, 80, { left:20, top:30, width:200, height:100 }), [.5, .5])
  assert.deepEqual(imagePoint(220, 130, { left:-180, top:-70, width:800, height:400 }), [.5, .5])
})
test('brush raster traces concavities and rejects disconnected scraps or holes', () => {
  const mask = new Uint8Array(100)
  for(let y=2;y<8;y++)for(let x=2;x<8;x++)if(x<5||y<5)mask[y*10+x]=1
  const polygon = contourFromBinary(mask,10,10)
  assert.equal(polygon.length,6)
  assert.ok(polygon.some(p=>p[0]===.5&&p[1]===.5))
  mask[0]=1
  assert.throws(()=>contourFromBinary(mask,10,10),/连续岩点/)
  const hole = new Uint8Array(100).fill(1);hole[44]=0
  assert.throws(()=>contourFromBinary(hole,10,10),/孔洞/)
})
test('simplification preserves a closed contour corner rather than reducing to a line', () => {
  const path=[[0,0],[.5,0],[1,0],[1,.5],[1,1],[.5,1],[0,1],[0,.5]]
  assert.deepEqual(simplifyContour(path),[[0,0],[1,0],[1,1],[0,1]])
})
