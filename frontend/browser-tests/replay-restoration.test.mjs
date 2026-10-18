import { startFixtureServer } from './fixtures/server.mjs'
import { organized, syntheticMedia } from './fixtures/actions.mjs'
import { chromium } from '@playwright/test'
import test, { after } from 'node:test'
import assert from 'node:assert/strict'
import { mkdir } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'
import { replayFileAction } from './fixtures/panels.mjs'

const base = await startFixtureServer(4199)
const browser = await chromium.launch({ headless: true })
const media = await syntheticMedia(browser)
const artifacts = new URL('../../.tmp/hold-confirmation-20261006/', import.meta.url)
await mkdir(artifacts, { recursive: true })
after(() => browser.close())

async function setup(width, source = true, prepared) {
  const page = await browser.newPage({ viewport: { width, height: width < 600 ? 844 : 900 } })
  const writes = [], errors = [], actionReads = [], localAnalyses = []
  let job = { id: 'restored-record', status: 'succeeded', original_name: 'constructed.webm', route_color: '黄色',
    video: { duration_seconds: 8, fps: 24 }, created_at: '2026-10-01T00:00:00Z', hold_review_history: [], holds_revision: 'fixture-0',
    media: { source_video: { status: source ? 'available' : 'deleted' }, overlay_video: { status: 'available' } },
    result: { video: { duration_seconds: 8, fps: 24 }, holds: [{ id: 1, bbox: [.1, .1, .15, .15] }],
      attempt: { contacts: [], action_steps: [1, 3, 5].map((time, index) => ({
        limb: 'left_hand', hold_id: 1, start_time_seconds: time, end_time_seconds: time + 1,
        start_source_frame: time * 24, supplementary_name: `换点 ${index + 1}`,
      })) } } }
  page.on('pageerror', e => errors.push(e.message))
  await page.route('**/api/**', async route => {
    const request = route.request(), path = new URL(request.url()).pathname
    if (/\/(?:source-video|overlay-video|reviewed-overlay-video)$/.test(path)) {
      const range = request.headers().range?.match(/bytes=(\d+)-(\d*)/)
      const start = range ? +range[1] : 0, end = range?.[2] ? Math.min(+range[2], media.length - 1) : media.length - 1
      return route.fulfill({ status: range ? 206 : 200, body: media.subarray(start, end + 1), contentType: 'video/webm',
        headers: { 'Accept-Ranges': 'bytes', 'Content-Length': String(end - start + 1),
          ...(range ? { 'Content-Range': `bytes ${start}-${end}/${media.length}` } : {}) } })
    }
    if (request.method() !== 'GET') {
      writes.push({ path, body: request.postData() ? request.postDataJSON() : null })
      if (path.endsWith('/preview')) return route.fulfill({ json: {
        point_xy: [.4, .4], region_xyxy: [.3, .3, .5, .5], time_seconds: 3,
        source_polygon: [[.3, .3], [.5, .3], [.5, .5], [.3, .5]], supporting_frames: 2,
      } })
      if (path.endsWith('/holds/point')) {
        job = structuredClone(job)
        job.hold_edit_draft ||= { holds: structuredClone(job.result.holds) }
        const version = job.hold_review_history.length + 1
        job.hold_edit_draft.holds.push({ id: version + 1, bbox: [.3, .3, .2, .2], identity_source: 'user_confirmed_video_click', review_version: version })
        job.hold_review_history.push({ operation: 'add_hold_at_point', version, time_seconds: 3, point_xy: [.4, .4] })
        job.holds_revision = `fixture-${version}`
        job.holds_pending_local_analysis = true
        job.holds_confirmation = null
      } else if (path.endsWith('/holds/point/1/undo')) {
        job = structuredClone(job)
        job.hold_edit_draft.holds = job.hold_edit_draft.holds.filter(h => h.review_version !== 1)
        job.holds_revision = 'fixture-undo'
      } else if (path.endsWith('/confirm-all')) {
        job = structuredClone(job)
        assert.equal(request.postDataJSON().revision, job.holds_revision)
        job.result.holds = job.hold_edit_draft.holds
        job.result.hold_review_version = 4
        job.hold_edit_draft = null
        job.holds_pending_local_analysis = false
        job.holds_confirmation = { revision: job.holds_revision }
        job.media.reviewed_overlay_video = { status: 'available' }
        localAnalyses.push(path)
      } else throw new Error(`Unexpected write: ${path}`)
      return route.fulfill({ json: job })
    }
    if (path.endsWith('/actions')) {
      actionReads.push(path)
      return route.fulfill({ json: { task: { status: 'idle' }, result_version: null, media_ready: false,
        result: prepared || { ...structuredClone(organized), groups: [] }, revision_count: 0, cloud_configured: false, export: { status: 'idle' } } })
    }
    if (path.endsWith('/consent-policy')) return route.fulfill({ json: { version: 'fixture', enabled: true } })
    if (path.endsWith('/test-videos')) return route.fulfill({ json: { items: [] } })
    if (path.endsWith('/jobs')) return route.fulfill({ json: [job] })
    if (path.endsWith('/restored-record')) return route.fulfill({ json: job })
    return route.fulfill({ json: { routes: [] } })
  })
  await page.goto(base + '/e2e/coaching-harness.html?parent&replay=restored-record')
  await page.waitForFunction(() => document.querySelector('.unified-replay video')?.readyState >= 2)
  if (!prepared || prepared.groups.length) await page.getByRole('navigation', { name: '动作时间轴' }).getByRole('button').first().waitFor()
  return { page, writes, errors, actionReads, localAnalyses }
}

for (const width of [1280, 390]) test(`restore saved action jumps, statistics and hold repair at ${width}px`, async () => {
  const { page, writes, errors, actionReads, localAnalyses } = await setup(width)
  try {
    const mainVideo = page.locator('.unified-replay video')
    const entry = page.getByRole('button', { name: '补充岩点', exact: true })
    const entryBox = await entry.boundingBox(), videoBox = await mainVideo.boundingBox()
    assert.ok(entryBox.y >= 0 && entryBox.y + entryBox.height <= page.viewportSize().height,
      'hold repair must be visible immediately when opening a record')
    assert.ok(entryBox.y + entryBox.height <= videoBox.y, 'hold repair must precede the video and action timeline')
    assert.equal(await entry.evaluate(button => !!button.closest('details')), false)
    assert.equal(await page.getByRole('dialog', {name:'更多复盘资料',exact:true}).count(),0)
    if (!process.env.REPLAY_SKIP_SCREENSHOTS) await page.screenshot({ path: fileURLToPath(new URL(`entry-${width}.png`, artifacts)) })
    assert.equal(await mainVideo.evaluate(v => v.playbackRate), .75)
    await page.getByRole('navigation', { name: '动作时间轴' }).getByRole('button').nth(1).click()
    assert.ok(await mainVideo.evaluate(v => v.currentTime) >= 3)
    assert.equal(writes.length, 0, 'old records must work without preparing or uploading anything')
    await page.getByRole('button', { name: '整段观看', exact: true }).click()
    await mainVideo.evaluate(v => { v.pause(); v.dispatchEvent(new Event('ended')) })
    assert.equal(await page.locator('.summary-overlay,.summary-orb').count(),0)
    await page.getByRole('region',{name:'基础数据统计',exact:true}).waitFor()
    await page.getByRole('button', { name: '补充岩点', exact: true }).click()
    const readsBeforeEdits = actionReads.length
    await page.waitForFunction(() => document.querySelector('.video-canvas video')?.readyState >= 2)
    assert.equal(await mainVideo.isVisible(), false)
    assert.equal(await mainVideo.evaluate(v => v.paused), true)
    assert.equal(await page.locator('.hold-draw-surface').isVisible(), true)
    const surface = await page.locator('.hold-draw-surface').boundingBox()
    await page.mouse.move(surface.x + surface.width * .3, surface.y + surface.height * .3)
    await page.mouse.down()
    await page.mouse.move(surface.x + surface.width * .5, surface.y + surface.height * .5, { steps: 5 })
    await page.mouse.up()
    await page.getByRole('button', { name: '取消候选岩点', exact: true }).waitFor()
    const confirmation = page.getByRole('button', { name: '轮廓正确，确认补入', exact: true })
    const confirmBox = await confirmation.boundingBox()
    assert.ok(confirmBox.y >= 0 && confirmBox.y + confirmBox.height <= page.viewportSize().height,
      'the explicit confirmation must remain in view after drawing a hold')
    assert.equal(await confirmation.evaluate(button => !!button.closest('details')), false)
    assert.equal(await confirmation.evaluate(button => button === document.activeElement), true)
    if (!process.env.REPLAY_SKIP_SCREENSHOTS) await page.screenshot({ path: fileURLToPath(new URL(`confirm-${width}.png`, artifacts)) })
    assert.ok(writes[0].path.endsWith('/preview'))
    assert.equal(writes.length, 1, 'dragging a box must not save before confirmation')
    await page.getByRole('button', { name: '取消候选岩点', exact: true }).click()
    await page.locator('.hold-coordinate-entry > summary').click()
    for (const [label, value] of [['左侧', '30'], ['顶部', '30'], ['右侧', '50'], ['底部', '50']]) {
      await page.getByLabel(label, { exact: false }).fill(value)
    }
    await page.getByRole('button', { name: '预览轮廓', exact: true }).click()
    await page.getByLabel('待确认的岩点轮廓', { exact: true }).waitFor()
    assert.equal(writes.length, 2)
    assert.ok(writes[1].path.endsWith('/preview'))
    await page.getByRole('button', { name: '轮廓正确，确认补入', exact: true }).click()
    await page.getByText('已补入岩点并保存草稿，可继续补点；全部补完后再确认并分析。').waitFor()
    assert.ok(writes[2].path.endsWith('/holds/point'))
    assert.deepEqual(writes[2].body.region_xyxy, [.3, .3, .5, .5])
    await page.getByRole('button', { name: '补删点', exact: true }).click()
    await page.locator('.hold-draw-surface').waitFor()
    assert.equal(writes.length, 3, 'continuing to draw must not confirm or save a hold automatically')
    await page.locator('.hold-coordinate-entry > summary').click()
    for (const [label, value] of [['左侧', '55'], ['顶部', '30'], ['右侧', '75'], ['底部', '50']]) {
      await page.getByLabel(label, { exact: false }).fill(value)
    }
    await page.getByRole('button', { name: '预览轮廓', exact: true }).click()
    await page.getByRole('button', { name: '轮廓正确，确认补入', exact: true }).click()
    await replayFileAction(page, '记录与版本')
    await page.locator('.manual-hold-history .media-row').nth(1).waitFor({ state: 'attached' })
    assert.equal(localAnalyses.length, 0, 'two separate point confirmations must only save the draft')
    assert.equal(actionReads.length, readsBeforeEdits, 'pending points must not refresh the previous analysis')
    await page.locator('.manual-hold-history > summary').click()
    await page.getByRole('button', { name: '查看补点', exact: true }).first().click()
    await replayFileAction(page, '记录与版本')
    await page.locator('.manual-hold-history > summary').click()
    await page.getByRole('button', { name: '撤销补点', exact: true }).first().click()
    await page.getByText('已撤销第 1 次补点并保存草稿；其他补点保留，全部补完后再确认并分析。').waitFor()
    assert.ok(writes.at(-1).path.endsWith('/holds/point/1/undo'))
    assert.equal(localAnalyses.length, 0)
    assert.equal(actionReads.length, readsBeforeEdits)
    await page.getByRole('button', { name: '关闭面板', exact: true }).click()
    if (!process.env.REPLAY_SKIP_SCREENSHOTS) await page.screenshot({ path: fileURLToPath(new URL(`batch-pending-${width}.png`, artifacts)), fullPage: true })
    await page.getByRole('button', { name: '确认全部岩点并本地分析', exact: true }).click()
    await page.getByText('全部岩点已确认，本地分析已完成，未新增姿态请求。').waitFor()
    assert.equal(localAnalyses.length, 1)
    assert.ok(writes.at(-1).path.endsWith('/confirm-all'))
    assert.equal(writes.some(write => write.path.endsWith('/analysis/start')), false)
    assert.ok(actionReads.length > readsBeforeEdits, 'only the completed batch refreshes the main replay')
    await page.getByRole('button', { name: '返回复盘', exact: true }).click()
    await page.waitForFunction(() => document.querySelector('.unified-replay video')?.readyState >= 2)
    assert.equal(await mainVideo.isVisible(), true)
    assert.equal(await page.locator('.video-canvas video').count(), 0)
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1), false, JSON.stringify(await page.evaluate(()=>[...document.querySelectorAll('body *')].filter(el=>el.getBoundingClientRect().width && el.getBoundingClientRect().right>innerWidth+1).map(el=>({tag:el.tagName,class:el.className,right:el.getBoundingClientRect().right})).slice(-12))))
    assert.deepEqual(errors, [])
  } finally { await page.close() }
})

test('old retained video keeps action jumps and statistics when the source was deleted', async () => {
  const { page, writes, errors } = await setup(390, false)
  try {
    assert.equal(await page.getByRole('button', { name: '补充岩点', exact: true }).isDisabled(), true)
    await page.getByRole('navigation', { name: '动作时间轴' }).getByRole('button').nth(2).click()
    assert.ok(await page.locator('.unified-replay video').evaluate(v => v.currentTime) >= 5)
    assert.equal(await page.getByRole('button',{name:'复盘总结',exact:true}).count(),0)
    await page.getByRole('region',{name:'基础数据统计',exact:true}).waitFor()
    assert.equal(writes.length, 0)
    assert.deepEqual(errors, [])
  } finally { await page.close() }
})

test('displacement groups replace repeated legacy steps without preparing media', async () => {
  const result = { ...structuredClone(organized), segmentation_basis: 'significant_axis_displacement' }
  result.groups = result.groups.slice(0, 2)
  const { page, writes, errors } = await setup(1280, true, result)
  try {
    assert.equal(await page.getByRole('navigation', { name: '动作时间轴' }).getByRole('button').count(), 2)
    await page.getByRole('region',{name:'基础数据统计',exact:true}).waitFor()
    assert.equal(await page.locator('.summary-overlay,.summary-orb,.rhythm-track').count(),0)
    assert.deepEqual(writes, [])
    assert.deepEqual(errors, [])
  } finally { await page.close() }
})

test('missing observations preserve statistics without a rhythm card and do not restore duplicate steps', async () => {
  const result = { ...structuredClone(organized), segmentation_basis: 'significant_axis_displacement', groups: [],
    motion_summary: { duration_seconds: 8, segments: [{kind: 'unknown', start_seconds: 0, end_seconds: 8}],
      totals: [{kind: 'moving', label: '移动', percent: 0, seconds: 0},
        {kind: 'relative_still', label: '姿态停留', percent: 0, seconds: 0},
        {kind: 'unknown', label: '未观测', percent: 100, seconds: 8}] } }
  const { page, writes, errors } = await setup(390, true, result)
  try {
    await page.getByRole('region',{name:'基础数据统计',exact:true}).waitFor()
    assert.equal(await page.getByRole('navigation', { name: '动作时间轴' }).count(),0)
    assert.equal(await page.locator('.summary-overlay,.summary-orb').count(),0)
    assert.deepEqual(writes, [])
    assert.deepEqual(errors, [])
  } finally { await page.close() }
})
