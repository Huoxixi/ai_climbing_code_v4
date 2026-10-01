import assert from 'node:assert/strict'
import test from 'node:test'
import { readFileSync } from 'node:fs'
import { QUICK_ROUTE_COLORS, ROUTE_COLORS, ROUTE_COLOR_NAMES, hexToRgb, nearestRouteColor, rgbToHex, routeColorHex } from '../src/constants/routeColors.js'

test('线路快捷颜色固定为十二种且包含青色和棕色', () => {
  assert.equal(ROUTE_COLORS.length, 12)
  assert.equal(new Set(ROUTE_COLOR_NAMES).size, 12)
  assert.ok(ROUTE_COLOR_NAMES.includes('青色'))
  assert.ok(ROUTE_COLOR_NAMES.includes('棕色'))
  assert.equal(QUICK_ROUTE_COLORS.length, 10)
})

test('每种快捷颜色都有稳定色值且未知旧值安全回退', () => {
  for (const { value, hex } of ROUTE_COLORS) assert.equal(routeColorHex(value), hex)
  assert.equal(routeColorHex('历史自定义色'), '#7b7468')
})

test('调色盘和视频 RGB 样本能映射到最近的十二色并保留实际色值', () => {
  assert.deepEqual(hexToRgb('#20a6a6'), [32, 166, 166])
  assert.equal(rgbToHex([32, 166, 166]), '#20a6a6')
  assert.equal(nearestRouteColor([30, 160, 160]).value, '青色')
  assert.equal(nearestRouteColor([132, 82, 54]).value, '棕色')
})

test('复盘页可点选样本岩点并关联保存线路', () => {
  const page = readFileSync(new URL('../src/components/ClimbReplayPage.vue', import.meta.url), 'utf8')
  const service = readFileSync(new URL('../src/services/climbReplayService.js', import.meta.url), 'utf8')
  assert.match(page, /从画面点选样本岩点/)
  assert.match(page, /type="color"/)
  assert.match(page, /pickColorFromFrame/)
  assert.match(page, /point_xy: point/)
  assert.match(page, /routeId: selectedRouteId\.value/)
  assert.match(page, /routeColorSample: colorSample\.value/)
  assert.match(service, /route_color_sample:routeColorSample/)
  assert.match(service, /route_id:routeId/)
})
