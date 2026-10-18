import {chromium} from '@playwright/test'
import test,{after} from 'node:test'
import assert from 'node:assert/strict'
import {spawnSync} from 'node:child_process'
import {mkdirSync,readFileSync} from 'node:fs'
import {fileURLToPath} from 'node:url'
import {startFixtureServer} from './fixtures/server.mjs'
const base=await startFixtureServer(4246),browser=await chromium.launch({headless:true})
after(()=>browser.close())
const folder=new URL('../../.tmp/current-playback/',import.meta.url);mkdirSync(folder,{recursive:true})
const path=fileURLToPath(new URL('source.mp4',folder))
const ffmpeg=process.env.FFMPEG_EXE || fileURLToPath(new URL('../../../../.tools/boulder-python/imageio_ffmpeg/binaries/ffmpeg-win-x86_64-v7.1.exe',import.meta.url))
const encoded=spawnSync(ffmpeg,['-v','error','-f','lavfi','-i','color=c=0x263b46:s=320x568:r=24:d=3','-c:v','libx264','-pix_fmt','yuv420p','-movflags','+faststart','-y',path],{windowsHide:true})
assert.equal(encoded.status,0,encoded.stderr?.toString())
const media=readFileSync(path),video={width:320,height:568,fps:24,frame_count:72,duration_seconds:3}
const hold={id:1,polygon:[[.1,.1],[.3,.1],[.3,.25],[.1,.25]]}
const contacts=[{limb:'left_hand',hold_id:1,start_source_frame:0,end_source_frame:15}]
for(const width of [1280,390])test(`current local pause, leave, seek back, last frame and export ${width}`,async()=>{
 const page=await browser.newPage({viewport:{width,height:900}}),writes=[],errors=[]
 page.on('pageerror',e=>errors.push(e.message))
 const state={task:{status:'succeeded'},result_version:'fixed-current-v1',result:{video,groups:[],metrics:[],
  replay_visualization:{version:'registered-body-feet-v12',pose_samples:[],contacts}},export:{status:'idle'}}
 await page.route('**/api/**',async route=>{
  const req=route.request(),pathname=new URL(req.url()).pathname
  if(req.method()!=='GET')writes.push({path:pathname,body:req.postDataJSON()})
  if(pathname.endsWith('/source-video')){
   const range=req.headers().range?.match(/bytes=(\d+)-(\d*)/),start=range?Number(range[1]):0,end=range&&range[2]?Math.min(Number(range[2]),media.length-1):media.length-1
   return route.fulfill({status:range?206:200,body:media.subarray(start,end+1),contentType:'video/mp4',headers:{'Accept-Ranges':'bytes',...(range?{'Content-Range':`bytes ${start}-${end}/${media.length}`}:{})}})
  }
  return route.fulfill({json:state})
 })
 try{
  await page.goto(base+'/e2e/local-player-harness.html')
  await page.evaluate(({video,hold,contacts})=>window.localPlayerHarness.setJob({id:'current',status:'succeeded',media:{source_video:{status:'available'}},result:{video,holds:[hold],attempt:{contacts},pose_samples:[]}}),{video,hold,contacts})
  await page.waitForFunction(()=>document.querySelector('video')?.readyState>=2)
  const pixel=()=>page.locator('canvas').evaluate(c=>[...c.getContext('2d').getImageData(384,99,1,1).data].slice(0,3))
  const seek=async time=>{await page.getByLabel('复盘视频进度',{exact:true}).fill(String(time));await page.waitForFunction(t=>{const v=document.querySelector('video');return !v.seeking&&Math.abs(v.currentTime-t)<.05},time)}
  const lit=await pixel();assert.deepEqual(lit,[80,196,235])
  await page.getByRole('button',{name:'播放复盘视频',exact:true}).click()
  await page.getByRole('button',{name:'暂停复盘视频',exact:true}).click()
  assert.equal(await page.locator('video').evaluate(v=>v.paused),true)
  await seek(1);assert.deepEqual(await pixel(),[14,16,15])
  await seek(.2);assert.deepEqual(await pixel(),lit)
  await seek(2.96);assert.deepEqual(await pixel(),[241,208,75])
  await seek(.2);assert.deepEqual(await pixel(),lit)
  await page.getByRole('button',{name:'导出',exact:true}).click()
  assert.equal(await page.getByRole('radio').count(),2)
  await page.getByRole('button',{name:'导出文件',exact:true}).click()
  assert.deepEqual(writes.map(x=>x.body),[{result_version:'fixed-current-v1',scope:'full',group_id:null,speed:.75}])
  assert.deepEqual(errors,[])
 }finally{await page.close()}
})
