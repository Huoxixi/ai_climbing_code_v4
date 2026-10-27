import assert from 'node:assert/strict'
import test from 'node:test'
import { readFileSync } from 'node:fs'
import { QUICK_ROUTE_COLORS, ROUTE_COLORS, ROUTE_COLOR_NAMES, hexToRgb, nearestRouteColor, rgbToHex, routeColorHex } from '../src/constants/routeColors.js'
import apiClient from '../src/services/apiClient.js'

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

test('复盘页取色与历史线路参数保留，纯骨架分支明确排除岩点输入', async (t) => {
  const page = readFileSync(new URL('../src/components/ClimbReplayPage.vue', import.meta.url), 'utf8')
  const service = readFileSync(new URL('../src/services/climbReplayService.js', import.meta.url), 'utf8')
  assert.match(page, /从画面点选样本岩点/)
  assert.doesNotMatch(page, /type="color"|name="route-color"|replay-extra-color/)
  assert.match(page, /pickColorFromFrame/)
  assert.match(page, /point_xy: point/)
  assert.doesNotMatch(page, /selectedRouteId|replay-saved-route|loadSavedRoutes|关联线路/)
  assert.match(page, /routeColorSample: colorSample\.value/)
  // 执行真实服务构造的请求，避免skip_holds分支或空白变化使源码正则误报。
  const executable = service.replace("'./apiClient'", JSON.stringify(new URL('../src/services/apiClient.js', import.meta.url).href))
    .replace("'./chunkUpload'", JSON.stringify(new URL('../src/services/chunkUpload.js', import.meta.url).href))
  const { default: replay } = await import(`data:text/javascript;base64,${Buffer.from(executable).toString('base64')}`)
  const previousAdapter = apiClient.defaults.adapter
  t.after(() => { apiClient.defaults.adapter = previousAdapter })
  const requests = []
  apiClient.defaults.adapter = async config => {
    const data = typeof config.data === 'string' ? JSON.parse(config.data) : config.data
    requests.push({ url: config.url, data })
    return { data: config.method === 'put' ? { offset: 3 } : { id: 'upload-1', offset: 0, chunk_size: 8 }, status: 200, statusText: 'OK', headers: {}, config }
  }
  const sample = { source: 'video', rgb: [30, 160, 160], point_xy: [20, 40], time_seconds: 2 }
  const input = { video: new File(['abc'], 'wall.mp4', { type: 'video/mp4' }), routeId: 'legacy-route', routeColor: '青色', routeColorSample: sample,
    consentVersion: 'test-local-version', consentGranted: true, retentionMode: 'delete_after_processing', trimStartSeconds: 0, trimEndSeconds: 90 }
  for (const preparedId of ['', 'prepared id']) {
    for (const skipHolds of [false, true]) {
      requests.length = 0
      await replay.create({ ...input, preparedId, skipHolds })
      const request = requests[0]
      assert.equal(request.url, preparedId ? '/api/climb-replay/prepared-videos/prepared%20id/start' : '/api/climb-replay/uploads')
      assert.deepEqual(request.data, {
        filename: 'wall.mp4', content_type: 'video/mp4', size_bytes: 3, skip_holds: skipHolds,
        route_id: skipHolds ? '' : input.routeId, route_color: skipHolds ? '' : input.routeColor, route_color_sample: skipHolds ? null : sample,
        consent_version: input.consentVersion, consent_granted: true, retention_mode: 'keep_private_original', trim_start_seconds: 0, trim_end_seconds: 90,
      })
    }
  }
})
