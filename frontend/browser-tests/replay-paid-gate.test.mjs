import { chromium } from '@playwright/test'
import test, { after } from 'node:test'
import assert from 'node:assert/strict'
import { mkdir } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'
import { startFixtureServer } from './fixtures/server.mjs'
import { syntheticMedia } from './fixtures/actions.mjs'

const base = await startFixtureServer(4204)
const browser = await chromium.launch({ headless: true })
const media = await syntheticMedia(browser)
const artifacts = new URL('../../.tmp/replay-paid-gate/', import.meta.url)
await mkdir(artifacts, { recursive: true })
after(() => browser.close())

for (const width of [1280, 390]) test(`upload, local edits, global confirmation and explicit local RTMW start at ${width}px`, async () => {
  const page = await browser.newPage({ viewport: { width, height: width < 600 ? 844 : 900 } })
  page.setDefaultTimeout(7000)
  const writes = [], errors = []
  let job = null, revision = 1, analysisStarts = 0
  const changed = () => {
    job.holds_revision = `revision-${++revision}`
    job.holds_confirmation = null
  }
  page.on('pageerror', error => errors.push(error.message))
  await page.route('**/api/**', async route => {
    const request = route.request(), path = new URL(request.url()).pathname, method = request.method()
    if (path.endsWith('/source-video')) {
      const range = request.headers().range?.match(/bytes=(\d+)-(\d*)/)
      const start = range ? +range[1] : 0, end = range?.[2] ? Math.min(+range[2], media.length - 1) : media.length - 1
      return route.fulfill({ status: range ? 206 : 200, body: media.subarray(start, end + 1), contentType: 'video/webm',
        headers: { 'Accept-Ranges': 'bytes', 'Content-Length': String(end - start + 1),
          ...(range ? { 'Content-Range': `bytes ${start}-${end}/${media.length}` } : {}) } })
    }
    if (method !== 'GET') {
      writes.push(path)
      if (path.endsWith('/uploads')) {
        assert.equal(request.postDataJSON().route_id, '', 'new uploads use the current video sample without a saved route')
        assert.equal(request.postDataJSON().route_color_sample.source, 'video')
        return route.fulfill({ json: { id: 'upload', offset: 0 } })
      }
      if (method === 'PUT') return route.fulfill({ json: { offset: media.length } })
      if (path.endsWith('/complete')) {
        job = { id: 'constructed', original_name: 'constructed.webm', status: 'awaiting_hold_review',
          route_color: '黄色', video: { fps: 24, duration_seconds: 8 }, holds_revision: 'revision-1',
          media: { source_video: { status: 'available', retention_mode: 'keep_private_original' } },
          hold_draft: { holds: [{ id: 1, bbox: [.1, .1, .15, .15] }, { id: 2, bbox: [.6, .6, .15, .15] }],
            hold_evidence: { reference_frame: 0 } }, hold_review_history: [] }
      } else if (path.endsWith('/confirm-all')) {
        assert.equal(request.postDataJSON().revision, job.holds_revision)
        job.holds_confirmation = { revision: job.holds_revision }
      } else if (method === 'DELETE') {
        job.hold_draft.holds = job.hold_draft.holds.filter(hold => hold.id !== +path.split('/').at(-1))
        changed()
      } else if (path.endsWith('/preview')) return route.fulfill({ json: {
        source_polygon: [[.3, .3], [.5, .3], [.5, .5], [.3, .5]], supporting_frames: 2,
      } })
      else if (path.endsWith('/holds/point')) {
        job.hold_draft.holds.push({ id: 3, bbox: [.3, .3, .2, .2], identity_source: 'user_confirmed_video_click', review_version: 1 })
        job.hold_review_history.push({ operation: 'add_hold_at_point', version: 1, point_xy: [.4, .4], time_seconds: 0 })
        changed()
      } else if (path.endsWith('/analysis/start')) {
        assert.equal(job.holds_confirmation?.revision, job.holds_revision)
        assert.equal(request.postDataJSON().consent_granted, true)
        assert.equal(request.postDataJSON().pose_fps, 10)
        assert.deepEqual(request.postDataJSON().focus_windows, [])
        analysisStarts++
        job.status = 'queued'
        job.stage = '等待本地姿态分析'
      } else throw new Error(`Unexpected write ${method} ${path}`)
      return route.fulfill({ json: job })
    }
    if (path.endsWith('/jobs')) return route.fulfill({ json: job ? [job] : [] })
    if (path.endsWith('/constructed')) return route.fulfill({ json: job })
    if (path.endsWith('/consent-policy')) return route.fulfill({ json: { version: 'fixture', provider: '本机 RTMW-L', execution: 'local', uploads_frames: false, enabled: true } })
    if (path.endsWith('/test-videos')) return route.fulfill({ json: { items: [] } })
    return route.fulfill({ json: { routes: [] } })
  })
  try {
    await page.goto(base + '/e2e/coaching-harness.html?parent')
    await page.locator('input[type=file]').first().setInputFiles({ name: 'constructed.webm', mimeType: 'video/webm', buffer: media })
    const upload = page.getByRole('button', { name: '上传并本地识别岩点', exact: true })
    assert.equal(await upload.isDisabled(), true, 'upload requires a sample from the current video')
    await page.waitForFunction(() => document.querySelector('.video-canvas video')?.readyState >= 2)
    await page.getByRole('button', { name: '从画面点选样本岩点', exact: true }).click()
    await page.getByLabel('在暂停的视频画面中点击目标线路岩点取色').click({ position: { x: 30, y: 30 } })
    await page.getByRole('status').filter({ hasText: /#[0-9A-F]{6}/ }).waitFor()
    await page.getByRole('button', { name: '上传并本地识别岩点', exact: true }).click()
    await page.getByRole('button', { name: '确认全部岩点', exact: true }).waitFor()
    await page.waitForFunction(() => document.querySelector('.video-canvas video')?.readyState >= 2)
    const start = page.getByRole('button', { name: '开始本地分析', exact: true })
    assert.equal(analysisStarts, 0)
    assert.equal(await start.isVisible(), false)
    await page.getByRole('button', { name: '确认全部岩点', exact: true }).click()
    await page.getByRole('button', { name: '全部岩点已确认', exact: true }).waitFor()
    assert.equal(analysisStarts, 0, 'global confirmation alone must not start pose analysis')
    assert.equal(await start.isEnabled(), true, 'confirmation enables the separate local start button')
    await page.getByRole('button', { name: '选择岩点 2，缺少轮廓', exact: true }).click()
    await page.getByRole('button', { name: '删除所选岩点', exact: true }).click()
    await page.getByText('已删除岩点并保存草稿，请继续检查并确认全部岩点。').waitFor()
    assert.equal(await start.isVisible(), false, 'editing invalidates the global confirmation')
    await page.getByRole('button', { name: '补删点', exact: true }).click()
    await page.locator('.hold-coordinate-entry > summary').click()
    for (const [label, value] of [['左侧', '30'], ['顶部', '30'], ['右侧', '50'], ['底部', '50']]) {
      await page.getByLabel(label, { exact: false }).fill(value)
    }
    await page.getByRole('button', { name: '预览轮廓', exact: true }).click()
    await page.getByRole('button', { name: '轮廓正确，确认补入', exact: true }).click()
    await page.getByText('已补入岩点并保存草稿，可继续补点；全部补完后再确认并分析。').waitFor()
    assert.equal(analysisStarts, 0)
    assert.equal(await start.isVisible(), false, 'a single hold confirmation is not global confirmation')
    await page.getByRole('button', { name: '确认全部岩点', exact: true }).click()
    await page.getByRole('button', { name: '全部岩点已确认', exact: true }).waitFor()
    assert.equal(await start.isEnabled(), true)
    await page.screenshot({ path: fileURLToPath(new URL(`ready-${width}.png`, artifacts)), fullPage: true })
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1), false)
    await start.click()
    await page.getByText('任务正在排队', { exact: true }).waitFor()
    assert.equal(analysisStarts, 1)
    assert.equal(writes.filter(path => path.endsWith('/analysis/start')).length, 1)
    assert.deepEqual(errors, [])
  } finally { await page.close() }
})
