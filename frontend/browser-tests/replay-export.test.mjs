import test, { after } from 'node:test'
import assert from 'node:assert/strict'
import { chromium } from '@playwright/test'
import { startFixtureServer } from './fixtures/server.mjs'
import { organized, syntheticMedia } from './fixtures/actions.mjs'
const base = await startFixtureServer(4196)
const browser = await chromium.launch({ headless: true })
const media = await syntheticMedia(browser)
after(() => browser.close())

for (const width of [1280, 390]) test(`exactly two export choices and no more materials at ${width}px`, async () => {
  const page = await browser.newPage({ viewport: { width, height: 900 } })
  const errors = [], writes = []
  page.on('pageerror', e => errors.push(e.message))
  const state = { task: { status: 'succeeded' }, result: structuredClone(organized),
    result_version: 'source-version', cloud_configured: false, export: { status: 'idle' }, revision_count: 0 }
  await page.route('**/api/climb-replay/**', async route => {
    const request = route.request(), url = new URL(request.url())
    if (request.method() === 'POST') writes.push(request.postDataJSON())
    if (url.pathname.endsWith('/source-video') || url.pathname.endsWith('/overlay-video')) {
      return route.fulfill({ body: media, contentType: 'video/webm' })
    }
    if (url.pathname.endsWith('/package')) {
      assert.equal(url.searchParams.get('version'), 'source-version')
      return route.fulfill({ body: Buffer.from('constructed-download'), contentType: 'application/zip',
        headers: { 'Content-Disposition': 'attachment; filename=climb-replay-package.zip' } })
    }
    return route.fulfill({ json: state })
  })
  try {
    await page.goto(base + '/e2e/actions-harness.html')
    assert.equal(await page.getByRole('button', { name: '更多资料', exact: true }).count(), 0)
    await page.getByRole('button', { name: '导出', exact: true }).click()
    const sheet = page.getByRole('dialog', { name: '导出复盘', exact: true })
    await sheet.waitFor()
    assert.equal(await sheet.getByRole('radio').count(), 2)
    assert.equal(await sheet.getByRole('radio', { name: '复盘视频', exact: true }).isChecked(), true)
    assert.equal(await sheet.getByRole('link').count(), 0)
    await sheet.getByRole('radio', { name: '视频＋全部资料', exact: true }).check()
    assert.match(await sheet.textContent(), /身体角度.*提示词与约束/)
    assert.equal(writes.length, 0)
    await page.getByRole('button', { name: '关闭面板', exact: true }).click()
    state.export_media = { id: 'video-1', scope: 'full', speed: .75 }
    await page.reload()
    await page.getByRole('button', { name: '导出', exact: true }).click()
    assert.equal(await sheet.getByRole('link').count(), 1)
    assert.match(await sheet.getByRole('link').getAttribute('href'), /video-1/)
    await sheet.getByRole('radio', { name: '视频＋全部资料', exact: true }).check()
    assert.equal(await sheet.getByRole('link').count(), 1)
    const bundle = sheet.getByRole('link', { name: '下载视频＋全部资料', exact: true })
    assert.match(await bundle.getAttribute('href'), /exported=true/)
    const download = page.waitForEvent('download')
    await bundle.click()
    assert.equal((await download).suggestedFilename(), 'climb-replay-package.zip')
    const bounds = await bundle.boundingBox()
    assert.ok(bounds.x >= 0 && bounds.x + bounds.width <= width)
    assert.deepEqual(errors, [])
  } finally { await page.close() }
})

test('vision settings save the chosen protocol and exact model without calling inference', async () => {
  const page = await browser.newPage({ viewport: { width: 390, height: 900 } })
  const writes = []
  await page.route('**/api/settings/replay-vision', async route => {
    const request = route.request()
    let data = { base_url: 'https://api.openai.com/v1', model: 'gpt-6-sol', api_mode: 'auto', configured: true, ready: true }
    if (request.method() === 'PUT') {
      data = { ...data, ...request.postDataJSON() }
      writes.push(structuredClone(data))
    }
    delete data.api_key
    await route.fulfill({ json: data })
  })
  try {
    await page.goto(base + '/e2e/replay-vision-harness.html')
    await page.getByLabel('接口类型', { exact: true }).selectOption('responses')
    await page.getByRole('button', { name: '保存评语服务', exact: true }).click()
    await page.getByRole('status').filter({ hasText: '已保存' }).waitFor()
    assert.equal(writes.length, 1)
    assert.equal(writes[0].model, 'gpt-6-sol')
    assert.equal(writes[0].api_mode, 'responses')
    assert.equal(writes[0].api_key, null)
  } finally { await page.close() }
})
