import test from 'node:test'
import assert from 'node:assert/strict'
import { photoObjectLabel, photoObjectPosition } from '../src/utils/photoObjectLabel.js'

const board = { width: 300, height: 600 }

test('岩点位置使用照片中的人类可读区域', () => {
  assert.equal(photoObjectPosition({ contour: [[10, 20], [20, 40]] }, board), '左上区域')
  assert.equal(photoObjectPosition({ contour: [[140, 280], [160, 320]] }, board), '中央区域')
  assert.equal(photoObjectPosition({ contour: [[280, 560], [290, 580]] }, board), '右下区域')
})

test('岩点无障碍名称包含颜色、位置和线路状态', () => {
  const object = { color_group: '黄色', contour: [[280, 560], [290, 580]] }
  assert.equal(photoObjectLabel(object, board, { member: true }), '黄色岩点，照片右下区域，已在线路中')
  assert.equal(photoObjectLabel(object, board), '黄色岩点，照片右下区域，可加入线路')
})
