import { startFixtureServer } from './fixtures/server.mjs'
import test, { after } from 'node:test'
import assert from 'node:assert/strict'
import { createRequire } from 'node:module'
import { mkdir } from 'node:fs/promises'
const require = createRequire(import.meta.url)
let playwright
try { playwright = require(process.env.PLAYWRIGHT_MODULE || '@playwright/test') }
catch (failure) {
  if (process.env.PLAYWRIGHT_MODULE) throw failure
  playwright = require('playwright')
}
const { chromium } = playwright
const base = await startFixtureServer(4181, process.env.COACHING_TEST_URL)
const shots = new URL('../test-results/coaching/', import.meta.url)
await mkdir(shots, { recursive: true })

const policy = { version: 'fixture-v2', enabled: true, configured: true, advice_available: true, approved_claim_count: 1, budget: { amount: .2, estimate_min: 0, estimate_max: .2, max_requests: 3 }, provider: '测试视觉服务', model: 'fixture-model', data_types: ['可对应时间的抽样画面', '必要信息'], full_video_sent: false, purpose: '构造案例验收', knowledge_notice: '知识审核状态保留。' }
const observation = (id, start = 0) => ({ id, title: `构造观察 ${id}`, start_seconds: start, end_seconds: start + 2, observation: '<img src=x onerror=alert(1)> 只是文本，不是实际用户数据。', possible_explanation: '用于验收的有条件解释。', personal_factors: ['height_cm'], evidence: [{ frame_id: `${id}-frame`, time_seconds: start }], knowledge_refs: [{ unit_id: 'fixture-unit', title: '构造知识来源', version: 1, source_urls: ['javascript:alert(1)', 'https://example.org/fixture'] }] })
const report = () => ({ result_status: 'try', overview: '构造案例报告，不代表真实攀岩判断。', observations: ['a', 'b', 'c', 'd'].map((id, index) => observation(id, index * 3)), improvements: ['e', 'f', 'g', 'h'].map((id, index) => ({ ...observation(id), id: `improvement-${id}`, observation_id: ['a', 'b', 'c', 'd'][index], adjustment: '构造调整方向', conditions: ['画面可以核实时'], verification: '构造验证方法', independent_review: { status: 'verified' } })), risk_reminders: [{ ...observation('risk'), user_report: '构造用户自述', knowledge_support: '构造资料摘要，仅用于验证来源分区。', conditions: ['构造风险适用条件'], precaution: '构造风险提示' }], next_attempt: { kind: 'adjustment', text: '构造的下次尝试重点', verification: '核对构造现象' }, coverage: { frames_reviewed: 8 }, knowledge_status: { eligible_advice_units: 1, total_units: 10 }, limitations: ['构造案例的限制'], provenance: { provider: '测试视觉服务', model: 'fixture-model' } })
const empty = () => ({ id: null, status: 'none', stale: false, report: null, feedback: [] })

test('接口缺失与记录丢失分别说明恢复方式，重新读取不会生成云端任务', { timeout: 30000 }, async () => {
  const browser = await chromium.launch({ headless: true })
  const page = await browser.newPage()
  let available = false, reportMissing = false, reportReads = 0, mutations = 0
  try {
    await page.route('**/api/climb-replay/**', async route => {
      const path = new URL(route.request().url()).pathname
      if (route.request().method() !== 'GET') mutations += 1
      if (path.endsWith('/coaching-policy')) return route.fulfill(available ? { json: policy } : { status: 404, json: { detail: 'Not Found' } })
      reportReads += 1
      return route.fulfill(reportMissing ? { status: 404, json: { detail: 'Not Found' } } : { json: empty() })
    })
    await page.goto(`${base}/e2e/coaching-harness.html`)
    await page.getByRole('alert').filter({ hasText: '请更新或重启本地服务后重新读取' }).waitFor()
    assert.equal(await page.getByRole('button', { name: '生成个性化复盘', exact: true }).isDisabled(), true)
    assert.equal(reportReads, 0, 'missing feature endpoint must not be mistaken for an empty report')
    assert.equal(await page.getByText('Not Found', { exact: true }).count(), 0)

    available = true
    await page.getByRole('button', { name: '重新读取', exact: true }).click()
    await page.waitForFunction(() => !document.querySelector('.coaching-primary')?.disabled)
    assert.equal(reportReads, 1)
    assert.equal(await page.getByRole('alert').count(), 0)

    reportMissing = true
    await page.evaluate(() => window.coachingHarness.setJob({ id: 'fixture-missing', status: 'succeeded', result: {} }))
    await page.getByRole('alert').filter({ hasText: '请刷新复盘列表后重新选择' }).waitFor()
    assert.equal(await page.getByRole('button', { name: '生成个性化复盘', exact: true }).isDisabled(), true)
    assert.equal(await page.locator('.coaching-report').count(), 0)
    assert.equal(mutations, 0, 'reading/retrying availability never creates a cloud analysis')
  } finally { await browser.close() }
})

async function assertTouchTargets(page) {
  const undersized = await page.locator('.coaching-panel').evaluate(panel => [...panel.querySelectorAll('button,summary,a,input:not([type="checkbox"]),textarea,select,.coaching-consent label')]
    .filter(element => element.checkVisibility())
    .map(element => ({ target: element.textContent.trim().slice(0, 40) || element.getAttribute('placeholder') || element.tagName, width: element.getBoundingClientRect().width, height: element.getBoundingClientRect().height }))
    .filter(({ width, height }) => width < 43.9 || height < 43.9))
  assert.deepEqual(undersized, [], 'every visible touch target, including checkbox label, must be at least 44×44')
}

for (const [width, height] of [[1280, 900], [390, 844]]) {
  test(`个性化复盘 ${width}px：授权、可跳过输入、片段、反馈、过期与切换`, { timeout: 60000 }, async () => {
    const browser = await chromium.launch({ headless: true })
    const page = await browser.newPage({ viewport: { width, height } })
    const errors = []
    const requests = []
    let state = empty()
    let nextPolicy = { ...policy }
    page.on('pageerror', error => errors.push(error.message))
    try {
      await page.route('**/api/climb-replay/**', async route => {
        const request = route.request(), url = new URL(request.url())
        if (url.pathname.endsWith('coaching-policy')) return route.fulfill({ json: nextPolicy })
        if (url.pathname.endsWith('/preflight')) return route.fulfill({ json: { ...nextPolicy, ready: true } })
        if (request.method() === 'POST') {
          const body = request.postDataJSON()
          requests.push({ path: url.pathname, body })
          if (url.pathname.endsWith('/feedback')) state.feedback.push(body)
          else if (url.pathname.endsWith('/consent/withdraw')) state = { ...state, stale: true, stale_reason: '云端分析授权已撤回。' }
          else state = { id: 'fixture-report', status: 'succeeded', stale: false, report: report(), personal: { height_cm: 170 }, feedback: [] }
        }
        return route.fulfill({ json: state })
      })
      await page.goto(`${base}/e2e/coaching-harness.html`)
      await page.getByRole('button', { name: '生成个性化复盘', exact: true }).click()
      const submit = page.getByRole('button', { name: '同意并生成报告' })
      assert.equal(await submit.isDisabled(), true)
      await page.getByLabel('本次是室内抱石录像').check()
      assert.equal(await submit.isDisabled(), true)
      await page.getByLabel('我同意将上述画面和必要信息用于本次云端分析').check()
      assert.equal(await submit.isDisabled(), true)
      await page.getByLabel('我已了解费用范围、内部预算限制，以及失败或重试可能产生费用').check()
      await page.locator('.coaching-input-details summary').click()
      await assertTouchTargets(page)
      await page.locator('.coaching-input-details summary').click()
      await page.screenshot({ path: new URL(`${width}-form.png`, shots).pathname.replace(/^\/(\w:)/, '$1'), fullPage: true })
      await page.getByLabel('关注片段开始（秒）').fill('0')
      await submit.click()
      await page.getByText('关注片段需要同时填写开始与结束时间，也可以全部留空。').waitFor()
      assert.equal(requests.length, 0)
      await page.getByLabel('关注片段开始（秒）').fill('')
      await submit.click()
      await page.getByText('构造案例报告，不代表真实攀岩判断。').waitFor()
      assert.deepEqual(requests[0].body.personal, {})
      assert.deepEqual(requests[0].body.context, {})
      assert.equal(requests[0].body.consent_granted, true)
      assert.equal(Object.hasOwn(requests[0].body, 'adult_confirmed'), false)
      assert.equal(requests[0].body.budget_accepted, true)
      assert.equal(requests[0].body.indoor_bouldering_confirmed, true)
      assert.equal(await page.locator('[aria-label="改进重点"] article').count(), 1)
      assert.equal(await page.locator('[aria-label="对应画面观察"] article').count(), 0)
      assert.equal(await page.locator('[aria-label="改进重点"] article, [aria-label="对应画面观察"] article').count(), 1)
      assert.equal(await page.locator('[aria-label="其他画面观察"] article').count(), 3)
      assert.equal(await page.locator('[aria-label="其他画面观察"]').getAttribute('open'), null)
      assert.equal(await page.locator('[aria-label="风险提醒"] article').count(), 0)
      assert.equal(await page.locator('.coaching-item img').count(), 0)
      const firstItem = page.locator('[aria-label="改进重点"] article').first()
      await firstItem.getByRole('button', { name: '回看 0:00.0–0:02.0' }).click()
      assert.deepEqual(JSON.parse(await page.locator('#last-seek').textContent()), { start_seconds: 0, end_seconds: 2 })
      await firstItem.locator('summary').click()
      assert.equal(await firstItem.getByText('使用的个人信息：身高 170厘米').count(), 1)
      assert.equal(await firstItem.locator('a').count(), 1)
      assert.equal(await firstItem.locator('a').getAttribute('href'), 'https://example.org/fixture')
      await assertTouchTargets(page)
      await firstItem.getByLabel('具体原因（选填）').selectOption('body_part')
      await firstItem.getByRole('button', { name: '看错了', exact: true }).click()
      await page.getByText(/反馈已保存，用于人工复核/).waitFor()
      assert.equal(requests[1].body.report_id, 'fixture-report')
      assert.equal(requests[1].body.item_id, 'improvement-e')
      assert.equal(requests[1].body.reason, 'body_part')
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1), false)
      await page.screenshot({ path: new URL(`${width}-report.png`, shots).pathname.replace(/^\/(\w:)/, '$1'), fullPage: true })

      state = { ...state, report: { ...state.report, improvements: state.report.improvements.slice(0, 1) } }
      await page.evaluate(() => window.coachingHarness.setJob({ id: 'fixture-a', status: 'succeeded', result: { updated: 1 } }))
      await page.locator('[aria-label="其他画面观察"]').waitFor()
      assert.equal(await page.locator('[aria-label="改进重点"] article').count(), 1)
      assert.equal(await page.locator('[aria-label="对应画面观察"] article').count(), 0)
      assert.equal(await page.locator('[aria-label="其他画面观察"] article').count(), 3)
      assert.equal(await page.locator('[aria-label="对应画面观察"] article, [aria-label="其他画面观察"] article').getByRole('heading', { name: '构造观察 a', exact: true }).count(), 0, 'an observation already explained by an improvement must not be repeated')

      state = { ...state, stale: true, stale_reason: '动作修正发生变化。' }
      await page.evaluate(() => window.coachingHarness.setJob({ id: 'fixture-a', status: 'succeeded', result: { hold_review_version: 2 } }))
      await page.getByText(/动作修正发生变化/).waitFor()
      assert.equal(await page.locator('.coaching-report').count(), 0)
      await page.getByRole('button', { name: '重新生成个性化复盘' }).click()
      assert.equal(await page.getByLabel('我同意将上述画面和必要信息用于本次云端分析').isChecked(), false)
      state = empty()
      nextPolicy = { ...policy, configured: false }
      await page.evaluate(() => window.coachingHarness.setJob({ id: 'fixture-b', status: 'succeeded', result: {} }))
      await page.getByText('服务尚未配置或开放，请联系管理员完成视觉服务配置后重试。').waitFor()
      assert.equal(await page.getByRole('button', { name: '生成个性化复盘', exact: true }).isDisabled(), true)
      assert.equal(await page.locator('.coaching-form').count(), 0)
      assert.deepEqual(errors, [])
    } finally { await browser.close() }
  })
}

test('报告轮询、知识门禁、失败、撤回与视频缺失', { timeout: 60000 }, async () => {
  const browser = await chromium.launch({ headless: true })
  const page = await browser.newPage()
  let state = { id: 'fixture-running', status: 'running', stale: false, feedback: [] }
  let reads = 0
  try {
    await page.route('**/api/climb-replay/**', async route => {
      const path = new URL(route.request().url()).pathname
      if (path.endsWith('coaching-policy')) return route.fulfill({ json: policy })
      if (path.endsWith('/consent/withdraw')) state = { ...state, stale: true, stale_reason: '这份报告的云端分析授权已撤回。' }
      if (route.request().method() === 'GET') reads += 1
      return route.fulfill({ json: state })
    })
    await page.goto(`${base}/e2e/coaching-harness.html`)
    await page.getByText(/正在核对画面和知识依据/).waitFor()
    state = { ...state, status: 'failed', error: '构造云端超时，请重试。', cost: { status: 'partial', known_amount: .025, usage_complete: false } }
    await page.getByText('构造云端超时，请重试。').waitFor()
    await page.getByText('已知个性化分析费用估算：¥0.0250（已知部分）').waitFor()
    await page.locator('.coaching-cost summary').click()
    await page.getByText(/费用可能不完整，未收到完整用量的请求仍可能计费/).waitFor()
    const completedReads = reads
    await page.waitForTimeout(3000)
    assert.equal(reads, completedReads, 'terminal reports do not poll')
    state = { ...state, status: 'succeeded', error: null, report: { ...report(), result_status: 'insufficient', improvements: [], risk_reminders: [], knowledge_status: { eligible_advice_units: 0, total_units: 10 } } }
    await page.evaluate(() => window.coachingHarness.setJob({ id: 'fixture-a', status: 'succeeded', result: { updated: true } }))
    await page.getByText(/没有通过审核与验收的适用知识/).waitFor()
    assert.equal(await page.locator('[aria-label="改进重点"] article').count(), 0)
    assert.equal(await page.locator('[aria-label="对应画面观察"] article').count(), 0)
    assert.equal(await page.locator('[aria-label="画面观察（尚未确认重点）"] article').count(), 4)
    assert.equal(await page.locator('[aria-label="画面观察（尚未确认重点）"]').getAttribute("open"), null)
    assert.equal(await page.getByRole("heading", { name: "资料不足" }).isVisible(), true)
    await page.getByText('本次报告的云端授权', { exact: true }).click()
    await page.getByRole('button', { name: '撤回本次报告授权' }).click()
    await page.getByText(/这份报告的云端分析授权已撤回/).waitFor()
    assert.equal(await page.locator('.coaching-report').count(), 0)
    await page.evaluate(() => window.coachingHarness.setMedia(false))
    await page.getByText(/本次可对应时间的复盘视频与分析副本均不可用/).waitFor()
    assert.equal(await page.getByRole('button', { name: '重新生成个性化复盘' }).isDisabled(), true)
  } finally { await browser.close() }
})

test('切换复盘丢弃迟到结果，卸载停止轮询且不取消服务器任务', { timeout: 30000 }, async () => {
  const browser = await chromium.launch({ headless: true })
  const page = await browser.newPage()
  let sawFirstRequest
  const firstRequest = new Promise(resolve => { sawFirstRequest = resolve })
  let reads = 0, mutations = 0
  try {
    await page.route('**/api/climb-replay/**', async route => {
      const path = new URL(route.request().url()).pathname
      if (path.endsWith('coaching-policy')) return route.fulfill({ json: policy })
      if (route.request().method() === 'POST') mutations += 1
      reads += 1
      if (path.includes('fixture-a')) {
        sawFirstRequest()
        await new Promise(resolve => setTimeout(resolve, 600))
        return route.fulfill({ json: { id: 'late-report', status: 'succeeded', report: report(), feedback: [] } }).catch(() => {})
      }
      return route.fulfill({ json: { id: 'second-report', status: 'running', feedback: [] } })
    })
    await page.goto(`${base}/e2e/coaching-harness.html`)
    await firstRequest
    await page.evaluate(() => window.coachingHarness.setJob({ id: 'fixture-b', status: 'succeeded', result: {} }))
    await page.getByText(/正在核对画面和知识依据/).waitFor()
    await page.waitForTimeout(800)
    assert.equal(await page.locator('.coaching-report').count(), 0)
    await page.evaluate(() => window.coachingHarness.hide())
    const finalReads = reads
    await page.waitForTimeout(2800)
    assert.equal(reads, finalReads)
    assert.equal(mutations, 0)
  } finally { await browser.close() }
})

test('重复提交只发一个请求，取消失败仍跟踪任务', { timeout: 30000 }, async () => {
  const browser = await chromium.launch({ headless: true })
  const page = await browser.newPage()
  let state = empty(), posts = 0, reads = 0, cancels = 0
  try {
    await page.route('**/api/climb-replay/**', async route => {
      const path = new URL(route.request().url()).pathname
      if (path.endsWith('coaching-policy')) return route.fulfill({ json: policy })
      if (path.endsWith('/preflight')) return route.fulfill({ json: { ...policy, ready: true } })
      if (path.endsWith('/cancel')) {
        cancels += 1
        if (cancels === 1) return route.fulfill({ status: 503, json: { detail: '构造停止失败' } })
        state = { ...state, status: 'cancelled' }
      } else if (route.request().method() === 'POST') {
        posts += 1
        await new Promise(resolve => setTimeout(resolve, 100))
        state = { id: 'running-report', status: 'running', stale: false, feedback: [] }
      } else reads += 1
      return route.fulfill({ json: state })
    })
    await page.goto(`${base}/e2e/coaching-harness.html`)
    await page.getByRole('button', { name: '生成个性化复盘', exact: true }).click()
    await page.getByLabel('本次是室内抱石录像').check()
    await page.getByLabel('我同意将上述画面和必要信息用于本次云端分析').check()
    await page.getByLabel('我已了解费用范围、内部预算限制，以及失败或重试可能产生费用').check()
    await page.locator('form').evaluate(form => { form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true })); form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true })) })
    await page.getByText(/正在核对画面和知识依据/).waitFor()
    assert.equal(posts, 1)
    await page.getByRole('button', { name: '停止生成', exact: true }).click()
    await page.getByText('构造停止失败').waitFor()
    const before = reads
    await page.waitForTimeout(2800)
    assert.ok(reads > before, 'cancel failure must resume polling')
    await page.getByRole('button', { name: '停止生成', exact: true }).click()
    await page.getByText(/已停止后续调用/).waitFor()
  } finally { await browser.close() }
})

test('无获准知识必须明确选择观察模式；预检不通过不会发起付费请求', { timeout: 30000 }, async () => {
  const browser = await chromium.launch({ headless: true })
  const page = await browser.newPage()
  let blocked = true, body = null
  const observationPolicy = { ...policy, advice_available: false, approved_claim_count: 0, observation_only_notice: '本次仅能整理画面观察，不能生成技术建议。' }
  try {
    await page.route('**/api/climb-replay/**', async route => {
      const path = new URL(route.request().url()).pathname
      if (path.endsWith('/coaching-policy')) return route.fulfill({ json: observationPolicy })
      if (path.endsWith('/preflight')) return route.fulfill(blocked ? { status: 409, json: { detail: '视频关键画面不可读，请重新选择可用录像。' } } : { json: { ...observationPolicy, ready: true } })
      if (route.request().method() === 'POST') { body = route.request().postDataJSON(); return route.fulfill({ json: { id: 'observation-only', status: 'queued', feedback: [] } }) }
      return route.fulfill({ json: empty() })
    })
    await page.goto(`${base}/e2e/coaching-harness.html`)
    await page.getByRole('button', { name: '生成个性化复盘', exact: true }).click()
    await page.getByText('视频关键画面不可读，请重新选择可用录像。').waitFor()
    assert.equal(await page.locator('form').count(), 0)
    assert.equal(body, null)
    blocked = false
    await page.getByRole('button', { name: '生成个性化复盘', exact: true }).click()
    const submit = page.getByRole('button', { name: '同意并生成画面观察' })
    await page.getByLabel('本次是室内抱石录像').check()
    await page.getByLabel('我同意将上述画面和必要信息用于本次云端分析').check()
    await page.getByLabel('我已了解费用范围、内部预算限制，以及失败或重试可能产生费用').check()
    assert.equal(await submit.isDisabled(), true)
    await page.getByLabel('我选择仅生成画面观察，知道本次不会给出技术建议').check()
    assert.equal(await submit.isDisabled(), false)
    await submit.click()
    await page.getByText(/报告正在排队/).waitFor()
    assert.equal(body.observation_only_accepted, true)
    assert.equal(body.budget_accepted, true)
    assert.equal(body.indoor_bouldering_confirmed, true)
    assert.equal(body.consent_version, 'fixture-v2')
  } finally { await browser.close() }
})

test('旧行动默认隐藏；复核片段显示具体缺失且历史费用另列', { timeout: 30000 }, async () => {
  const browser = await chromium.launch({ headless: true })
  const page = await browser.newPage()
  let state = { id: 'legacy', status: 'succeeded', legacy: true, report: report(), cost: { status: 'estimated', amount_min: .03, amount_max: .03 }, feedback: [] }
  try {
    await page.route('**/api/climb-replay/**', async route => route.fulfill({ json: new URL(route.request().url()).pathname.endsWith('coaching-policy') ? policy : state }))
    await page.goto(`${base}/e2e/coaching-harness.html`)
    await page.getByText(/这份旧报告尚未通过当前的画面复核/).waitFor()
    assert.equal(await page.locator('.coaching-report').count(), 0)
    assert.equal(await page.getByText('构造调整方向', { exact: true }).count(), 0)
    const review = observation('review', 6)
    state = { ...state, legacy: false, previous_attempt_costs: [{ id: 'previous', cost: { status: 'partial', known_amount: .012 } }], report: { ...report(), result_status: 'review', improvements: [], observations: [review], next_attempt: { kind: 'review', observation_id: 'review', reason: '脚部位置变化需要核对。', verification: '确认是否是为转身做准备。' }, no_advice_reasons: [{ code: 'visibility_unknown', message: '右脚鞋部被挡，不能判断接触过程。' }] } }
    await page.evaluate(() => window.coachingHarness.setJob({ id: 'fixture-a', status: 'succeeded', result: { updated: 'review' } }))
    await page.getByRole('heading', { name: '先核对片段' }).waitFor()
    await page.getByText('右脚鞋部被挡，不能判断接触过程。').waitFor()
    assert.equal(await page.locator('[aria-label="改进重点"] article').count(), 0)
    await page.locator('.coaching-cost summary').click()
    await page.getByText('此前尝试 1（另计）：¥0.0120（已知部分）').waitFor()
    assert.equal(await page.getByText(/高置信度|低置信度|置信度：/).count(), 0)
    state = { ...state, report: { ...state.report, observations: [review, observation('second', 12)], next_attempt: null } }
    await page.evaluate(() => window.coachingHarness.setJob({ id: 'fixture-a', status: 'succeeded', result: { updated: 'multiple' } }))
    await page.getByText('目前还不能确定哪一段更优先。下方观察可分别回看核对，不能据此认定为动作问题。').waitFor()
    assert.equal(await page.getByRole('heading', { name: '先核对片段', exact: true }).count(), 1)
    assert.equal(await page.getByRole('heading', { name: '资料不足', exact: true }).count(), 0)
  } finally { await browser.close() }
})

test('同一复盘更新依据后，迟到预检不会重新打开表单或恢复旧建议', { timeout: 30000 }, async () => {
  const browser = await chromium.launch({ headless: true })
  const page = await browser.newPage()
  let signalStarted
  const started = new Promise(resolve => { signalStarted = resolve })
  let changed = false, posts = 0
  try {
    await page.route('**/api/climb-replay/**', async route => {
      const path = new URL(route.request().url()).pathname
      if (path.endsWith('coaching-policy')) return route.fulfill({ json: policy })
      if (path.endsWith('/preflight')) {
        signalStarted()
        await new Promise(resolve => setTimeout(resolve, 500))
        return route.fulfill({ json: { ...policy, ready: true } }).catch(() => {})
      }
      if (route.request().method() === 'POST') posts += 1
      return route.fulfill({ json: { id: 'versioned', status: 'succeeded', stale: changed, stale_reason: changed ? '构造新媒体版本。' : null, report: report(), feedback: [] } })
    })
    await page.goto(`${base}/e2e/coaching-harness.html`)
    await page.getByRole('button', { name: '重新生成个性化复盘', exact: true }).click()
    await started
    changed = true
    await page.evaluate(() => window.coachingHarness.setJob({ id: 'fixture-a', status: 'succeeded', result: { updated: 'during-preflight' } }))
    await page.getByText(/构造新媒体版本/).waitFor()
    await page.waitForTimeout(600)
    assert.equal(await page.locator('.coaching-form').count(), 0)
    assert.equal(await page.locator('.coaching-report').count(), 0)
    assert.equal(posts, 0)
  } finally { await browser.close() }
})

test('迟到反馈不覆盖新报告的生成状态', { timeout: 30000 }, async () => {
  const browser = await chromium.launch({ headless: true })
  const page = await browser.newPage()
  const old = { id: 'old', status: 'succeeded', report: report(), feedback: [] }
  let state = old
  let releaseFeedback
  const feedbackResponse = new Promise(resolve => { releaseFeedback = resolve })
  try {
    await page.route('**/api/climb-replay/**', async route => {
      const path = new URL(route.request().url()).pathname
      if (path.endsWith('coaching-policy')) return route.fulfill({ json: policy })
      if (path.endsWith('/preflight')) return route.fulfill({ json: { ...policy, ready: true } })
      if (path.endsWith('/feedback')) { await feedbackResponse; return route.fulfill({ json: old }) }
      if (route.request().method() === 'POST') state = { id: 'new', status: 'running', feedback: [] }
      return route.fulfill({ json: state })
    })
    await page.goto(`${base}/e2e/coaching-harness.html`)
    await page.getByRole('button', { name: '重新生成个性化复盘', exact: true }).click()
    await page.getByLabel('本次是室内抱石录像').check()
    await page.getByLabel('我同意将上述画面和必要信息用于本次云端分析').check()
    await page.getByLabel('我已了解费用范围、内部预算限制，以及失败或重试可能产生费用').check()
    await page.locator('[aria-label="改进重点"] article').getByRole('button', { name: '有帮助', exact: true }).click()
    await page.getByRole('button', { name: '同意并生成报告', exact: true }).click()
    await page.getByText(/正在核对画面和知识依据/).waitFor()
    releaseFeedback()
    await page.waitForTimeout(150)
    assert.equal(await page.locator('.coaching-report').count(), 0)
    assert.equal(await page.getByText(/正在核对画面和知识依据/).count(), 1)
  } finally { releaseFeedback(); await browser.close() }
})

test('当前复盘页只在手动展开后读取旧报告，保留视频且不启动云任务', { timeout: 30000 }, async () => {
  const browser = await chromium.launch({ headless: true })
  const page = await browser.newPage()
  const errors = [], requests = [], mutations = []
  page.on('pageerror', error => errors.push(error.message))
  const job = { id: 'fixture-parent', status: 'succeeded', original_name: '构造已有录像.mp4', route_color: '黄色',
    created_at: '2026-09-25T00:00:00Z', video: { duration_seconds: 30, fps: 30, width: 320, height: 180 },
    media: { overlay_video: { status: 'available' }, source_video: { status: 'deleted' } },
    result: { holds: [], pose_samples: [], attempt: { topped_out: false, contacts: [], sequence: [], duration_seconds: 30 },
      video: { duration_seconds: 30, fps: 30, width: 320, height: 180 } } }
  try {
    await page.addInitScript(() => {
      const listen = HTMLMediaElement.prototype.addEventListener
      HTMLMediaElement.prototype.addEventListener = function(type, ...args) { if(type !== 'error') return listen.call(this,type,...args) }
    })
    await page.route('**/api/**', async route => {
      const path = new URL(route.request().url()).pathname
      requests.push(path)
      if(route.request().method() !== 'GET') mutations.push(path)
      if (path.endsWith('coaching-policy') || path.endsWith('consent-policy')) return route.fulfill({ json: policy })
      if (path.endsWith('/coaching')) return route.fulfill({ json: { status: 'succeeded', report: { summary: '构造旧报告保留', observations: [], improvements: [] } } })
      if (path.endsWith('/template-video')) return route.fulfill({ json: { status: 'none' } })
      if (path.endsWith('/actions')) return route.fulfill({ json: { task: {status:'idle'}, result: {groups:[],metrics:[],source_duration_seconds:30},media_ready:false } })
      if (path === '/api/climb-replay/jobs') return route.fulfill({ json: [job] })
      if (path.endsWith('/fixture-parent')) return route.fulfill({ json: job })
      if (path.includes('/media/')) return route.fulfill({ status: 200, contentType: 'video/mp4', body: '' })
      return route.fulfill({ json: path.endsWith('/test-videos') ? { items: [] } : [] })
    })
    await page.goto(`${base}/e2e/coaching-harness.html?parent`)
    await page.locator('.recent-row').filter({ hasText: '构造已有录像.mp4' }).click()
    await page.locator('.unified-replay').waitFor()
    assert.equal(requests.filter(path=>path.endsWith('/coaching')).length,0)
    await page.locator('.replay-more > summary').click()
    await page.getByRole('button',{name:'查看旧报告与旧视频',exact:true}).click()
    await page.getByText('构造旧报告保留',{exact:true}).waitFor()
    assert.match(await page.locator('.replay-cinema video').getAttribute('src'),/fixture-parent\/media\/overlay-video/)
    await page.locator('.replay-cinema video').evaluate(video=>video.dispatchEvent(new Event('loadedmetadata')))
    assert.equal(await page.locator('.replay-cinema video').evaluate(video=>video.playbackRate),.75)
    assert.deepEqual(mutations,[])
    assert.deepEqual(errors,[])
  } finally { await browser.close() }
})
