import assert from 'node:assert/strict'
import { fileURLToPath } from 'node:url'
import { createServer as createPortReservation } from 'node:net'
import test, { after, before } from 'node:test'
import { createServer } from 'vite'
import vue from '@vitejs/plugin-vue'
import { chromium } from '@playwright/test'
import { organized, syntheticMedia } from './fixtures/actions.mjs'

// Characterize existing page entry points with constructed records only. All API
// requests are intercepted; the random loopback server never uses a user backend.
let server, browser, base, media
before(async () => {
  const root = fileURLToPath(new URL('../', import.meta.url))
  const reservation = createPortReservation()
  await new Promise(resolve => reservation.listen(0, '127.0.0.1', resolve))
  const port = reservation.address().port
  await new Promise(resolve => reservation.close(resolve))
  server = await createServer({
    root, configFile: false, envDir: false, publicDir: false,
    plugins: [vue()],
    define: { 'import.meta.env.VITE_API_BASE_URL': JSON.stringify('') },
    cacheDir: `.tmp/replay-page-characterization-${process.pid}`,
    server: { host: '127.0.0.1', port, strictPort: true },
  })
  await server.listen()
  base = `http://127.0.0.1:${server.httpServer.address().port}`
  browser = await chromium.launch({ headless: true })
  media = await syntheticMedia(browser)
})
after(async () => { await browser?.close(); await server?.close() })

const records = ['a', 'b'].map(suffix => ({
  id: `characterization-${suffix}`, original_name: `constructed-${suffix}.webm`,
  status: 'succeeded', route_color: '黄色', created_at: '2026-10-01T00:00:00Z',
  route_id: 'constructed-route', route_version_id: 'constructed-version',
  reviewed_segments: [{ id: 'old-review', source: 'user_confirmed' }],
  media: { source_video: { status: 'available' }, overlay_video: { status: 'available' } },
  result: { video: organized.video, pose_samples: [], holds: [], attempt: { contacts: [] } },
}))

async function fixture(entry, width, { jobs = records, actionStateFor } = {}) {
  const page = await browser.newPage({ viewport: { width, height: 900 } })
  const writes = [], reads = [], errors = []
  page.on('pageerror', error => errors.push(error.message))
  await page.route('**/api/**', route => {
    const request = route.request(), pathname = new URL(request.url()).pathname
    if (request.method() !== 'GET') writes.push({ pathname, body: request.postData() })
    else reads.push(pathname)
    if (/\/(?:source-video|overlay-video|reviewed-overlay-video)$/.test(pathname) || pathname.endsWith('/actions/media')) {
      return route.fulfill({ body: media, contentType: 'video/webm' })
    }
    if (pathname.endsWith('/jobs')) return route.fulfill({ json: jobs })
    if (pathname.endsWith('/consent-policy')) return route.fulfill({ json: { version: 'characterization' } })
    if (pathname.endsWith('/test-videos')) return route.fulfill({ json: { items: [] } })
    if (pathname.endsWith('/actions')) {
      const id = pathname.split('/').at(-2)
      const state = {
        task: { status: 'succeeded' }, export: { status: 'idle' }, result_version: `saved-${id}`,
        result: { ...structuredClone(organized), groups: [] }, cloud_configured: false,
        background: { status: 'unavailable', message: '构造记录无无人背景' },
      }
      return route.fulfill({ json: actionStateFor ? actionStateFor(id, state) : state })
    }
    return route.fulfill({ json: {} })
  })
  const harness = entry === 'local' ? 'local-replay-harness' : 'coaching-harness'
  await page.goto(`${base}/e2e/${harness}.html?parent&replay=${jobs[0].id}`)
  await page.getByRole('button', { name: '导出', exact: true }).waitFor()
  await page.waitForFunction(() => document.querySelector('.unified-replay video')?.readyState >= 2)
  return { page, writes, reads, errors }
}

for (const entry of ['local', 'full']) {
  test(`characterization: ${entry} retained media priority and versions survive record switching`, async () => {
    const jobs = ['source', 'reviewed', 'overlay', 'organized'].map(kind => ({
      ...structuredClone(records[0]), id: `retained-${kind}`, original_name: `constructed-${kind}.webm`,
      media: {
        source_video: { status: kind === 'source' ? 'available' : 'deleted' },
        overlay_video: { status: 'available' },
        reviewed_overlay_video: { status: kind === 'overlay' ? 'deleted' : 'available' },
      },
    }))
    let organizedReads = 0
    const { page, writes, errors } = await fixture(entry, 1280, {
      jobs,
      actionStateFor: (id, state) => id === 'retained-organized'
        ? { ...state, media_ready: true, result_version: `organized-v${++organizedReads}` }
        : state,
    })
    try {
      for (const [index, kind] of ['source', 'reviewed', 'overlay', 'organized', 'source', 'organized'].entries()) {
        if (index > 0) {
          await page.getByRole('button', { name: /最近分析/ }).click()
          await page.getByRole('dialog', { name: '最近分析', exact: true })
            .getByRole('button', { name: new RegExp(`constructed-${kind}\\.webm`) }).click()
        }
        const expectedPath = kind === 'organized'
          ? '/api/climb-replay/jobs/retained-organized/actions/media'
          : `/api/climb-replay/jobs/retained-${kind}/media/${kind === 'source' ? 'source-video' : kind === 'reviewed' ? 'reviewed-overlay-video' : 'overlay-video'}`
        await page.waitForFunction(expected => {
          const src = document.querySelector('.unified-replay video')?.getAttribute('src')
          return src && new URL(src, location.href).pathname === expected
        }, expectedPath)
        const src = new URL(await page.locator('.unified-replay video').getAttribute('src'), base)
        if (kind === 'organized') {
          assert.equal(src.searchParams.get('version'), `organized-v${index === 3 ? 1 : 2}`)
          assert.equal(src.searchParams.get('exported'), 'false')
        }
        await page.getByRole('button', { name: '导出', exact: true }).click()
        const dialog = page.getByRole('dialog', { name: '导出复盘', exact: true })
        assert.equal(await dialog.getByLabel('导出范围', { exact: true }).inputValue(), 'full')
        assert.equal(await dialog.getByLabel('导出速度', { exact: true }).inputValue(), '0.75')
        assert.equal(await dialog.getByRole(entry === 'local' ? 'checkbox' : 'radio').count(), entry === 'local' ? 4 : 2)
        await dialog.getByLabel('导出速度', { exact: true }).selectOption('1')
        await dialog.getByRole('button', { name: '关闭面板', exact: true }).click()
      }
      assert.deepEqual(writes, [], 'retained media selection and export choices never regenerate or alter a saved record')
      assert.deepEqual(errors, [])
    } finally { await page.close() }
  })
}

for (const entry of ['local', 'full']) for (const width of [1280, 390]) {
  test(`characterization: ${entry} saved records stay read-only at ${width}px`, async () => {
    const { page, writes, reads, errors } = await fixture(entry, width)
    try {
      assert.ok(reads.includes('/api/climb-replay/jobs'))
      assert.ok(reads.some(path => path.endsWith(`/${records[0].id}/actions`)))
      assert.equal(await page.getByText('constructed-a.webm', { exact: true }).count(), 1)
      assert.equal(await page.getByRole('button', { name: '保存动作复核', exact: true }).count(), 0)

      await page.getByRole('button', { name: '导出', exact: true }).click()
      const exportDialog = page.getByRole('dialog', { name: '导出复盘', exact: true })
      await exportDialog.waitFor()
      assert.equal(await exportDialog.getByLabel('导出范围', { exact: true }).inputValue(), 'full')
      assert.equal(await exportDialog.getByLabel('导出速度', { exact: true }).inputValue(), '0.75')
      assert.equal(await exportDialog.getByRole(entry === 'local' ? 'checkbox' : 'radio').count(), entry === 'local' ? 4 : 2)
      await exportDialog.getByRole('button', { name: '关闭面板', exact: true }).click()

      if (width >= 900) {
        await page.getByRole('button', { name: /最近分析/ }).click()
        const history = page.getByRole('dialog', { name: '最近分析', exact: true })
        assert.equal(await history.getByRole('navigation', { name: '分析历史分页', exact: true }).innerText(), '上一页1 / 1下一页')
        await history.getByRole('button', { name: /constructed-b\.webm/ }).click()
        await page.getByText('constructed-b.webm', { exact: true }).waitFor()
        await page.getByRole('button', { name: /最近分析/ }).click()
        await page.getByRole('dialog', { name: '最近分析', exact: true }).getByRole('button', { name: /constructed-a\.webm/ }).click()
        await page.getByText('constructed-a.webm', { exact: true }).waitFor()
      }
      if (entry === 'local') {
        await page.getByRole('button', { name: '返回', exact: true }).click()
        await page.getByText('导入视频', { exact: true }).waitFor()
      }
      assert.deepEqual(writes, [], 'opening, exporting choices and switching records never writes or starts recognition')
      assert.deepEqual(errors, [])
    } finally { await page.close() }
  })
}
