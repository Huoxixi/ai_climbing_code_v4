import { startFixtureServer } from './fixtures/server.mjs'
import { fileURLToPath } from 'node:url'
import test, { after } from 'node:test'
import assert from 'node:assert/strict'
import { createRequire } from 'node:module'
const require = createRequire(import.meta.url)
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || '@playwright/test')
import { mkdir } from 'node:fs/promises'
import { summarySeconds } from '../src/services/replayPresentation.js'
import { organized, syntheticMedia } from './fixtures/actions.mjs'
const base = await startFixtureServer(4195)
const shots = new URL('../test-results/actions-page/', import.meta.url)
const captureScreenshots = !process.env.REPLAY_SKIP_SCREENSHOTS
await mkdir(shots, { recursive: true })
const browser = await chromium.launch({ headless: true })
const media = await syntheticMedia(browser)
after(() => browser.close())

async function setup(width) {
  const page = await browser.newPage({ viewport: { width, height: 900 } })
  const mutations = [], errors = []
  const state = { task: { status: 'succeeded' }, result: structuredClone(organized), result_version: 'real-source-local-result',
    media_ready: true, cloud_configured: false, export: { status: 'idle' }, revision_count: 0,
    vocabulary: {techniques:[{code:'CROSS',name:'交叉手'}]} }
  let original
  const firstEvent = state.result.groups[0].events[0]
  firstEvent.trajectory_details = {status:'observed',summary:'腕部相对肩部向上伸出，肘部逐步展开；接触尚未确认。',
    phases:[{start_seconds:firstEvent.start_seconds,end_seconds:firstEvent.end_seconds,code:'extend',text:'上举手臂，逐步展开肘部'}],
    evidence:firstEvent.evidence || [],limitations:[],reason_labels:['肩肘腕或髋膝踝有低置信／遮挡点','原片姿态采样有间隔，不能补画轨迹']}
  page.on('pageerror', e => errors.push(e.message))
  await page.route('**/api/climb-replay/**', async route => {
    const request = route.request(), url = new URL(request.url())
    if (url.pathname.endsWith('/media') || url.pathname.endsWith('/source-video') || url.pathname.endsWith('/overlay-video')) {
      const range = request.headers().range?.match(/bytes=(\d+)-(\d*)/)
      const start = range ? +range[1] : 0, end = range && range[2] ? Math.min(+range[2], media.length - 1) : media.length - 1
      return route.fulfill({ status: range ? 206 : 200, body: media.subarray(start, end + 1), contentType: 'video/webm',
        headers: { 'Accept-Ranges': 'bytes', 'Content-Length': String(end - start + 1), ...(range ? { 'Content-Range': `bytes ${start}-${end}/${media.length}` } : {}) } })
    }
    if (request.method() === 'POST') {
      mutations.push({ path: url.pathname, body: request.postDataJSON() })
      if (url.pathname.endsWith('/export')) state.export = { status: 'queued' }
      if (url.pathname.endsWith('/review')) {
        original = structuredClone(state.result)
        const body = request.postDataJSON()
        state.result = structuredClone(state.result)
        const group = state.result.groups.find(g=>g.id===body.group_id)
        const event = group.events[0]
        Object.assign(event,body,{id:body.event_id||'corrected-event',event_status:'human_confirmed',evidence_status:'human_confirmed',
          display_name:'右手原点重新抓握',facts:[],technique_tags:[{code:'CROSS',name:'交叉手',status:'human_confirmed'}],
          caption_parts:[{start_seconds:body.start_seconds,text:'调整手部位置'},{start_seconds:body.contact_seconds,text:'原点重新抓握 1 · 交叉手（人工确认）'}]})
        group.description = event.display_name
        state.revision_count = 1
        state.result_version = 'human-correction-version'
      }
      if (url.pathname.endsWith('/review/undo')) {
        state.result = original; state.revision_count = 0; state.result_version = 'undo-version'
      }
    }
    return route.fulfill({ json: state })
  })
  await page.goto(base + '/e2e/actions-harness.html')
  await page.waitForFunction(() => document.querySelector('video')?.readyState >= 2)
  return { page, mutations, errors, state }
}

for (const width of [1280,390]) test(`simple actions, optional correction and undo at ${width}px`, async () => {
  const {page,mutations,errors,state} = await setup(width)
  try {
    state.result.holds = [{id:'1'}]
    // Reload the mocked result to exercise the real component and service.
    await page.reload(); await page.waitForFunction(()=>document.querySelector('video')?.readyState>=2)
    const group = state.result.groups[0], event = group.events[0]
    await page.getByRole('navigation',{name:'动作时间轴'}).getByRole('button').first().click()
    await page.locator('video').evaluate((v,t)=>{v.pause();v.currentTime=t},(event.start_seconds+event.end_seconds)/2)
    await page.locator('.motion-name').waitFor()
    assert.equal(await page.getByLabel('骨架轨迹观察',{exact:true}).count(),0)
    assert.equal(await page.locator('.trajectory-observation,.movement-analysis,.trajectory-phases,.evidence-note').count(),0)
    assert.equal(await page.locator('.action-correction').evaluate(el=>el.open),false)
    assert.equal(await page.getByLabel('修正肢体',{exact:true}).isVisible(),false)
    const note = await page.getByLabel('当前动作解析',{exact:true}).innerText()
    assert.equal(/二维|墙面参考|相对肩|遮挡|另行核对/.test(note),false)
    await page.locator('.action-correction > summary').click()
    const save = page.getByRole('button',{name:'保存动作修正',exact:true})
    assert.equal(await save.isDisabled(),true)
    await page.getByLabel('修正肢体',{exact:true}).selectOption('right_hand')
    await page.getByLabel('修正动作',{exact:true}).selectOption('readjust')
    await page.getByLabel('原岩点',{exact:true}).selectOption('1')
    await page.getByLabel('目标岩点',{exact:true}).selectOption('1')
    const at = Math.round((event.start_seconds + event.end_seconds)/2*100)/100
    await page.getByLabel('接触或离点秒数',{exact:true}).fill(String(at))
    await page.locator('.technique-editor > summary').click()
    await page.getByLabel('交叉手',{exact:true}).check()
    await page.getByLabel('我已观看这段原片，确认填写的动作及接触',{exact:true}).check()
    await save.click()
    await page.waitForFunction(()=>Array.from(document.querySelectorAll('.action-detail > button')).some(button=>button.textContent.includes('撤销上一次动作修正') && !button.disabled))
    await page.waitForFunction(()=>{const v=document.querySelector('video');return v?.readyState>=2 && new URL(v.currentSrc).searchParams.get('version')==='human-correction-version'})
    assert.equal(mutations.at(-1).body.result_version,'real-source-local-result')
    assert.deepEqual(mutations.at(-1).body.technique_codes,['CROSS'])
    assert.equal(mutations.at(-1).body.source_hold_id,'1')
    await page.locator('video').evaluate((v,t)=>{v.pause();v.currentTime=t;v.dispatchEvent(new Event('timeupdate'))},at+.03)
    await page.locator('.motion-name').filter({hasText:'原点重新抓握'}).waitFor()
    if (captureScreenshots) await page.screenshot({path:fileURLToPath(new URL(`review-${width}.png`,shots)),fullPage:true})
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false)
    await page.getByRole('button',{name:'撤销上一次动作修正',exact:true}).click()
    await page.waitForFunction(()=>Array.from(document.querySelectorAll('.action-detail > button')).some(button=>button.textContent.includes('撤销上一次动作修正') && button.disabled))
    assert.equal(mutations.at(-1).body.result_version,'human-correction-version')
    assert.ok(mutations.at(-1).path.endsWith('/review/undo'))
    assert.deepEqual(errors,[])
  } finally {await page.close()}
})

for (const width of [1280, 390]) test(`single player source-time interaction at ${width}px`, async () => {
  const { page, mutations, errors } = await setup(width)
  try {
    assert.equal(await page.locator('video').count(), 1)
    assert.equal(await page.locator('video').evaluate(v => v.playbackRate), .75)
    assert.equal(await page.locator('.summary-overlay,.summary-orb').count(),0)
    assert.equal(await page.getByLabel('当前动作解析',{exact:true}).evaluate(el=>!!el.closest('.replay-cinema')),false)
    const buttons = page.getByRole('navigation', { name: '动作时间轴' }).getByRole('button')
    await buttons.nth(1).click()
    assert.equal(await page.locator('video').evaluate(v => v.playbackRate), .75)
    assert.ok(await page.locator('video').evaluate(v => v.currentTime) >= organized.groups[1].start_seconds)
    assert.equal(await page.getByLabel('循环', { exact: true }).isChecked(), false)
    await page.getByRole('button', { name: '下一段', exact: true }).click()
    assert.ok(await page.locator('video').evaluate(v => v.currentTime) >= organized.groups[2].start_seconds)
    await page.getByRole('button', { name: '重看', exact: true }).click()
    await page.getByLabel('播放速度', {exact:true}).selectOption('0.5')
    await page.getByRole('button', { name: '重看', exact: true }).click()
    assert.equal(await page.locator('video').evaluate(v=>v.playbackRate),.5)
    await page.getByLabel('播放速度', {exact:true}).selectOption('0.75')
    await page.locator('video').evaluate((v, end) => { v.currentTime = end - .08 }, organized.groups[2].end_seconds)
    await page.waitForFunction(() => document.querySelector('video').paused)
    assert.equal(await page.locator('.summary-overlay').count(),0)
    await page.getByLabel('循环', { exact: true }).check()
    await page.getByRole('button', { name: '重看', exact: true }).click()
    await page.locator('video').evaluate((v, end) => { v.currentTime = end - .08 }, organized.groups[2].end_seconds)
    await page.waitForFunction(start => document.querySelector('video').currentTime < start + .7, organized.groups[2].start_seconds)
    // Actual mouse dragging on Chromium's native media timeline; no synthetic seek event.
    const box = await page.locator('video').boundingBox()
    await page.mouse.move(box.x + box.width * .75, box.y + box.height - 18)
    await page.mouse.down()
    await page.mouse.move(box.x + box.width * .12, box.y + box.height - 18, { steps: 15 })
    await page.mouse.up()
    await page.waitForFunction(() => document.querySelector('video').currentTime < 3)
    assert.equal(await page.getByRole('button', { name: '重看', exact: true }).count(), 0)
    assert.equal(await page.locator('video').evaluate(v => v.playbackRate), .75)
    // Finish once: sequenced data over the blurred final frame, then a small disc.
    await page.locator('video').evaluate(v => { v.currentTime = v.duration - .15; v.play() })
    await page.waitForFunction(()=>document.querySelector('video').ended)
    await page.locator('.summary-overlay').waitFor()
    assert.equal(await page.locator('.summary-overlay').evaluate(el=>!!el.closest('.unified-stage')),true)
    const dataText = await page.locator('.summary-overlay').innerText()
    assert.ok(dataText.includes('线路岩点使用'))
    if (captureScreenshots) await page.screenshot({ path: fileURLToPath(new URL(`summary-${width}.png`, shots)), fullPage: true })
    assert.ok(await page.locator('video').evaluate(v => v.ended))
    await page.getByRole('button',{name:'展开复盘总结',exact:true}).waitFor({timeout:(summarySeconds(organized.metrics,organized.motion_summary)+3)*1000})
    await page.locator('.summary-overlay').waitFor({state:'detached'})
    assert.equal(await page.locator('.summary-overlay').count(),0)
    await page.getByRole('button', {name:'展开复盘总结',exact:true}).click()
    await page.locator('.summary-overlay').waitFor()
    await page.waitForTimeout(450)
    assert.equal(await page.locator('.summary-overlay').count(),1)
    await page.locator('video').evaluate(v=>{v.currentTime=1.4})
    assert.equal(await page.locator('.summary-overlay').count(),1)
    await page.getByRole('button', {name:'收起总结',exact:true}).click()
    await page.locator('.summary-overlay').waitFor({state:'detached'})
    await buttons.nth(1).click()
    assert.equal(await page.locator('.summary-overlay').count(),0)
    assert.equal(await page.locator('video').evaluate(v=>getComputedStyle(v).filter),'none')
    await page.getByLabel('播放速度',{exact:true}).selectOption('1')
    await page.getByRole('button',{name:'整段观看',exact:true}).click()
    assert.equal(await page.locator('video').evaluate(v=>v.playbackRate),.75)
    await page.locator('video').evaluate(v=>{v.currentTime=v.duration-.1;return v.play()})
    await page.waitForFunction(()=>document.querySelector('video').ended)
    assert.equal(await page.locator('.summary-overlay').count(),0)
    assert.equal(await page.getByRole('button',{name:'展开复盘总结',exact:true}).count(),1)
    await buttons.nth(1).click()
    await page.getByRole('button', { name: '导出', exact: true }).click()
    await page.getByLabel('导出范围', { exact: true }).selectOption('group')
    assert.equal(await page.getByLabel('导出速度', {exact:true}).inputValue(),'0.75')
    await page.getByRole('button', { name: '生成导出文件', exact: true }).click()
    assert.equal(mutations.at(-1).body.scope, 'group')
    assert.equal(mutations.at(-1).body.speed, .75)
    assert.equal(mutations.at(-1).body.group_id, organized.groups[1].id)
    assert.deepEqual(Object.keys(mutations.at(-1).body).sort(), ['group_id', 'result_version', 'scope', 'speed'])
    assert.deepEqual(errors, [])
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false)
  } finally { await page.close() }
})

test('a retained legacy summary tail stops at the source climbing end', async () => {
  const {page,state,errors} = await setup(1280)
  try {
    state.media_ready = false
    state.result.source_duration_seconds = 2
    await page.reload(); await page.waitForFunction(()=>document.querySelector('video')?.readyState>=2)
    await page.locator('video').evaluate(v=>v.play())
    await page.locator('.summary-overlay').waitFor()
    await page.waitForTimeout(700)
    assert.equal(await page.locator('.summary-overlay').isVisible(),true)
    const playback = await page.locator('video').evaluate(v=>({time:v.currentTime,paused:v.paused,speed:v.playbackRate}))
    assert.ok(playback.time <= 2 && playback.time >= 1.9)
    assert.equal(playback.paused,true)
    assert.equal(playback.speed,.75)
    assert.deepEqual(errors,[])
  } finally {await page.close()}
})

test('replay deep links select only an owned listed record without starting processing', async () => {
  for (const replay of ['owned-existing', 'unlisted-record', null]) {
    const page = await browser.newPage()
    const mutations = [], errors = []
    const job = {id:'owned-existing',status:'succeeded',original_name:'已有复盘.mp4',route_color:'黄色',
      created_at:'2026-09-30T00:00:00Z',video:organized.video,
      media:{source_video:{status:'available'},overlay_video:{status:'available'}},
      result:{...structuredClone(organized),hold_evidence:{selection:'color_candidates_need_review'}}}
    page.on('pageerror',error=>errors.push(error.message))
    await page.route('**/api/**',async route=>{
      const request=route.request(),path=new URL(request.url()).pathname
      if(request.method()!=='GET') mutations.push(path)
      if(path.endsWith('/jobs')) return route.fulfill({json:[job]})
      if(path.endsWith('/actions')) return route.fulfill({json:{result:organized,result_version:'existing',media_ready:true}})
      if(path.includes('/media')) return route.fulfill({body:media,contentType:'video/webm'})
      if(path.endsWith('/consent-policy')) return route.fulfill({json:{version:'fixture',enabled:false}})
      return route.fulfill({json:[]})
    })
    try {
      await page.goto(`${base}/e2e/coaching-harness.html?parent${replay?`&replay=${replay}`:''}`)
      await page.getByText('已有复盘.mp4',{exact:true}).waitFor({state:'attached'})
      if(replay==='owned-existing') await page.locator('.unified-replay').waitFor()
      else assert.equal(await page.locator('.unified-replay').count(),0)
      assert.deepEqual(mutations,[])
      assert.deepEqual(errors,[])
    } finally {await page.close()}
  }
})
