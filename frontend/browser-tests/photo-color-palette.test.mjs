import test, { after } from 'node:test'
import assert from 'node:assert/strict'
import { mkdir } from 'node:fs/promises'
import { chromium } from '@playwright/test'
import { startFixtureServer } from './fixtures/server.mjs'

const base = await startFixtureServer(4198)
const browser = await chromium.launch({ headless: true })
after(() => browser.close())
const shots = new URL('../test-results/photo-palette/', import.meta.url)
await mkdir(shots, { recursive: true })

for (const flowVersion of [3, 2]) for (const width of [1280, 390]) test(`sample original before recognition, then repair v${flowVersion} at ${width}px`, async () => {
  const page = await browser.newPage({ viewport: { width, height: 900 } })
  const errors = [], writes = []
  page.on('pageerror', error => errors.push(error.message))
  const detectedObjects = [
      { id: 'yellow', color_group: '黄色', contour: [[100,100],[160,100],[160,160],[100,160]], object_version: 1 },
      { id: 'blue', color_group: '蓝色', contour: [[250,100],[310,100],[310,160],[250,160]], object_version: 1 },
    ]
  const board = { id: 'palette-board', version: 1, width: 600, height: 800,
    original_asset: { filename: 'palette.svg' }, objects: flowVersion === 2 ? structuredClone(detectedObjects) : [] }
  const session = { id: 'palette-session', version: 1, flow_version: flowVersion, status: 'awaiting_color', board,
    colors: [], color_groups: [], ai: {}, route: null }
  let failContour = true, finishRecognition = false
  await page.route('**/api/**', async route => {
    const request = route.request(), path = new URL(request.url()).pathname
    if (path.endsWith('/assets/palette.svg')) return route.fulfill({ contentType: 'image/svg+xml', body:
      '<svg xmlns="http://www.w3.org/2000/svg" width="600" height="800"><rect width="600" height="800" fill="#ccc"/><path d="M100 100H160V160H100Z" fill="#e1b91d"/><path d="M250 100H310V160H250Z" fill="#3478bc"/><path d="M100 280H160V340H100Z" fill="#e1b91d"/></svg>' })
    if (request.method() !== 'GET') {
      const body = request.postDataJSON(); writes.push({ path, body })
      if (path.endsWith('/color')) {
        assert.equal(body.color, '黄色'); assert.equal(body.member_ids, undefined); assert.equal(body.board_version, 1); assert.equal(body.recognize, true)
        session.status = 'processing'; session.color = body.color; session.version++
        session.flow_version = 3; session.board.objects = []
        session.stage = '正在识别所选颜色线路'; session.progress = 0
      } else if (path.endsWith('/members')) {
        session.route.members = body.member_ids.map(object_id => ({ object_id, roles: [], tags: [], note: '' })); session.version++
      } else if (path.endsWith('/add-contour')) {
        if (failContour) { failContour = false; return route.fulfill({ status: 503, json: { detail: '构造保存失败，请重试' } }) }
        assert.equal(body.board_version, 1); assert.equal(body.contour.length, 3)
        session.board.objects.push({ id: 'drawn', color_group: '黄色', contour: body.contour, object_version: 1 })
        session.board.version++; session.version++
        session.route.members.push({ object_id: 'drawn', roles: [], tags: [], note: '' })
      } else throw new Error(`Unexpected mutation: ${path}`)
      return route.fulfill({ json: session })
    }
    if (path === '/api/photo-routes/workflow/current' && session.status === 'processing' && finishRecognition) {
      session.board.objects = structuredClone(detectedObjects); session.status = 'ready'; session.progress = 100; session.version++
      session.ai = { status: 'not_requested' }
      session.route = { id: 'palette-route', members: [{ object_id: 'yellow', roles: [], tags: [], note: '' }] }
    }
    const responses = {
      '/api/auth/session': { authenticated: true, auth_enabled: true, username: 'palette-fixture', display_name: '测试' },
      '/api/pilot/edit-lease': { active: false, owned_by_me: false },
      '/api/holds/mapping': {}, '/api/holds/vectors': {}, '/api/holds/assets': [], '/api/my-boards': [], '/api/standard-board/routes': [],
      '/api/photo-routes/workflow/current': session,
    }
    return route.fulfill({ json: responses[path] ?? {} })
  })
  async function photoPoint(x, y) {
    const image = page.locator('.photo-work__image')
    await image.scrollIntoViewIfNeeded()
    let bounds = await image.boundingBox()
    // Keep the target clear of the app's fixed mobile header and bottom controls.
    await page.evaluate(targetY => window.scrollBy(0, targetY - innerHeight * .4), bounds.y + y / 800 * bounds.height)
    bounds = await image.boundingBox()
    await page.mouse.click(bounds.x + x / 600 * bounds.width, bounds.y + y / 800 * bounds.height)
  }
  try {
    await page.goto(base + '/#/photo-routes')
    const palette = page.getByLabel('打开调色盘选择线路颜色')
    await palette.waitFor()
    await page.waitForFunction(() => document.querySelector('.photo-work__image img')?.naturalWidth > 0)
    assert.equal(await page.getByRole('button', { name: '补充岩点', exact: true }).count(), 0)
    assert.equal(await page.locator('.photo-work__image polygon').count(), 0)
    assert.equal(await page.getByRole('button', { name: '识别线路', exact: true }).isDisabled(), true)
    await palette.fill('#3478bc'); await palette.dispatchEvent('input')
    await page.getByText('已选蓝色 · 未识别', { exact: true }).waitFor()
    assert.equal(await page.locator('.is-route-contour').count(), 0)
    await palette.fill('#2f8c62'); await palette.dispatchEvent('input')
    assert.equal(await page.getByRole('button', { name: '识别绿色线路' }).isDisabled(), false)
    // Direct sampling works without a detected hold or a contour overlay.
    await photoPoint(130, 130)
    await page.getByText('已选黄色 · 未识别', { exact: true }).waitFor()
    assert.match(await page.locator('.photo-work__sample').innerText(), /#E1B91D/)
    await page.getByRole('button', { name: '放大', exact: true }).click()
    await page.getByRole('button', { name: '从照片取色', exact: true }).click()
    await photoPoint(280, 130)
    await page.getByText('已选蓝色 · 未识别', { exact: true }).waitFor()
    assert.match(await page.locator('.photo-work__sample').innerText(), /#3478BC/)
    await photoPoint(130, 130)
    await page.getByText('已选黄色 · 未识别', { exact: true }).waitFor()
    await page.getByRole('button', { name: '完整显示', exact: true }).click()
    await page.screenshot({ path: new URL(`color-${width}.png`, shots).pathname.replace(/^\/(\w:)/, '$1'), fullPage: true })
    assert.equal(writes.length, 0)
    await page.getByRole('button', { name: '识别黄色线路' }).click()
    await page.getByRole('heading', { name: '正在识别所选颜色线路', exact: true }).waitFor()
    assert.equal(await page.getByRole('button', { name: '补充岩点', exact: true }).count(), 0)
    assert.equal(writes.length, 1)
    finishRecognition = true
    await page.getByRole('button', { name: '补点', exact: true }).click()
    assert.equal(await page.locator('.photo-work__image polygon').count(), 2)
    await photoPoint(280, 130)
    await page.getByRole('button', { name: '加入线路', exact: true }).filter({ visible: true }).click()
    await page.getByText('2 个岩点 · 进度已保存', { exact: true }).waitFor()
    await page.getByRole('button', { name: '手动描边补点', exact: true }).click()
    await photoPoint(105, 285); await photoPoint(155, 285); await photoPoint(155, 335)
    assert.equal(await page.getByRole('button', { name: '保存线路', exact: true }).filter({ visible: true }).isDisabled(), true)
    await page.screenshot({ path: new URL(`repair-${width}.png`, shots).pathname.replace(/^\/(\w:)/, '$1'), fullPage: true })
    await page.reload()
    await page.getByText('已描 3 个边缘点', { exact: true }).waitFor()
    assert.equal(await page.locator('.photo-work__draft-point').count(), 3)
    await page.getByRole('button', { name: '保存补点', exact: true }).click()
    await page.getByText('构造保存失败，请重试', { exact: true }).waitFor()
    await page.getByRole('button', { name: '重试未完成的修改' }).click()
    await page.getByRole('button', { name: '复核', exact: true }).waitFor()
    await page.getByText('3 个岩点 · 进度已保存', { exact: true }).waitFor()
    const attempts = writes.filter(write => write.path.endsWith('/add-contour'))
    assert.equal(attempts.length, 2); assert.deepEqual(attempts[0].body, attempts[1].body)
    assert.equal(await page.locator('.photo-work__draft-contour').count(), 0)
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), true)
    assert.deepEqual(errors, [])
  } catch (error) {
    console.error(error.message)
    await page.screenshot({ path: new URL(`failure-${width}.png`, shots).pathname.replace(/^\/(\w:)/, '$1'), fullPage: true })
    throw error
  } finally { await page.close() }
})
