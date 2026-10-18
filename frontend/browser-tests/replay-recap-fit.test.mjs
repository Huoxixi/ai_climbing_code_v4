import { startFixtureServer } from './fixtures/server.mjs'
import { organized } from './fixtures/actions.mjs'
import { chromium } from '@playwright/test'
import test, { after } from 'node:test'
import assert from 'node:assert/strict'
import { mkdir } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'

const base = await startFixtureServer(4208)
const browser = await chromium.launch({headless:true})
after(()=>browser.close())
const artifacts = new URL('../../.tmp/recap-fit-20261009/',import.meta.url)
await mkdir(artifacts,{recursive:true})
const maker=await browser.newPage()
// Constructed portrait split view, never user media or identity evidence.
const media=Buffer.from(await maker.evaluate(async()=>{
 const c=document.createElement('canvas');c.width=640;c.height=568
 const x=c.getContext('2d'),stream=c.captureStream(12),chunks=[]
 const rec=new MediaRecorder(stream,{mimeType:'video/webm;codecs=vp8'})
 rec.ondataavailable=e=>chunks.push(e.data);const stopped=new Promise(r=>rec.onstop=r)
 function paint(){x.fillStyle='#777c72';x.fillRect(0,0,320,568);x.fillStyle='#10130f';x.fillRect(320,0,320,568)
  for(const [a,b] of [[90,130],[220,280],[110,430]]){x.fillStyle='#debf4e';x.fillRect(a,b,24,18);x.strokeStyle='#858b7e';x.strokeRect(a+320,b,24,18)}
  x.strokeStyle='#75e7ee';x.lineWidth=5;x.beginPath();x.moveTo(155,230);x.lineTo(155,340);x.lineTo(110,430);x.moveTo(155,340);x.lineTo(220,410);x.moveTo(155,250);x.lineTo(100,145);x.moveTo(155,250);x.lineTo(220,280);x.stroke();x.fillStyle='#f4cd55';x.beginPath();x.arc(155,210,15,0,7);x.fill()}
 paint();rec.start();const loop=setInterval(paint,75);await new Promise(r=>setTimeout(r,1050));clearInterval(loop);rec.stop();await stopped;stream.getTracks().forEach(t=>t.stop())
 return Array.from(new Uint8Array(await new Blob(chunks).arrayBuffer()))
}))
await maker.close()
const holds=[{id:1,polygon:[[.28,.23],[.36,.23],[.36,.26],[.28,.26]]},{id:2,polygon:[[.68,.49],[.76,.49],[.76,.52],[.68,.52]]}]
const trajectory={segments:[[{xy:[.5,.7],time_seconds:.3},{xy:[.5,.4],time_seconds:.7}]],climbing_window:{status:'finish_observed',end_seconds:.7}}
const motion={duration_seconds:1,segments:[{kind:'moving',start_seconds:0,end_seconds:1}],totals:[{kind:'moving',label:'移动',percent:100,seconds:1}]}
async function setup({width,height},reduced=false) {
 const page=await browser.newPage({viewport:{width,height},reducedMotion:reduced?'reduce':'no-preference'}),errors=[],writes=[]
 page.on('pageerror',e=>errors.push(e.message));page.setDefaultTimeout(10000)
 await page.route('**/api/**',async route=>{
  const req=route.request(),path=new URL(req.url()).pathname
  if(req.method()!=='GET')writes.push(path)
  if(path.endsWith('/media')||path.endsWith('/overlay-video')||path.endsWith('/source-video')){
   const range=req.headers().range?.match(/bytes=(\d+)-(\d*)/),start=range?+range[1]:0,end=range?.[2]?Math.min(+range[2],media.length-1):media.length-1
   return route.fulfill({status:range?206:200,body:media.subarray(start,end+1),contentType:'video/webm',headers:{'Accept-Ranges':'bytes','Content-Length':String(end-start+1),...(range?{'Content-Range':`bytes ${start}-${end}/${media.length}`}:{})}})
  }
  return route.fulfill({json:{result:{...organized,motion_summary:motion,torso_trajectory:trajectory,route_usage:{route_hold_ids:['1','2'],used_hold_ids:['1'],total:2,used:1}},media_ready:true,result_version:'portrait-recap',task:{status:'succeeded'}}})
 })
 await page.goto(base+'/e2e/actions-harness.html')
 await page.evaluate(({holds})=>window.actionsHarness.setJob({id:'portrait',status:'succeeded',media:{source_video:{status:'available'}},result:{
  video:{width:320,height:568,duration_seconds:1.05,fps:12,frame_count:13},overlay:{width:640,height:568,layout:'split_route_map_equal_v10',video_rect:[0,0,320,568]},holds,pose_samples:[]}}),{holds})
 await page.waitForFunction(()=>document.querySelector('video')?.readyState>=2)
 await page.mouse.move(width-1,height-1)
 return {page,errors,writes}
}
for(const viewport of [{width:1280,height:720},{width:1280,height:850},{width:390,height:844},{width:844,height:390}])test(`video, timeline and statistics orb at ${viewport.width}×${viewport.height}`,async()=>{
 const {page,errors,writes}=await setup(viewport)
 try{
  const fit=await page.locator('.replay-cinema').evaluate(el=>{const f=el.querySelector('.replay-frame').getBoundingClientRect(),c=el.querySelector('.media-controls').getBoundingClientRect();return {top:f.top,bottom:c.bottom,height:f.height,width:f.width}})
  assert.ok(fit.top>=0&&fit.bottom<=viewport.height,'entire picture and controls fit the visible viewport')
  assert.ok(Math.abs(fit.width/fit.height-640/568)<.01,'both panes keep source proportion')
  const stats=page.getByRole('region',{name:'基础数据统计',exact:true})
  assert.equal(await stats.count(),0,'statistics start hidden')
  const orb=page.getByRole('button',{name:'基础数据统计',exact:true})
  const geometry=await page.evaluate(()=>{const orb=document.querySelector('.statistics-orb').getBoundingClientRect(),frame=document.querySelector('.replay-frame').getBoundingClientRect(),timeline=document.querySelector('.action-strip').getBoundingClientRect();return {orbLeft:orb.left,frameRight:frame.right,bottom:timeline.bottom}})
  assert.ok(geometry.orbLeft>=geometry.frameRight,'orb stays on reserved black margin')
  assert.ok(geometry.bottom<=viewport.height,'video and timeline are both visible')
  assert.equal(await page.locator('.action-label').count(),0,'timeline has no commentary')
  await orb.click()
  await stats.waitFor();assert.ok((await stats.innerText()).includes('攀爬时长'))
  await page.getByRole('button',{name:'关闭基础数据',exact:true}).click()
  await page.getByRole('button',{name:'全屏复盘',exact:true}).click()
  await page.waitForFunction(()=>document.fullscreenElement?.classList.contains('replay-view'))
  assert.equal(await page.getByRole('navigation',{name:'动作时间轴',exact:true}).isVisible(),true)
  await page.evaluate(()=>document.exitFullscreen())
  assert.equal(await page.getByRole('button',{name:'复盘总结',exact:true}).count(),0)
  await page.locator('video').evaluate(v=>{v.currentTime=v.duration-.1;return v.play()})
  await page.waitForFunction(()=>document.querySelector('video').ended)
  // Waiting beyond the old first-card deadline must not reveal any overlay.
  await page.clock.install();await page.clock.fastForward(31000)
  assert.equal(await page.locator('.summary-overlay,.summary-window,.summary-orb,.summary-action,.torso-route-end,.unused-holds').count(),0)
  assert.equal(await page.locator('.replay-cinema').evaluate(el=>getComputedStyle(el.querySelector('canvas')).filter),'none')
  if((viewport.width===1280&&viewport.height===720)||viewport.width===390)await page.screenshot({path:fileURLToPath(new URL(`basic-only-${viewport.width}.png`,artifacts)),fullPage:true})
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false)
  assert.deepEqual(errors,[]);assert.deepEqual(writes,[])
 }finally{await page.close()}
})
