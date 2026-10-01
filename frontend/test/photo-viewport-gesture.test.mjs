import test from 'node:test'
import assert from 'node:assert/strict'
import { photoWheelGesture } from '../src/utils/photoViewportGesture.js'

test('触摸板双指上下滑动在放大后平移照片而不是缩放', () => {
  assert.deepEqual(
    photoWheelGesture({ ctrlKey: false, deltaX: 0, deltaY: 36, deltaMode: 0 }, 2, 600),
    { type: 'pan', x: 0, y: -36 },
  )
})

test('触摸板捏合仍然缩放照片', () => {
  const result = photoWheelGesture({ ctrlKey: true, deltaX: 0, deltaY: -50, deltaMode: 0 }, 2, 600)
  assert.equal(result.type, 'zoom')
  assert.ok(result.factor > 1)
})

test('完整显示时双指滑动交给页面滚动', () => {
  assert.deepEqual(
    photoWheelGesture({ ctrlKey: false, deltaX: 0, deltaY: 36, deltaMode: 0 }, 1, 600),
    { type: 'page' },
  )
})
