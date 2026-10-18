import { chromium } from '@playwright/test'
import test, {after} from 'node:test'
import assert from 'node:assert/strict'
import {mkdir} from 'node:fs/promises'
import {startFixtureServer} from './fixtures/server.mjs'
import {organized,syntheticMedia} from './fixtures/actions.mjs'
const base=await startFixtureServer(4228)
const browser=await chromium.launch({headless:true})
const media=await syntheticMedia(browser)
await mkdir(new URL('../../.tmp/replay-full-analysis/',import.meta.url),{recursive:true})
after(()=>browser.close())

for(const width of [1280,390]) test(`whole analysis and independent playback at ${width}`,async()=>{
  const page=await browser.newPage({viewport:{width,height:900},reducedMotion:'reduce'})
  const errors=[];page.on('pageerror',e=>errors.push(e.message))
  const result=structuredClone(organized)
  result.ai_analysis={overview:'身体逐步上移，动作之间保持连续。',input_mode:'frames',
    actions:[{id:'analysis-001',group_id:result.groups[0].id,title:'抬脚后上移',start_seconds:0,end_seconds:1.5,
      observation:'左脚抬高，随后身体上移。',evaluation:'可见脚部与身体移动衔接。',next_check:'回看抬脚后的身体位置。'}],
    priority_focus:'优先回看身体上移后的稳定阶段。',limitations:[]}
  await page.route('**/api/climb-replay/**',r=>/\/(media|overlay-video|source-video)$/.test(new URL(r.request().url()).pathname)
    ?r.fulfill({body:media,contentType:'video/webm'})
    :r.fulfill({json:{task:{status:'succeeded'},result,result_version:'v1',export:{status:'idle'},cloud_configured:true}}))
  try{
    await page.goto(base+'/e2e/actions-harness.html')
    await page.getByRole('heading',{name:'AI 复盘分析'}).waitFor()
    assert.equal(await page.getByText('身体逐步上移，动作之间保持连续。').count(),1)
    assert.equal(await page.locator('.action-list button').count(),1)
    await page.locator('.commentary-segment').click()
    assert.equal(await page.getByRole('button',{name:'重看',exact:true}).count(),1)
    assert.equal(await page.getByText('重要动作解说',{exact:true}).count(),0)
    assert.equal(await page.getByRole('button',{name:'整理动作',exact:true}).count(),0)
    await page.screenshot({path:new URL(`../../.tmp/replay-full-analysis/${width}.png`,import.meta.url).pathname.replace(/^\/([A-Z]:)/,'$1'),fullPage:true})
    assert.deepEqual(errors,[])
  }finally{await page.close()}
})

test('ordinary local events do not disable authorized AI analysis',async()=>{
  const page=await browser.newPage(),writes=[]
  const result=structuredClone(organized)
  result.commentary_policy={important_only:true,selected_event_count:0}
  result.event_validation={analysis_valid:false}
  await page.route('**/api/climb-replay/**',r=>{
    if(/\/(media|overlay-video|source-video)$/.test(new URL(r.request().url()).pathname))return r.fulfill({body:media,contentType:'video/webm'})
    if(r.request().method()==='POST')writes.push(r.request().postDataJSON())
    return r.fulfill({json:{task:{status:'idle'},result,result_version:'v1',cloud_configured:true,consent_version:'whole-climb-analysis-v1',export:{status:'idle'}}})
  })
  try{
    await page.goto(base+'/e2e/actions-harness.html')
    const start=page.getByRole('button',{name:'开始 AI 复盘',exact:true})
    await start.waitFor();assert.equal(await start.isDisabled(),true)
    assert.deepEqual(writes,[])
    await page.getByLabel('同意发送本次复盘资料，并确认费用').check()
    await start.click();await page.waitForTimeout(100)
    assert.equal(writes.length,1);assert.equal(writes[0].cloud_consent,true)
  }finally{await page.close()}
})

test('independent AI action exports once and starts download automatically',async()=>{
  const page=await browser.newPage(),writes=[]
  const result=structuredClone(organized)
  result.ai_analysis={overview:'整体观察。',actions:[{id:'analysis-001',group_id:null,title:'身体上移',
    start_seconds:1,end_seconds:2,observation:'可见身体上移。',evaluation:'动作衔接连贯。'}],limitations:[]}
  let exported=false
  await page.route('**/api/climb-replay/**',r=>{
    const path=new URL(r.request().url()).pathname
    if(path.endsWith('/actions/media'))return r.fulfill({body:media,contentType:'video/webm',headers:{'Content-Disposition':'attachment; filename="climb-replay.mp4"'}})
    if(/\/(media|overlay-video|source-video)$/.test(path))return r.fulfill({body:media,contentType:'video/webm'})
    if(r.request().method()==='POST'){writes.push(r.request().postDataJSON());exported=true}
    return r.fulfill({json:{task:{status:'succeeded'},result,result_version:'v1',export:{status:exported?'succeeded':'idle'},
      ...(exported?{export_media:{id:'export-1',scope:'group',speed:.75,result_version:'v1'}}:{})}})
  })
  try{
    await page.goto(base+'/e2e/actions-harness.html')
    await page.locator('.commentary-segment').click()
    await page.getByRole('button',{name:'导出',exact:true}).click()
    await page.getByLabel('导出范围',{exact:true}).selectOption('group')
    const downloaded=page.waitForEvent('download')
    await page.getByRole('button',{name:'导出文件',exact:true}).click()
    assert.equal((await downloaded).suggestedFilename(),'climb-replay.mp4')
    assert.equal(writes.length,1)
    assert.equal(writes[0].group_id,null)
    assert.equal(writes[0].segment_id,'analysis-001')
    assert.equal(writes[0].scope,'group')
  }finally{await page.close()}
})
