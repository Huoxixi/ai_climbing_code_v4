import { startFixtureServer } from './fixtures/server.mjs'
import { organized } from './fixtures/actions.mjs'
import { chromium } from '@playwright/test'
import test, { after } from 'node:test'
import assert from 'node:assert/strict'
import { mkdir } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'
const base = await startFixtureServer(4205)
const browser = await chromium.launch({ headless: true })
after(() => browser.close())
const artifacts = new URL('../../.tmp/torso-trajectory-verification/', import.meta.url)
await mkdir(artifacts, { recursive: true })
const holds = [
  {id:1,bbox:[.4,.1,.12,.08],polygon:[[.4,.12],[.46,.1],[.52,.13],[.5,.18],[.42,.17]]},
  {id:2,bbox:[.52,.4,.1,.08],polygon:[[.52,.42],[.59,.4],[.62,.44],[.6,.48],[.53,.47]]},
  {id:3,bbox:[.4,.7,.12,.08],polygon:[[.4,.72],[.46,.7],[.52,.73],[.5,.78],[.42,.77]]},
]
const overlay = {width:1000,height:800,layout:'split_route_map_actions_v8',action_count:18,video_rect:[0,78,640,480],route_map_rect:[460,-30,720,540],torso_center:'baked'}
const identity = [[1,0,0],[0,1,0],[0,0,1]]
const trajectory = { status:'partial',reference_size:[640,480],version:'registered-torso-center-trajectory-v2',climbing_window:{start_seconds:.5,end_seconds:1.5,status:'finish_observed'},
  segments:[[[.46,.7],[.45,.6],[.48,.5]],[[.48,.4],[.46,.3],[.47,.2]]].map(run=>run.map((xy,i)=>({xy,time_seconds:.5+i*.25}))) }
// Constructed wall and skeleton only; no user photos or records.
const maker = await browser.newPage()
const media = Buffer.from(await maker.evaluate(async ({holds}) => {
  const c=document.createElement('canvas'); c.width=1000;c.height=800
  const ctx=c.getContext('2d'), stream=c.captureStream(24), rec=new MediaRecorder(stream,{mimeType:'video/webm;codecs=vp8'}),chunks=[]
  rec.ondataavailable=e=>chunks.push(e.data);const done=new Promise(r=>rec.onstop=r)
  const polygon=(poly,rect,color)=>{ctx.beginPath();poly.forEach(([x,y],i)=>ctx[i?'lineTo':'moveTo'](rect[0]+x*rect[2],rect[1]+y*rect[3]));ctx.closePath();ctx.fillStyle=color;ctx.fill();ctx.strokeStyle='#81857a';ctx.lineWidth=3;ctx.stroke()}
  function paint(){ctx.fillStyle='#10120f';ctx.fillRect(0,0,1000,800);ctx.fillStyle='#76796f';ctx.fillRect(0,78,640,480)
    for(const h of holds){polygon(h.polygon,[0,78,640,480],'#d7b440');polygon(h.polygon,[460,-30,720,540],'#20241f')}
    ctx.strokeStyle='#75e7ee';ctx.lineWidth=9;ctx.beginPath();ctx.moveTo(290,240);ctx.lineTo(280,350);ctx.lineTo(250,430);ctx.moveTo(280,350);ctx.lineTo(340,430);ctx.moveTo(290,250);ctx.lineTo(255,200);ctx.moveTo(290,250);ctx.lineTo(340,205);ctx.stroke()
    ctx.fillStyle='#f4c854';ctx.beginPath();ctx.arc(290,210,18,0,7);ctx.fill()
    ctx.fillStyle='#eee';ctx.font='18px sans-serif';ctx.fillText('线路动作图',654,26)
    ctx.fillStyle='#bc317d';ctx.fillRect(0,636,1000,164);ctx.fillStyle='#fff';ctx.fillText('OLD ACTION STRIP SHOULD BE REMOVED',24,720)
  }
  paint();rec.start();const timer=setInterval(paint,40);await new Promise(r=>setTimeout(r,1800));clearInterval(timer);rec.stop();await done;stream.getTracks().forEach(t=>t.stop());return Array.from(new Uint8Array(await new Blob(chunks).arrayBuffer()))
},{holds}))
await maker.close()
async function check(width) {
 const page=await browser.newPage({viewport:{width,height:900}}),writes=[],errors=[]
 page.setDefaultTimeout(10000);page.on('pageerror',e=>errors.push(e.message))
 await page.route('**/api/**',async route=>{
  const req=route.request(),path=new URL(req.url()).pathname
  if(req.method()!=='GET')writes.push(path)
  if(path.endsWith('/media')||path.endsWith('/overlay-video')){
   const range=req.headers().range?.match(/bytes=(\d+)-(\d*)/),start=range?+range[1]:0,end=range?.[2]?Math.min(+range[2],media.length-1):media.length-1
   return route.fulfill({status:range?206:200,body:media.subarray(start,end+1),contentType:'video/webm',headers:{'Accept-Ranges':'bytes','Content-Length':String(end-start+1),...(range?{'Content-Range':`bytes ${start}-${end}/${media.length}`}:{})}})
  }
  return route.fulfill({json:{result:{...organized,torso_trajectory:trajectory,route_usage:{route_hold_ids:['1','2','3'],used_hold_ids:['1','3'],total:3,used:2}},media_ready:true,result_version:'trajectory-fixture',task:{status:'succeeded'}}})
 })
 const job=id=>({id,status:'succeeded',media:{source_video:{status:'available'}},result:{video:{width:640,height:480,duration_seconds:1.8,fps:24,frame_count:43},overlay,holds,pose_samples:[{observed:true,time_seconds:1.5,source_frame_id:36,wall_alignment:'reference',wall_reference_transform:identity}]}})
 try {
  await page.goto(base+'/e2e/actions-harness.html')
  await page.evaluate(job=>window.actionsHarness.setJob(job),job('before-end'))
  await page.waitForFunction(()=>document.querySelector('video')?.readyState>=2)
  const stats=page.getByRole('region',{name:'基础数据统计',exact:true})
  await stats.waitFor()
  const frame=await page.locator('.replay-frame').boundingBox()
  assert.ok(Math.abs(frame.width/frame.height-1280/480)<.01,'legacy action strip excluded; map matches original scale')
  assert.equal(await page.locator('canvas').getAttribute('width'),'1280')
  assert.equal(await page.locator('canvas').getAttribute('height'),'480')
  await page.locator('video').evaluate(v=>{v.currentTime=v.duration-.1;return v.play()})
  await page.waitForFunction(()=>document.querySelector('video').ended)
  assert.equal(await page.locator('.summary-overlay,.summary-orb,.torso-route-end,.unused-holds').count(),0)
  assert.equal(await page.getByRole('button',{name:'复盘总结',exact:true}).count(),0)
  assert.deepEqual(writes,[]);assert.deepEqual(errors,[])
 } finally {await page.close()}
}
test('旧复盘去掉总结卡片，保留同尺度双画面和基础统计，桌面与手机',async()=>{await Promise.all([check(1280),check(390)])})
