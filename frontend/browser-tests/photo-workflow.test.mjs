import { startFixtureServer } from './fixtures/server.mjs'
import test, { after } from 'node:test'
import assert from 'node:assert/strict'
import { createRequire } from 'node:module'
const require = createRequire(import.meta.url)
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || '@playwright/test')
const base = await startFixtureServer(4197)
const browser = await chromium.launch({ headless: true })
after(() => browser.close())

// All records, masks and images are constructed; no account or personal media is used.
const board = { id: 'fixture-board', width: 600, height: 800, original_asset: { filename: 'fixture.svg' }, objects: [
  { id: 'fixture-hold', color_group: '黄色', contour: [[100,100],[150,100],[150,150],[100,150]], object_version: 1 },
] }
const record = { id: 'fixture-route', board_version_id: board.id, version: 1, name: '构造黄色线路', color_group: '黄色',
  status: 'completed', difficulty: 'V2', notes: '', setter: '', created_at: '2026-09-30T00:00:00Z',
  members: [{ object_id: 'fixture-hold', roles: [], tags: [], note: '' }], media: [] }
for (const width of [1280,390]) test(`current photo library and contour detail at ${width}px`, async () => {
  const page = await browser.newPage({ viewport: { width, height: 900 } })
  const errors = [], writes = [], unknown = []
  page.on('pageerror', error => errors.push(error.message))
  await page.route('**/api/**', async route => {
    const request = route.request(), path = new URL(request.url()).pathname
    if (request.method() !== 'GET') writes.push(path)
    if (path.endsWith('/assets/fixture.svg')) return route.fulfill({ contentType: 'image/svg+xml', body: '<svg xmlns="http://www.w3.org/2000/svg" width="600" height="800"><rect width="600" height="800" fill="#ccc"/><rect x="100" y="100" width="50" height="50" fill="#ffcc00"/></svg>' })
    const responses = {
      '/api/auth/session': { authenticated: true, auth_enabled: true, username: 'constructed-browser-test', display_name: '测试' },
      '/api/pilot/edit-lease': { active: false, owned_by_me: false },
      '/api/holds/mapping': {},
      '/api/holds/vectors': {},
      '/api/holds/assets': [],
      '/api/my-boards': [],
      '/api/standard-board/routes': [],
      '/api/photo-routes/workflow/current': null,
      '/api/photo-routes/v2/routes': [record],
      [`/api/photo-routes/v2/routes/${record.id}`]: record,
      [`/api/photo-routes/v2/boards/${board.id}`]: board,
    }
    if (!Object.hasOwn(responses, path)) { unknown.push(path); return route.fulfill({ status: 404, json: {} }) }
    return route.fulfill({ body: JSON.stringify(responses[path]), contentType: 'application/json' })
  })
  try {
    await page.goto(base + '/#/my-records')
    const card = page.getByRole('button', { name: /^查看线路：构造黄色线路/ })
    await card.waitFor()
    assert.equal(await card.locator('polygon').count(), 1)
    await card.click()
    await page.getByRole('heading', { name: '线路信息', exact: true }).waitFor()
    assert.equal(await page.locator('.is-route-contour').count(), 1)
    assert.equal(await page.getByLabel('线路名称', { exact: true }).inputValue(), record.name)
    assert.equal(await page.locator('.photo-work__image img').evaluate(img => img.complete && img.naturalWidth > 0), true)
    assert.equal(await page.locator('.physical-board,.hole-grid,.calibration-panel').count(), 0)
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), true)
    await page.getByRole('button', { name: '返回我的记录', exact: true }).click()
    await card.waitFor()
    assert.deepEqual(errors, [])
    assert.deepEqual(writes, [])
    assert.deepEqual(unknown, [])
  } finally { await page.close() }
})
