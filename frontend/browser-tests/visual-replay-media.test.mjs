import test from 'node:test'
import assert from 'node:assert/strict'
import { createRequire } from 'node:module'
import { readFile, mkdir } from 'node:fs/promises'
import { createServer } from 'node:http'
import { fileURLToPath } from 'node:url'

const mediaPath = process.env.VISUAL_REPLAY_MEDIA
const expectedDuration = Number(process.env.VISUAL_REPLAY_EXPECTED_DURATION || 0)
const analysisDuration = Number(process.env.VISUAL_REPLAY_ANALYSIS_DURATION || 0)
const require = createRequire(import.meta.url)

test('真实线路回放 WebM：桌面与手机尺寸播放、拖动和下载', { skip: !mediaPath, timeout: 60000 }, async () => {
  const { chromium } = require(process.env.PLAYWRIGHT_MODULE || '@playwright/test')
  const bytes = await readFile(mediaPath)
  const server = createServer((request, response) => {
    if (request.url.startsWith('/video')) {
      const range = /bytes=(\d+)-(\d*)/.exec(request.headers.range || '')
      const start = range ? Number(range[1]) : 0
      const end = range?.[2] ? Math.min(Number(range[2]), bytes.length - 1) : bytes.length - 1
      response.writeHead(range ? 206 : 200, {
        'Content-Type': 'video/webm', 'Content-Length': end - start + 1, 'Accept-Ranges': 'bytes',
        ...(range ? { 'Content-Range': `bytes ${start}-${end}/${bytes.length}` } : {}),
        ...(request.url.includes('download') ? { 'Content-Disposition': 'attachment; filename="route-replay.webm"' } : {}),
      })
      response.end(bytes.subarray(start, end + 1))
    } else {
      response.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8' })
      response.end('<!doctype html><meta name="viewport" content="width=device-width,initial-scale=1"><title>线路回放兼容验收</title><style>body{margin:0;background:#101411;color:#f7f6f1;font:16px sans-serif}main{max-width:960px;margin:16px auto;padding:0 12px}video{display:block;width:100%;max-height:78vh;object-fit:contain}a{display:inline-flex;padding:14px;color:#f4c430}</style><main><video controls playsinline preload="metadata" src="/video"></video><a href="/video?download" download="route-replay.webm">下载线路回放</a></main>')
    }
  })
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve))
  const browser = await chromium.launch({ headless: true })
  const shots = new URL('../test-results/visual-replay-media/', import.meta.url)
  await mkdir(shots, { recursive: true })
  try {
    for (const width of [1280, 390]) {
      const context = await browser.newContext({ viewport: { width, height: 900 },
        isMobile: width < 500, hasTouch: width < 500, acceptDownloads: true })
      const page = await context.newPage()
      const errors = []
      page.on('pageerror', error => errors.push(error.message))
      await page.goto(`http://127.0.0.1:${server.address().port}`)
      await page.waitForFunction(() => { const video = document.querySelector('video'); return video.readyState >= 2 && Number.isFinite(video.duration) && video.duration > 0 })
      const metadata = await page.locator('video').evaluate(video => ({ duration: video.duration, width: video.videoWidth, height: video.videoHeight }))
      if (expectedDuration > 0) assert.ok(Math.abs(metadata.duration - expectedDuration) <= .12,
        `media duration ${metadata.duration} does not match expected ${expectedDuration}`)
      assert.ok(Math.max(metadata.width, metadata.height) <= 1280)
      const playbackStart = Math.min(4, metadata.duration / 2)
      await page.locator('video').evaluate(async (video, seconds) => { video.currentTime = seconds; await video.play() }, playbackStart)
      await page.waitForFunction(seconds => document.querySelector('video').currentTime > seconds + .2, playbackStart)
      if (analysisDuration > 0) {
        assert.ok(metadata.duration > analysisDuration)
        await page.locator('video').evaluate(async (video, seconds) => { video.currentTime = seconds; await video.play() }, analysisDuration)
        await page.waitForFunction(seconds => document.querySelector('video').currentTime > seconds + .2, analysisDuration)
      }
      const presentedTime = await page.locator('video').evaluate(video => new Promise(resolve => {
        video.pause()
        video.requestVideoFrameCallback((_now, frame) => resolve(frame.mediaTime))
        video.currentTime = video.duration - .25
      }))
      assert.ok(presentedTime > metadata.duration - .5, 'seeking must present the requested frame, not just change currentTime')
      await page.waitForFunction(() => {
        const video = document.querySelector('video')
        return !video.seeking && video.currentTime > video.duration - .5
      })
      // The video callback precedes composition; let its decoded frame reach screenshots.
      await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))))
      await page.screenshot({ path: fileURLToPath(new URL(`playback-${width}.png`, shots)), fullPage: true })
      const downloadPromise = page.waitForEvent('download')
      await page.getByRole('link', { name: '下载线路回放' }).click()
      const download = await downloadPromise
      assert.equal(await download.failure(), null)
      assert.equal((await readFile(await download.path())).length, bytes.length)
      assert.equal(await page.locator('video').evaluate(video => video.error), null)
      assert.deepEqual(errors, [])
      console.log(JSON.stringify({ viewport: width, ...metadata, download_bytes: bytes.length }))
      await context.close()
    }
  } finally {
    await browser.close()
    await new Promise(resolve => server.close(resolve))
  }
})
