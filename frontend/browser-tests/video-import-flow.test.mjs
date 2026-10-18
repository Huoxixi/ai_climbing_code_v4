import test,{after} from 'node:test'
import assert from 'node:assert/strict'
import {chromium} from '@playwright/test'
import {spawnSync} from 'node:child_process'
import {readFileSync,mkdirSync} from 'node:fs'
import {fileURLToPath} from 'node:url'
import {startFixtureServer} from './fixtures/server.mjs'
const project=fileURLToPath(new URL('../../',import.meta.url))
const directory=new URL('../../.tmp/video-preview-20261015/browser-flow/',import.meta.url);mkdirSync(directory,{recursive:true})
const file=fileURLToPath(new URL('canonical.mp4',directory))
const encoder='D:/ai_climbing_code/.tools/boulder-python/imageio_ffmpeg/binaries/ffmpeg-win-x86_64-v7.1.exe'
const encoded=spawnSync(encoder,['-v','error','-f','lavfi','-i','testsrc2=size=96x128:rate=10:duration=1','-an','-c:v','libx264','-pix_fmt','yuv420p','-y',file],{windowsHide:true})
assert.equal(encoded.status,0,encoded.stderr?.toString())
const media=readFileSync(file)
const base=await startFixtureServer(4242),browser=await chromium.launch({headless:true});after(()=>browser.close())

test('any selected video uploads before decoding and prepared id starts analysis without a second upload',async()=>{
  const page=await browser.newPage(),calls=[],errors=[]
  page.on('pageerror',e=>errors.push(e.message))
  const original=Buffer.from('original HEVC/transport-stream bytes; browser cannot decode these')
  await page.route('**/api/**',async route=>{
    const request=route.request(),pathname=new URL(request.url()).pathname
    if(request.method()!=='GET')calls.push({path:pathname,body:request.postDataBuffer()})
    if(pathname.endsWith('/preview-capability'))return route.fulfill({json:{local_conversion:true}})
    if(pathname.endsWith('/preview-video')&&request.method()==='POST'){
      assert.ok(request.postDataBuffer().includes(original))
      return route.fulfill({body:media,contentType:'video/mp4',headers:{'X-Source-Duration':'1','X-Prepared-Video-Id':'prepared-once'}})
    }
    if(pathname.includes('/prepared-videos/'))return route.fulfill({json:{id:'prepared-job',status:'awaiting_hold_review',original_name:'phone.mts',video:{width:96,height:128,fps:10,frame_count:10,duration_seconds:1},media:{source_video:{status:'available'}},hold_draft:{holds:[]}}})
    if(pathname.endsWith('/source-video'))return route.fulfill({body:media,contentType:'video/mp4'})
    return route.fulfill({json:pathname.endsWith('/jobs')?[]:{version:'local-v1'}})
  })
  try{
    await page.goto(base+'/e2e/local-replay-harness.html')
    await page.locator('input[type=file]').setInputFiles({name:'phone.mts',mimeType:'application/octet-stream',buffer:original})
    const picker=page.getByRole('button',{name:'从画面点选样本岩点',exact:true})
    await picker.waitFor();await page.waitForFunction(()=>document.querySelector('video')?.readyState>=2)
    assert.equal(calls.filter(c=>c.path.endsWith('/preview-video')).length,1)
    await picker.click()
    const canvas=page.getByRole('button',{name:'在暂停的视频画面中点击目标线路岩点取色',exact:true})
    const bounds=await canvas.boundingBox();await canvas.click({position:{x:bounds.width/2,y:bounds.height/2}})
    await page.getByRole('button',{name:'识别岩点',exact:true}).click()
    await page.getByRole('button',{name:'确认全部岩点',exact:true}).waitFor()
    assert.equal(calls.filter(c=>c.path.includes('/prepared-videos/prepared-once/start')).length,1)
    assert.equal(calls.filter(c=>c.path.endsWith('/uploads')||c.path.endsWith('/jobs')).length,0)
    const payload=JSON.parse(calls.find(c=>c.path.endsWith('/start')).body.toString())
    assert.equal(payload.route_color_sample.source,'video')
    assert.deepEqual(payload.route_color_sample.point_xy.map(v=>Math.round(v*10)/10),[.5,.5])
    assert.deepEqual(errors,[])
  }finally{await page.close()}
})

test('conversion failure stays retryable and does not display an undecodable original',async()=>{
  const page=await browser.newPage();let conversions=0
  await page.route('**/api/**',route=>{
    const p=new URL(route.request().url()).pathname
    if(p.endsWith('/preview-capability'))return route.fulfill({json:{local_conversion:true}})
    if(p.endsWith('/preview-video')){conversions++;return route.fulfill({status:422,json:{detail:'本机未能准备视频，请重试。'}})}
    return route.fulfill({json:p.endsWith('/jobs')?[]:{version:'local-v1'}})
  })
  try{
    await page.goto(base+'/e2e/local-replay-harness.html')
    await page.locator('input[type=file]').setInputFiles({name:'broken.avi',mimeType:'video/x-msvideo',buffer:Buffer.from('bad')})
    await page.getByText('本机未能准备视频，请重试。',{exact:true}).waitFor()
    assert.equal(await page.locator('video').getAttribute('src'),null)
    assert.equal(await page.getByRole('button',{name:'跳过岩点识别',exact:true}).isEnabled(),false)
    await page.getByRole('button',{name:'重新加载画面',exact:true}).click()
    await page.waitForFunction(()=>document.querySelector('[role=alert]')?.textContent.includes('本机未能准备视频'))
    assert.equal(conversions,2)
  }finally{await page.close()}
})
