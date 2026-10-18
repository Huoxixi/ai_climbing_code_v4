import {chromium} from '@playwright/test'
import test,{after} from 'node:test'
import assert from 'node:assert/strict'
import {startFixtureServer} from './fixtures/server.mjs'
import {organized,syntheticMedia} from './fixtures/actions.mjs'
import {spawnSync} from 'node:child_process'
import {readFileSync,mkdirSync,unlinkSync,existsSync} from 'node:fs'
import {fileURLToPath} from 'node:url'
const base=await startFixtureServer(4238),browser=await chromium.launch({headless:true}),rawMedia=await syntheticMedia(browser)
// MediaRecorder WebM has no seek index. Remux synthetic frames to test actual seeking.
const bundledFfmpeg=fileURLToPath(new URL('../../../../.tools/boulder-python/imageio_ffmpeg/binaries/ffmpeg-win-x86_64-v7.1.exe',import.meta.url))
const mediaDirectory=new URL('../../.tmp/replay-seek-browser/',import.meta.url)
mkdirSync(mediaDirectory,{recursive:true})
const mediaFile=fileURLToPath(new URL(`seekable-${process.pid}.webm`,mediaDirectory))
const remux=spawnSync(process.env.FFMPEG_EXE || (existsSync(bundledFfmpeg)?bundledFfmpeg:'ffmpeg'),['-v','error','-i','pipe:0','-c','copy','-y',mediaFile],{input:rawMedia,windowsHide:true})
assert.equal(remux.status,0,remux.stderr?.toString())
const media=readFileSync(mediaFile);unlinkSync(mediaFile)
after(()=>browser.close())
for(const width of [1280,390])test(`preparation editing then clean result ${width}`,async()=>{
 const page=await browser.newPage({viewport:{width,height:900}}),writes=[],errors=[]
 page.on('pageerror',e=>errors.push(e.message))
 let job={id:'prep',original_name:'constructed.mp4',status:'awaiting_hold_review',video:organized.video,
  media:{source_video:{status:'available'}},hold_draft:{video:organized.video,holds:[{id:'1',bbox:[.2,.2,.1,.1],polygon:[[.2,.2],[.3,.2],[.3,.3],[.2,.3]]}]},holds_revision:'r1'}
 await page.route('**/api/**',r=>{
  const req=r.request(),path=new URL(req.url()).pathname
  if(req.method()==='POST')writes.push({path,body:req.postDataJSON()})
  if(path.endsWith('/source-video')){
    const range=req.headers().range?.match(/bytes=(\d+)-(\d*)/)
    if(range){const start=Number(range[1]),end=Math.min(media.length-1,range[2]?Number(range[2]):media.length-1);return r.fulfill({status:206,body:media.subarray(start,end+1),contentType:'video/webm',headers:{'Accept-Ranges':'bytes','Content-Range':`bytes ${start}-${end}/${media.length}`,'Content-Length':String(end-start+1)}})}
    return r.fulfill({body:media,contentType:'video/webm',headers:{'Accept-Ranges':'bytes','Content-Length':String(media.length)}})
  }
  if(path.endsWith('/consent-policy'))return r.fulfill({json:{version:'local-v1'}})
  if(path.endsWith('/jobs'))return r.fulfill({json:[job]})
  if(path.endsWith('/holds/confirm-all')){job={...job,holds_confirmation:{revision:'r1'}};return r.fulfill({json:job})}
  if(path.endsWith('/analysis/start')){job={...job,status:'succeeded',result:{...organized,pose_samples:[]}};return r.fulfill({json:job})}
  if(path.endsWith('/actions'))return r.fulfill({json:{task:{status:'succeeded'},result:{...organized,metrics:[...organized.metrics,{key:'longest_still',label:'最长姿态停留',value:1,unit:'秒',start_seconds:1.25,end_seconds:2.25}],ai_analysis:{overview:'must not show'}},result_version:'v1',export:{status:'idle'},cloud_configured:true}})
  return r.fulfill({json:job})
 })
 try{
  await page.goto(base+'/e2e/local-replay-harness.html?replay=prep')
  await page.getByRole('button',{name:'放大单帧／手绘轮廓',exact:true}).waitFor()
  assert.equal(await page.getByRole('button',{name:'补删点',exact:true}).count(),1)
  assert.equal(await page.getByRole('button',{name:'跳过岩点识别',exact:true}).count(),1)
  await page.getByRole('button',{name:'确认全部岩点',exact:true}).click()
  await page.getByRole('button',{name:'开始复盘',exact:true}).click()
  await page.getByRole('button',{name:'导出',exact:true}).waitFor()
  assert.equal(await page.getByRole('navigation',{name:'动作时间轴',exact:true}).count(),0)
  assert.equal(await page.getByRole('button',{name:'更换视频',exact:true}).count(),0)
  for(const name of ['放大单帧／手绘轮廓','补删点','跳过岩点识别','开始 AI 复盘','修正动作'])assert.equal(await page.getByRole('button',{name,exact:true}).count(),0)
  assert.equal(await page.getByText('must not show',{exact:true}).count(),0)
  await page.getByRole('button',{name:'基础数据统计',exact:true}).click()
  await page.getByRole('heading',{name:'基础数据统计',exact:true}).waitFor()
  await page.waitForFunction(()=>document.querySelector('video')?.readyState>=2)
  await page.getByRole('button',{name:'跳转到最长姿态停留',exact:true}).click()
  await page.waitForFunction(()=>{const v=document.querySelector('video');return v && !v.paused && !v.seeking})
  const jumped=await page.locator('video').evaluate(v=>v.currentTime)
  assert.ok(jumped>=1.24 && jumped<1.6,`jump starts at posture hold start; actual ${jumped}`)
  await page.waitForFunction(()=>{const v=document.querySelector('video');return v.currentTime>3 && !v.paused})
  assert.equal(await page.locator('.segment-controls').count(),0,'jump imposes no playback stop or loop')
  await page.getByRole('button',{name:'导出',exact:true}).click()
  assert.equal(await page.getByRole('dialog',{name:'导出复盘',exact:true}).getByRole('checkbox').count(),4)
  assert.equal(writes.some(x=>x.body?.cloud_consent===true),false)
  await page.getByRole('button',{name:'关闭面板',exact:true}).click()
  const beforeReturn = writes.length
  await page.getByRole('button',{name:'返回',exact:true}).click()
  await page.getByText('导入视频',{exact:true}).waitFor()
  assert.equal(writes.length,beforeReturn)
  if(width>=900){
    await page.getByRole('button',{name:/最近分析/}).click()
    await page.getByText('constructed.mp4',{exact:true}).click()
    await page.getByRole('button',{name:'导出',exact:true}).waitFor()
  }
  assert.deepEqual(errors,[])
 }finally{await page.close()}
})
test('local preparation precedes color picking without starting recognition',async()=>{
 const page=await browser.newPage(),errors=[];page.on('pageerror',e=>errors.push(e.message))
 await page.route('**/api/**',r=>{
  const pathname=new URL(r.request().url()).pathname
  if(pathname.endsWith('/preview-capability'))return r.fulfill({json:{local_conversion:true}})
  if(pathname.endsWith('/preview-video'))return r.fulfill({body:media,contentType:'video/mp4',headers:{'X-Prepared-Video-Id':'prepared-local-test'}})
  return r.fulfill({json:pathname.endsWith('/jobs')?[]:{version:'local-v1'}})
 })
 try{
  await page.goto(base+'/e2e/local-replay-harness.html')
  await page.locator('input[type=file]').setInputFiles({name:'constructed.webm',mimeType:'video/webm',buffer:media})
  await page.getByRole('button',{name:'从画面点选样本岩点',exact:true}).waitFor()
  assert.equal(await page.getByRole('button',{name:'跳过岩点识别',exact:true}).count(),1)
  assert.deepEqual(errors,[])
 }finally{await page.close()}
})
