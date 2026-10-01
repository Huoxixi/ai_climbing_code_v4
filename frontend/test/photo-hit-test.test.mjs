import test from 'node:test'
import assert from 'node:assert/strict'
import { pickPhotoObject } from '../src/utils/photoHitTest.js'
const box = (id, x, y, size) => ({id, contour:[[x,y],[x+size,y],[x+size,y+size],[x,y+size]]})
test('overlapping contours pick the smaller hold regardless of drawing order', () => {
  const small=box('hold',20,20,10), large=box('volume',0,0,100)
  for(const objects of [[small,large],[large,small]]) assert.equal(pickPhotoObject(objects,[25,25]).id,'hold')
})
test('edge tolerance selects the nearest contour but not distant wall', () => {
  const objects=[box('a',0,0,10),box('b',20,0,10)]
  assert.equal(pickPhotoObject(objects,[17,5],4).id,'b')
  assert.equal(pickPhotoObject(objects,[50,5],4),null)
  assert.equal(pickPhotoObject(objects,[10,5]).id,'a')
})
test('concave empty areas do not count as the hold', () => {
  const object={id:'L',contour:[[0,0],[10,0],[10,3],[3,3],[3,10],[0,10]]}
  assert.equal(pickPhotoObject([object],[8,8]),null)
  assert.equal(pickPhotoObject([object],[2,8]).id,'L')
})
