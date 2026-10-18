import test from 'node:test'
import assert from 'node:assert/strict'
import { torsoTrajectoryPlot, torsoRoutePlot, horizontalShiftLabel } from '../src/services/replayTorsoTrajectory.js'
import { summarySeconds, trajectoryStart } from '../src/services/replayPresentation.js'

const trajectory = { status: 'partial', reference_size: [640, 480], segments: [
  [{ xy: [.4, .7], time_seconds: 0 }, { xy: [.5, .6], time_seconds: .25 }],
  [{ xy: [.6, .4], time_seconds: 1 }, { xy: [.7, .3], time_seconds: 1.25 }],
] }

test('轨迹保留画面比例和缺测断口，静止轨迹也能显示', () => {
  const plot = torsoTrajectoryPlot(trajectory)
  assert.equal(plot.paths.length, 2)
  assert.equal(plot.pointCount, 4)
  assert.ok(plot.start.x < plot.end.x && plot.start.y > plot.end.y)
  const points = plot.paths[0].split(' ').map(point => point.split(',').map(Number))
  assert.ok(Math.abs(Math.abs((points[1][0] - points[0][0]) / (points[1][1] - points[0][1])) - 640 / 480) < 1e-9)
  const stationary = torsoTrajectoryPlot({ ...trajectory, segments: [[0, 1, 2].map(time_seconds => ({ time_seconds, xy: [.5, .5] }))] })
  assert.equal(stationary.start.x, stationary.end.x)
  assert.equal(torsoTrajectoryPlot({ ...trajectory, status: 'insufficient' }), null)
  assert.equal(torsoTrajectoryPlot(null), null)
})

test('左右说明有明确参照，数据不足不猜测偏向', () => {
  assert.equal(horizontalShiftLabel({ net_horizontal_percent: 12.5 }), '首末净横移：向右 12.5%')
  assert.equal(horizontalShiftLabel({ net_horizontal_percent: -4 }), '首末净横移：向左 4.0%')
  assert.equal(horizontalShiftLabel({ net_horizontal_percent: 0 }), '首末观测在同一列')
  assert.equal(horizontalShiftLabel(null), '左右偏移暂不能比较')
})

test('结束态线路使用与岩点图相同的裁剪坐标', () => {
  const plot = torsoRoutePlot(trajectory, [
    { bbox: [.35, .22, .18, .55] },
    { bbox: [.62, .28, .12, .2] },
  ])
  assert.equal(plot.paths.length, 2)
  assert.ok(plot.viewBox[0] > 0 && plot.viewBox[1] > 0)
  assert.ok(plot.viewBox[2] < 640 && plot.viewBox[3] < 480)
  assert.deepEqual(plot.start, { x: 256, y: 336 })
  assert.deepEqual(plot.end, { x: 448, y: 144 })
  assert.equal(torsoRoutePlot({ ...trajectory, status: 'insufficient' }), null)
})

test('结束总结在既有数据和节奏之后给轨迹留出阅读时间', () => {
  const metrics = [{ key: 'duration' }]
  assert.equal(trajectoryStart(metrics, {}), summarySeconds(metrics, {}))
  assert.equal(summarySeconds(metrics, {}, trajectory), summarySeconds(metrics, {}) + 8)
  assert.equal(summarySeconds(metrics, null, null), summarySeconds(metrics))
})
