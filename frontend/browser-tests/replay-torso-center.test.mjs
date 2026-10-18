import { startFixtureServer } from './fixtures/server.mjs'
import { organized, syntheticMedia } from './fixtures/actions.mjs'
import { chromium } from '@playwright/test'
import test, { after } from 'node:test'
import assert from 'node:assert/strict'
import { mkdir } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'

const base = await startFixtureServer(4203)
const browser = await chromium.launch({ headless: true })
const media = await syntheticMedia(browser)
const artifacts = new URL('../../.tmp/torso-center-verification/', import.meta.url)
await mkdir(artifacts, { recursive: true })
after(() => browser.close())

function pose(frame, x, reliable = true) {
  const sample = { observed: true, source_frame_id: frame, kpts_xy: Array.from({ length: 17 }, () => [0, 0]), kpts_score: Array(17).fill(0) }
  for (const [joint, dx, y] of [[5, -.1, .2], [6, .1, .2], [11, -.1, .7], [12, .1, .7]]) {
    sample.kpts_xy[joint] = [x + dx, y]; sample.kpts_score[joint] = reliable || joint > 6 ? .9 : .1
  }
  return sample
}

for (const width of [1280, 390]) test(`躯干中心跟随暂停和拖动，遮挡时隐藏，${width}px`, async () => {
  const page = await browser.newPage({ viewport: { width, height: 900 } })
  page.setDefaultTimeout(8000)
  const writes = [], errors = []
  page.on('pageerror', error => errors.push(error.message))
  await page.route('**/api/**', async route => {
    const request = route.request(), path = new URL(request.url()).pathname
    if (request.method() !== 'GET') writes.push(path)
    if (path.endsWith('/media') || path.endsWith('/overlay-video')) {
      const range = request.headers().range?.match(/bytes=(\d+)-(\d*)/)
      const start = range ? +range[1] : 0, end = range?.[2] ? Math.min(+range[2], media.length - 1) : media.length - 1
      return route.fulfill({ status: range ? 206 : 200, body: media.subarray(start, end + 1), contentType: 'video/webm',
        headers: { 'Accept-Ranges': 'bytes', 'Content-Length': String(end - start + 1),
          ...(range ? { 'Content-Range': `bytes ${start}-${end}/${media.length}` } : {}) } })
    }
    return route.fulfill({ json: { result: organized, media_ready: true, result_version: 'fixture', task: { status: 'succeeded' } } })
  })
  try {
    await page.goto(base + '/e2e/actions-harness.html')
    await page.evaluate(() => document.querySelector('video').pause())
    const job = { id: 'actions-a', status: 'succeeded', media: { source_video: { status: 'available' }, overlay_video: { status: 'available' } },
      result: { video: { width: 640, height: 360, frame_count: 192, fps: 24, duration_seconds: 8 },
        overlay: { width: 640, height: 360, action_count: 3, layout: 'split_route_map_actions_v8' },
        pose_samples: [pose(0, .3), pose(24, .5), pose(48, .5, false),
          ...[72, 96, 120, 144, 168].map(source_frame_id => ({ source_frame_id, observed: false }))] } }
    await page.evaluate(job => window.actionsHarness.setJob(job), job)
    await page.waitForFunction(() => {
      const video = document.querySelector('video')
      return video?.readyState >= 2 && video.currentSrc.includes('version=fixture')
    }, null, { timeout: 8000 })
    const dot = page.locator('.torso-center-overlay circle')
    await dot.waitFor()
    await page.locator('video').evaluate(video => { video.currentTime = .5 })
    await page.waitForFunction(() => Math.abs(Number(document.querySelector('.torso-center-overlay circle')?.getAttribute('cx')) - 179.2) < 1, null, { timeout: 8000 })
    await page.screenshot({ path: fileURLToPath(new URL(`center-${width}.png`, artifacts)) })
    const position = await dot.evaluate(circle => {
      const point = circle.getBoundingClientRect(), video = document.querySelector('.replay-frame').getBoundingClientRect()
      return point.x >= video.x && point.y >= video.y && point.right <= video.right && point.bottom <= video.bottom
    })
    assert.equal(position, true)
    await page.locator('video').evaluate(video => { video.currentTime = 2 })
    await dot.waitFor({ state: 'detached' })
    await page.locator('video').evaluate(video => { video.currentTime = 1 })
    await dot.waitFor()
    await page.locator('video').evaluate(video => { video.currentTime = 7 })
    await dot.waitFor({ state: 'detached' })
    await page.evaluate(job => window.actionsHarness.setJob({ ...job, result: { ...job.result, overlay: { ...job.result.overlay, torso_center: 'v1' } } }), job)
    await page.locator('video').evaluate(video => { video.currentTime = 0 })
    await page.waitForTimeout(100)
    assert.equal(await dot.count(), 0, 'already rendered markers must not be duplicated')
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false)
    assert.deepEqual(writes, [])
    assert.deepEqual(errors, [])
  } catch (error) {
    const diagnostic = await page.evaluate(() => ({ time: document.querySelector('video')?.currentTime,
      src: document.querySelector('video')?.currentSrc, dot: document.querySelector('.torso-center-overlay')?.outerHTML }))
    throw new Error(`${error.message}\n${JSON.stringify(diagnostic)}`)
  } finally { await page.close() }
})
