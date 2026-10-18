import { chromium } from '@playwright/test'
import test, { after } from 'node:test'
import assert from 'node:assert/strict'
import { mkdir } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'
import { startFixtureServer } from './fixtures/server.mjs'
import { syntheticMedia } from './fixtures/actions.mjs'

const base = await startFixtureServer(4201)
const browser = await chromium.launch({ headless: true })
const media = await syntheticMedia(browser)
after(() => browser.close())
const artifacts = new URL('../../.tmp/replay-preview-verification/', import.meta.url)
await mkdir(artifacts, { recursive: true })

async function setup(width = 1280) {
  const page = await browser.newPage({ viewport: { width, height: 900 } })
  const writes = [], errors = [], reads = []
  page.on('pageerror', error => errors.push(error.message))
  await page.route('**/api/**', async route => {
    const request = route.request(), path = new URL(request.url()).pathname
    if (request.method() !== 'GET') writes.push(path)
    else reads.push(path)
    const json = path.endsWith('/consent-policy') ? { version: 'fixture', enabled: true }
      : path.endsWith('/jobs') ? []
        : path.endsWith('/test-videos') ? { items: [] } : { routes: [] }
    await route.fulfill({ json })
  })
  await page.goto(base + '/e2e/coaching-harness.html?parent')
  return { page, writes, errors, reads }
}
async function select(page, buffer = media, name = 'constructed.webm') {
  await page.locator('input[type=file]').first().setInputFiles({ name, mimeType: 'video/webm', buffer })
}
async function ready(page) {
  await page.waitForFunction(() => {
    const video = document.querySelector('.video-canvas video')
    return video?.readyState >= 2 && video.videoWidth > 0 && !document.querySelector('.video-preview-state')
  })
}

for (const width of [1280, 390]) test(`local preview, buffering and recovery at ${width}px`, async () => {
  const { page, writes, errors, reads } = await setup(width)
  try {
    await select(page)
    await ready(page)
    await page.getByRole('button', { name: '从画面点选样本岩点', exact: true }).waitFor({ state: 'visible' })
    assert.equal(await page.locator('#replay-saved-route').count(), 0)
    assert.equal(await page.getByText('关联线路', { exact: true }).count(), 0)
    assert.equal(reads.some(path => /photo-routes.*routes/.test(path)), false, 'video setup does not load saved routes')
    await page.screenshot({ path: fileURLToPath(new URL(`direct-color-${width}.png`, artifacts)), fullPage: true })
    assert.equal(await page.locator('input[type=color], input[name=route-color], #replay-extra-color').count(), 0)
    const upload = page.getByRole('button', { name: '上传并本地识别岩点', exact: true })
    assert.equal(await upload.isDisabled(), true)
    await page.getByRole('button', { name: '从画面点选样本岩点', exact: true }).waitFor({ state: 'visible' })
    assert.equal(await page.getByRole('button', { name: '从画面点选样本岩点', exact: true }).isEnabled(), true)
    await page.locator('.video-canvas video').evaluate(video => video.dispatchEvent(new Event('waiting')))
    await page.getByRole('status').filter({ hasText: '正在加载视频画面' }).waitFor()
    assert.equal(await page.getByRole('button', { name: '从画面点选样本岩点', exact: true }).isEnabled(), false)
    assert.equal(await page.getByText('文件已选择，尚未上传。可以用调色盘选色后上传', { exact: false }).count(), 0)
    await page.screenshot({ path: fileURLToPath(new URL(`loading-${width}.png`, artifacts)), fullPage: true })
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)
    assert.equal(overflow, false)
    await page.locator('.video-canvas video').evaluate(video => video.dispatchEvent(new Event('canplay')))
    await ready(page)
    await page.getByRole('button', { name: '从画面点选样本岩点', exact: true }).click()
    await page.getByLabel('在暂停的视频画面中点击目标线路岩点取色').waitFor()
    await page.keyboard.press('Escape')
    assert.equal(await upload.isDisabled(), true, 'cancelled sampling cannot enable upload')
    await page.getByRole('button', { name: '从画面点选样本岩点', exact: true }).click()
    await page.getByLabel('在暂停的视频画面中点击目标线路岩点取色').click({ position: { x: 30, y: 30 } })
    await page.getByRole('status').filter({ hasText: /#[0-9A-F]{6}/ }).waitFor()
    assert.equal(await upload.isEnabled(), true)
    await select(page); await ready(page)
    await page.getByRole('button', { name: '从画面点选样本岩点', exact: true }).waitFor({ state: 'visible' })
    assert.equal(await upload.isDisabled(), true, 'a replacement file must be sampled again')
    assert.deepEqual(writes, [])
    assert.deepEqual(errors, [])
  } finally { await page.close() }
})

test('corrupt file reports decoding failure, retries and a replacement recovers', async () => {
  const { page, writes, errors } = await setup(390)
  try {
    await select(page, Buffer.from('invalid video contents'), 'broken.webm')
    await page.getByRole('alert').filter({ hasText: '暂时无法预览视频' }).waitFor()
    await page.getByText('无法预览，请重新加载或更换视频。', { exact: true }).waitFor()
    assert.equal(await page.getByRole('button', { name: '从画面点选样本岩点', exact: true }).isEnabled(), false)
    assert.equal(await page.getByRole('button', { name: '上传并本地识别岩点', exact: true }).isDisabled(), true,
      'an unavailable video cannot provide the required color sample')
    await page.screenshot({ path: fileURLToPath(new URL('error-390.png', artifacts)), fullPage: true })
    const fits = await page.locator('.video-preview-message').evaluate(message => {
      const outer = message.parentElement.getBoundingClientRect(), inner = message.getBoundingClientRect()
      return inner.top >= outer.top && inner.bottom <= outer.bottom
    })
    assert.equal(fits, true, 'error and recovery controls must fit the mobile stage')
    await page.getByRole('button', { name: '重新加载画面', exact: true }).click()
    await page.getByRole('alert').filter({ hasText: '暂时无法预览视频' }).waitFor()
    await page.getByRole('button', { name: '更换视频', exact: true }).click()
    await select(page)
    await ready(page)
    await page.waitForTimeout(100)
    assert.equal(await page.getByRole('alert').filter({ hasText: '暂时无法预览视频' }).count(), 0)
    assert.deepEqual(writes, [])
    assert.deepEqual(errors, [])
  } finally { await page.close() }
})

test('a real audio-only container cannot be mistaken for a ready video', async () => {
  const { page, writes, errors } = await setup()
  try {
    const audio = await page.evaluate(async () => {
      const context = new AudioContext()
      const oscillator = context.createOscillator(), destination = context.createMediaStreamDestination()
      oscillator.connect(destination); oscillator.start()
      const recorder = new MediaRecorder(destination.stream, { mimeType: 'audio/webm' })
      const chunks = [], stopped = new Promise(resolve => { recorder.onstop = resolve })
      recorder.ondataavailable = event => chunks.push(event.data)
      recorder.start(); await new Promise(resolve => setTimeout(resolve, 300)); recorder.stop(); await stopped
      oscillator.stop(); await context.close()
      return Array.from(new Uint8Array(await new Blob(chunks).arrayBuffer()))
    })
    await select(page, Buffer.from(audio), 'only-audio.webm')
    await page.getByRole('alert').filter({ hasText: '当前浏览器未能读取视频画面' }).waitFor()
    const video = await page.locator('.video-canvas video').evaluate(v => ({ width: v.videoWidth, duration: v.duration, ready: v.readyState }))
    assert.equal(video.width, 0)
    assert.ok(video.ready >= 1 && video.duration > 0)
    assert.equal(await page.getByRole('button', { name: '从画面点选样本岩点', exact: true }).isEnabled(), false)
    assert.deepEqual(writes, [])
    assert.deepEqual(errors, [])
  } finally { await page.close() }
})

test('a stalled frame times out and changing files cancels the old deadline', async () => {
  const { page, writes, errors } = await setup()
  try {
    await select(page); await ready(page)
    await page.clock.install()
    await page.locator('.video-canvas video').evaluate(video => {
      Object.defineProperty(video, 'readyState', { configurable: true, value: 1 })
      video.dispatchEvent(new Event('waiting'))
    })
    await page.clock.fastForward(12001)
    await page.getByRole('alert').filter({ hasText: '画面加载超时' }).waitFor()
    await page.locator('.video-canvas video').evaluate(video => { delete video.readyState })
    await select(page); await ready(page)
    await page.clock.fastForward(20000)
    await ready(page)
    assert.deepEqual(writes, [])
    assert.deepEqual(errors, [])
  } finally { await page.close() }
})
