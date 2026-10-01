import test, { after } from 'node:test'
import assert from 'node:assert/strict'
import { mkdir } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'
import { spawn } from 'node:child_process'
import { createRequire } from 'node:module'
const require = createRequire(import.meta.url)
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || '@playwright/test')

const base = process.env.VISUAL_REPLAY_TEST_URL || 'http://127.0.0.1:4182'
if (!process.env.VISUAL_REPLAY_TEST_URL) {
  const server = spawn(process.execPath, ['node_modules/vite/bin/vite.js', '--host', '127.0.0.1', '--port', '4182', '--strictPort'], {
    cwd: fileURLToPath(new URL('../', import.meta.url)), windowsHide: true, stdio: ['ignore', 'pipe', 'pipe'],
  })
  let output = ''
  try {
    await new Promise((resolve, reject) => {
      const timer = setTimeout(() => reject(new Error('Visual replay test server start timed out')), 15000)
      server.once('error', failure => { clearTimeout(timer); reject(failure) })
      server.once('exit', code => { clearTimeout(timer); reject(new Error(`Server exited (${code}): ${output}`)) })
      server.stdout.on('data', data => {
        output += data
        if (output.includes('Local:')) { clearTimeout(timer); resolve() }
      })
      server.stderr.on('data', data => { output += data })
    })
  } catch (failure) { server.kill(); throw failure }
  after(() => server.kill())
  process.once('exit', () => server.kill())
}
const shots = new URL('../test-results/visual-replay/', import.meta.url)
await mkdir(shots, { recursive: true })

for (const width of [1280, 390]) {
  test(`线路回放 ${width}px：尾段、动作隔离、失败重试与失效保护`, { timeout: 60000 }, async () => {
    const browser = await chromium.launch({ headless: true })
    const page = await browser.newPage({ viewport: { width, height: 900 } })
    const errors = []
    const mutations = []
    page.on('pageerror', error => errors.push(error.message))
    const metadata = { duration_seconds: 5, fps: 24, width: 640, height: 360 }
    const ready = { status: 'ready', analysis_frame_count: 120, analysis_duration_seconds: 5,
      tail_start_seconds: 5, tail_duration_seconds: 8, total_duration_seconds: 13, can_retry: true }
    let visual = { ...ready }
    const job = () => ({ id: 'visual-fixture', status: 'succeeded', original_name: '构造线路回放.webm',
      created_at: '2026-09-28T00:00:00Z', route_color: '黄色', video: metadata,
      media: { source_video: { status: 'available' }, overlay_video: { status: 'available' } },
      result: { video: metadata, holds: [], pose_samples: [], visual_replay: visual,
        attempt: { topped_out: false, contacts: [], sequence: [], action_steps: [
          { step: 1, limb: 'left_hand', hold_id: 1, start_time_seconds: 0, start_source_frame: 0 },
          { step: 2, limb: 'right_hand', hold_id: 2, start_time_seconds: 3, start_source_frame: 72 },
        ] } } })
    try {
      // This fixture verifies UI wiring and responsive layout, not device codecs.
      await page.addInitScript(() => {
        const times = new WeakMap(), paused = new WeakMap()
        const listen = HTMLMediaElement.prototype.addEventListener
        HTMLMediaElement.prototype.addEventListener = function (type, ...args) {
          if (type !== 'error') return listen.call(this, type, ...args)
        }
        Object.defineProperty(HTMLMediaElement.prototype, 'currentTime', { configurable: true,
          get() { return times.get(this) || 0 }, set(value) { times.set(this, value) } })
        Object.defineProperty(HTMLMediaElement.prototype, 'duration', { configurable: true, get() { return this.src.includes('source-video') ? 5 : 13 } })
        Object.defineProperty(HTMLMediaElement.prototype, 'paused', { configurable: true, get() { return paused.get(this) ?? true } })
        HTMLMediaElement.prototype.load = function () { queueMicrotask(() => this.dispatchEvent(new Event('loadedmetadata'))) }
        HTMLMediaElement.prototype.play = function () { paused.set(this, false); return Promise.resolve() }
        HTMLMediaElement.prototype.pause = function () { paused.set(this, true) }
      })
      await page.route('**/api/**', async route => {
        const path = new URL(route.request().url()).pathname
        if (path.includes('/media/')) return route.fulfill({ status: 200, contentType: 'video/webm', body: '' })
        if (route.request().method() === 'POST') {
          mutations.push(path)
          visual = path.endsWith('/cancel') ? { ...visual, status: 'cancelled' } : { ...visual, status: 'queued' }
          return route.fulfill({ json: job() })
        }
        if (path.endsWith('/consent-policy')) return route.fulfill({ json: { version: 'fixture', retention: {} } })
        if (path.endsWith('/coaching-policy')) return route.fulfill({ json: { enabled: false, configured: false } })
        if (path.endsWith('/coaching')) return route.fulfill({ json: { status: 'none' } })
        if (path === '/api/climb-replay/jobs') return route.fulfill({ json: [job()] })
        if (path.endsWith('/visual-fixture')) return route.fulfill({ json: job() })
        return route.fulfill({ json: path.endsWith('/test-videos') ? { items: [] } : [] })
      })
      await page.goto(`${base}/e2e/coaching-harness.html?parent`)
      await page.locator('.recent-row').click()
      const video = page.locator('.video-canvas video')
      await page.getByRole('button', { name: '查看线路回放', exact: true }).click()
      assert.equal(await video.evaluate(element => element.currentTime), 5)
      assert.equal(await page.locator('.action-focus').count(), 0)
      assert.equal(await page.locator('.event-timeline button[aria-current]').count(), 0)
      await page.getByText('线路回放 · 按本次用点顺序展示').waitFor()
      await page.locator('.event-timeline button').last().click()
      assert.equal(await video.evaluate(element => element.currentTime), 3)
      assert.equal(await page.locator('.action-focus').count(), 1)
      await page.getByRole('button', { name: '原视频', exact: true }).click()
      await page.getByRole('button', { name: '查看线路回放', exact: true }).click()
      await page.waitForFunction(() => document.querySelector('.video-canvas video').currentTime === 5)
      assert.match(await video.getAttribute('src'), /overlay-video/)
      const target = await page.getByRole('button', { name: '查看线路回放', exact: true }).boundingBox()
      assert.ok(target.height >= 44)
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false)
      await page.screenshot({ path: fileURLToPath(new URL(`ready-${width}.png`, shots)), fullPage: true })

      visual = { ...ready, status: 'failed' }
      await page.reload()
      await page.locator('.recent-row').click()
      await page.getByText('线路回放暂未生成，可重试。基础复盘可继续观看。').waitFor()
      await page.getByRole('button', { name: '重试线路回放', exact: true }).click()
      await page.getByText('正在制作线路回放，基础复盘可继续观看。').waitFor()
      assert.match(await video.getAttribute('src'), /overlay-video/)
      visual = { ...ready }
      await page.getByRole('button', { name: '查看线路回放', exact: true }).waitFor()
      assert.equal(mutations.filter(path => path.endsWith('/visual-replay/retry')).length, 1)

      visual = { ...ready, status: 'stale', stale: true }
      await page.reload()
      await page.locator('.recent-row').click()
      assert.equal(await page.getByRole('button', { name: '查看线路回放', exact: true }).count(), 0)
      assert.equal(await page.getByRole('link', { name: '导出复盘视频', exact: true }).count(), 0)
      await video.evaluate(element => { element.currentTime = 9; element.dispatchEvent(new Event('timeupdate')) })
      assert.ok(await video.evaluate(element => element.currentTime < 5 && element.paused))
      await page.getByRole('button', { name: '重新制作线路回放', exact: true }).click()
      await page.getByRole('button', { name: '停止制作', exact: true }).click()
      await page.getByRole('button', { name: '重新制作线路回放', exact: true }).waitFor()
      await page.screenshot({ path: fileURLToPath(new URL(`stale-${width}.png`, shots)), fullPage: true })
      assert.deepEqual(errors, [])
    } finally { await browser.close() }
  })
}
