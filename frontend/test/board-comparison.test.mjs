import assert from 'node:assert/strict'
import test from 'node:test'

import { compareBoards, reuseTierFor } from '../src/utils/boardComparison.js'

function board(holds, beta = [], spec = {}) {
  return {
    board_spec: { columns: 11, rows: 18, ...spec },
    placed_holds: holds,
    beta_sequence: beta,
  }
}

test('岩板差异能区分保留、新增、移除和修改', () => {
  const reference = board([
    { id: 'A1', hold_type: 'Jug', is_start: true },
    { id: 'B2', hold_type: 'Crimp' },
    { id: 'C3', hold_type: 'Foot' },
  ], [{ step: 1, limb: 'LH', hold_id: 'B2', is_top: true }])
  const target = board([
    { id: 'A1', hold_type: 'Jug', is_start: true },
    { id: 'B2', hold_type: 'Sloper', rotation: 15 },
    { id: 'D4', hold_type: 'Foot' },
  ], [{ step: 1, limb: 'RH', hold_id: 'D4', is_top: true }])

  const result = compareBoards(reference, target)
  assert.deepEqual(result.retained.map((hold) => hold.id), ['A1'])
  assert.deepEqual(result.changed.map((hold) => hold.id), ['B2'])
  assert.deepEqual(result.removed.map((hold) => hold.id), ['C3'])
  assert.deepEqual(result.added.map((hold) => hold.id), ['D4'])
  assert.equal(result.betaChanged, true)
  assert.deepEqual(result.topRemoved, ['B2'])
  assert.deepEqual(result.topAdded, ['D4'])
  assert.match(result.summary, /终点由 B2 调整为 D4/)
  assert.equal(result.displayHolds.some((hold) => hold.id === 'C3' && hold.comparison_ghost), true)
})

test('复用率严格按完全保留岩点占基准岩点计算并正确分级', () => {
  const reference = board([
    { id: 'A1', hold_type: 'Jug' },
    { id: 'B2', hold_type: 'Jug' },
    { id: 'C3', hold_type: 'Jug' },
    { id: 'D4', hold_type: 'Jug' },
  ])
  const target = board([
    { id: 'A1', hold_type: 'Jug' },
    { id: 'B2', hold_type: 'Jug' },
    { id: 'C3', hold_type: 'Crimp' },
    { id: 'E5', hold_type: 'Jug' },
  ])

  const result = compareBoards(reference, target)
  assert.equal(result.reuseRate, 0.5)
  assert.equal(result.reuseTier.key, 'pass')
  assert.equal(reuseTierFor(0.7).label, '达到最优标准')
  assert.equal(reuseTierFor(0.39).label, '变化较大')
})

test('不同规格岩板只提示坐标名比较，不推断物理位置相同', () => {
  const reference = board([{ id: 'A1', hold_type: 'Jug' }])
  const target = board([{ id: 'A1', hold_type: 'Jug' }], [], { columns: 14, rows: 20 })
  assert.equal(compareBoards(reference, target).specMismatch, true)
})
