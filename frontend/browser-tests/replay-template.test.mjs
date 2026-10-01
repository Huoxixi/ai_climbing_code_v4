import { startFixtureServer } from './fixtures/server.mjs'
import { fileURLToPath } from 'node:url'
import test, { after } from 'node:test'
import assert from 'node:assert/strict'
import { createRequire } from 'node:module'
import { mkdir } from 'node:fs/promises'
const require = createRequire(import.meta.url)
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || '@playwright/test')
const base = await startFixtureServer(4193, process.env.TEMPLATE_TEST_URL)
const shots = new URL('../test-results/template/', import.meta.url)
await mkdir(shots, { recursive: true })
const policy = { version: 'fixture-v2', enabled: true, configured: true, advice_available: true, budget: { amount: .2, estimate_min: 0, estimate_max: .2 }, provider: '构造测试服务', data_types: ['抽样画面'], full_video_sent: false }
const empty = () => ({ status: 'none', stale: false, media_ready: false })
const ready = () => ({ id: 'template-version-a', media_version: 'movie-a', status: 'succeeded', media_ready: true, stale: false, finished_at: 'fixture-time', plan: { duration_seconds: 68, chapters: [{ kind: 'actions', title: '连续动作解析', duration_seconds: 40 }, { kind: 'metrics', title: '基础数据', duration_seconds: 12 }, { kind: 'advice', title: '重点动作', duration_seconds: 16 }], omitted_metrics: [{ metric: 'longest_hold', reason: '遮挡使持续时间无法确认。' }] } })
const job = (id = 'template-a', status = 'available') => ({ id, status: 'succeeded', video: { duration_seconds: 30 }, result: {}, media: { source_video: { status } } })
async function setup(page, options = {}) {
  const data = { state: empty(), policy: { ...policy, ...options.policy }, mutations: [], reads: [], errors: [], ...options }
  page.on('pageerror', error => data.errors.push(error.message))
  await page.route('**/api/climb-replay/**', async route => {
    const request = route.request(), path = new URL(request.url()).pathname
    data.reads.push(path)
    if (path.endsWith('/coaching-policy')) return route.fulfill({ json: data.policy })
    if (path.endsWith('/coaching/preflight')) return route.fulfill({ json: { ...data.policy, ready: true } })
    if (path.endsWith('/coaching/consent/withdraw')) {
      data.state = { ...data.state, stale: true, stale_reason: '云端分析授权已撤回。', media_ready: false, media_version: null }
      data.report = { ...data.report, stale: true, stale_reason: '云端分析授权已撤回。' }
      return route.fulfill({ json: data.report })
    }
    if (path.endsWith('/coaching')) return route.fulfill({ json: data.report || { status: 'none', feedback: [] } })
    if (path.endsWith('/template-video/media')) return route.fulfill({ status: 200, contentType: 'video/webm', body: '' })
    if (path.includes('/template-video')) {
      if (data.missing) return route.fulfill({ status: 404, json: { detail: 'Not Found' } })
      if (request.method() === 'POST') {
        data.mutations.push({ path, body: request.postData() ? request.postDataJSON() : null })
        data.state = path.endsWith('/cancel') ? { ...data.state, status: 'cancelled', progress: 30 } : { id: 'template-version-a', status: 'waiting_report', progress: 12, media_ready: false }
      }
      const response = structuredClone(data.state)
      if (data.delay && path.includes('/template-a/') && request.method() === 'GET') await data.delay
      if (data.postDelay && path.includes('/template-a/') && request.method() === 'POST') await data.postDelay
      return route.fulfill({ json: response })
    }
    return route.fulfill({ json: { status: 'none', feedback: [] } })
  })
  await page.goto(`${base}/e2e/template-harness.html`)
  await page.evaluate(() => document.fonts.ready)
  return data
}
async function authorize(page, observationOnly = false) {
  await page.getByLabel('本次是室内抱石录像').check()
  if (observationOnly) await page.getByLabel('我选择仅生成画面观察，知道本次不会给出技术建议').check()
  await page.getByLabel('我同意将上述画面和必要信息用于本次云端分析').check()
  await page.getByLabel('我已了解费用范围、内部预算限制，以及失败或重试可能产生费用').check()
}
async function assertLayout(page) {
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false)
  const small = await page.locator('.template-panel').evaluate(panel => [...panel.querySelectorAll('button,a,summary')].filter(el => el.checkVisibility()).map(el => ({ text: el.textContent.trim(), width: el.getBoundingClientRect().width, height: el.getBoundingClientRect().height })).filter(el => el.width < 43.9 || el.height < 43.9))
  assert.deepEqual(small, [])
}
for (const width of [1280, 390]) {
  test(`模板 ${width}px：授权、进度取消、独立播放下载与过期隐藏`, { timeout: 45000 }, async () => {
    const browser = await chromium.launch({ headless: true }), page = await browser.newPage({ viewport: { width, height: 900 } })
    try {
      const data = await setup(page)
      await page.getByRole('button', { name: '按模板生成复盘视频', exact: true }).click()
      const submit = page.getByRole('button', { name: '同意并制作模板成片', exact: true })
      assert.equal(await submit.isDisabled(), true)
      assert.equal(data.mutations.length, 0)
      await authorize(page)
      await page.getByLabel('我已了解费用范围、内部预算限制，以及失败或重试可能产生费用').uncheck()
      assert.equal(await submit.isDisabled(), true)
      await page.getByLabel('我已了解费用范围、内部预算限制，以及失败或重试可能产生费用').check()
      await assertLayout(page)
      await page.screenshot({ path: fileURLToPath(new URL(`${width}-consent.png`, shots)), fullPage: true })
      await submit.click()
      await page.getByText('正在等待本次画面分析', { exact: true }).waitFor()
      assert.equal(data.mutations.length, 1)
      assert.equal(data.mutations[0].path.endsWith('/template-video'), true)
      assert.deepEqual(data.mutations[0].body, { consent_version: policy.version, consent_granted: true, indoor_bouldering_confirmed: true, budget_accepted: true, observation_only_accepted: false, personal: {}, context: {} })
      await page.getByRole('button', { name: '停止制作成片', exact: true }).click()
      await page.getByText('已停止制作成片，基础复盘仍保留。分析费用请在本次报告中查看。').waitFor()
      assert.equal(data.mutations[1].path.endsWith('/template-video/cancel'), true)

      data.state = ready()
      await page.evaluate(value => window.templateHarness.setJob(value), job())
      const video = page.getByLabel('Agent 模板复盘成片')
      await video.waitFor()
      assert.match(await video.getAttribute('src'), /template-a\/template-video\/media\?version=movie-a$/)
      assert.match(await page.getByRole('link', { name: '下载模板成片' }).getAttribute('href'), /template-video\/media\?download=true&version=movie-a$/)
      await page.getByText('查看本次成片章节', { exact: true }).click()
      await page.getByText('最长已确认停留：遮挡使持续时间无法确认。', { exact: true }).waitFor()
      await assertLayout(page)
      await page.locator('.template-panel').screenshot({ path: fileURLToPath(new URL(`${width}-result.png`, shots)) })

      data.state = { ...ready(), id: 'failed-attempt-b', status: 'failed', finished_at: 'a-later-time', error: '构造失败原因', media_plan: ready().plan, plan: { duration_seconds: 123, chapters: [{ title: '尚未完成的新分镜', duration_seconds: 123 }] } }
      await page.evaluate(value => window.templateHarness.setJob(value), job())
      await page.getByText('下方保留的是此前成功生成的成片。').waitFor()
      assert.equal(await video.count(), 1)
      assert.match(await video.getAttribute('src'), /version=movie-a$/)
      await page.getByText('约 68 秒', { exact: true }).waitFor()
      assert.equal(await page.getByText('尚未完成的新分镜', { exact: true }).count(), 0)
      data.state = { ...ready(), id: 'new-attempt-c', media_version: 'movie-c' }
      await page.evaluate(value => window.templateHarness.setJob(value), job())
      await page.waitForFunction(() => document.querySelector('.template-result video')?.getAttribute('src')?.endsWith('version=movie-c'))
      data.state = { ...ready(), stale: true, stale_reason: '岩点已复核。' }
      await page.evaluate(value => window.templateHarness.setJob(value), job())
      await page.getByText(/旧成片已停止展示/).waitFor()
      assert.equal(await video.count(), 0)
      assert.deepEqual(data.errors, [])
    } finally { await browser.close() }
  })
}
test('观察模式只承诺观察成片，缺原片/旧接口均不发起生成', { timeout: 30000 }, async () => {
  const browser = await chromium.launch({ headless: true }), page = await browser.newPage()
  try {
    const data = await setup(page, { policy: { ...policy, advice_available: false } })
    await page.getByRole('button', { name: '按模板生成复盘视频', exact: true }).click()
    await page.getByText('当前仅能提供画面观察，不生成动作纠正或练习建议。').waitFor()
    const submit = page.getByRole('button', { name: '同意并制作观察成片' })
    await authorize(page)
    assert.equal(await submit.isDisabled(), true)
    await page.getByLabel('我选择仅生成画面观察，知道本次不会给出技术建议').check()
    assert.equal(await submit.isEnabled(), true)
    await page.evaluate(value => window.templateHarness.setJob(value), job('template-b', 'deleted'))
    await page.getByText(/原视频不可用，暂时不能制作模板成片/).waitFor()
    assert.equal(await page.getByRole('button', { name: '按模板生成复盘视频', exact: true }).isDisabled(), true)
    assert.equal(data.reads.some(path => path.includes('template-b/template-video')), false)
    data.missing = true
    await page.evaluate(value => window.templateHarness.setJob(value), job('template-c'))
    await page.getByRole('alert').filter({ hasText: '模板成片服务或本次记录暂不可用' }).waitFor()
    assert.equal(await page.getByRole('button', { name: '按模板生成复盘视频', exact: true }).isDisabled(), true)
    data.missing = false
    await page.getByRole('button', { name: '重新读取成片状态', exact: true }).click()
    await page.waitForFunction(() => !document.querySelector('.template-primary')?.disabled)
    assert.equal(data.mutations.length, 0)
  } finally { await browser.close() }
})
test('切换视频会立即隐藏上次成片，延迟返回不能串入新视频', { timeout: 30000 }, async () => {
  const browser = await chromium.launch({ headless: true }), page = await browser.newPage()
  let release
  try {
    const data = await setup(page, { state: ready() })
    await page.getByLabel('Agent 模板复盘成片').waitFor()
    data.delay = new Promise(resolve => { release = resolve })
    await page.evaluate(value => window.templateHarness.setJob(value), job())
    await page.waitForFunction(() => !document.querySelector('.template-result video'))
    data.state = empty()
    await page.evaluate(value => window.templateHarness.setJob(value), job('template-b'))
    await page.waitForFunction(() => !document.querySelector('.template-primary')?.disabled)
    release()
    await page.waitForTimeout(100)
    assert.equal(await page.getByLabel('Agent 模板复盘成片').count(), 0)
    assert.equal(await page.getByRole('link', { name: '下载模板成片' }).count(), 0)
    assert.equal(data.mutations.length, 0)
  } finally { release?.(); await browser.close() }
})

test('生成请求迟到时不把旧任务进度和授权带入新视频', { timeout: 30000 }, async () => {
  const browser = await chromium.launch({ headless: true }), page = await browser.newPage()
  let release
  try {
    const data = await setup(page)
    await page.getByRole('button', { name: '按模板生成复盘视频', exact: true }).click()
    await authorize(page)
    data.postDelay = new Promise(resolve => { release = resolve })
    await page.getByRole('button', { name: '同意并制作模板成片', exact: true }).click()
    await page.waitForFunction(() => document.querySelector('.coaching-form fieldset')?.disabled)
    assert.equal(data.mutations.length, 1)
    data.state = empty()
    await page.evaluate(value => window.templateHarness.setJob(value), job('template-b'))
    await page.waitForFunction(() => !document.querySelector('.template-primary')?.disabled)
    release()
    await page.waitForTimeout(100)
    assert.equal(await page.getByText('正在等待本次画面分析', { exact: true }).count(), 0)
    assert.equal(await page.getByLabel('Agent 模板复盘成片').count(), 0)
    await page.getByRole('button', { name: '按模板生成复盘视频', exact: true }).click()
    assert.equal(await page.getByLabel('我同意将上述画面和必要信息用于本次云端分析').isChecked(), false)
    assert.equal(await page.getByLabel('我已了解费用范围、内部预算限制，以及失败或重试可能产生费用').isChecked(), false)
    assert.equal(await page.getByLabel('本次是室内抱石录像').isChecked(), false)
    assert.deepEqual(data.errors, [])
  } finally { release?.(); await browser.close() }
})

test('撤回本次报告授权立即重新核对并隐藏已经打开的模板成片', { timeout: 30000 }, async () => {
  const browser = await chromium.launch({ headless: true }), page = await browser.newPage()
  try {
    await setup(page, { state: ready(), report: { id: 'report-a', status: 'succeeded', feedback: [] } })
    await page.getByLabel('Agent 模板复盘成片').waitFor()
    await page.getByText('本次报告的云端授权', { exact: true }).click()
    await page.getByRole('button', { name: '撤回本次报告授权', exact: true }).click()
    await page.locator('.template-panel').getByText(/旧成片已停止展示/).waitFor()
    assert.equal(await page.getByLabel('Agent 模板复盘成片').count(), 0)
    assert.equal(await page.getByRole('link', { name: '下载模板成片' }).count(), 0)
  } finally { await browser.close() }
})
