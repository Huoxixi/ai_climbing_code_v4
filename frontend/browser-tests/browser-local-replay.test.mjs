import test,{after} from 'node:test'
import assert from 'node:assert/strict'
import {readFile,mkdir,writeFile} from 'node:fs/promises'
import {resolve} from 'node:path'
import {chromium} from '@playwright/test'
import {startFixtureServer} from './fixtures/server.mjs'

const base=await startFixtureServer(4318,process.env.CLIMB_BROWSER_BASE_URL)
const browser=await chromium.launch({headless:true})
after(()=>browser.close())
const fixtures=process.env.CLIMB_BROWSER_NATIVE_FIXTURES
const report={}
async function rejectServerApis(page){await page.route('**/api/**',route=>route.abort())}
test('browser page works without auth APIs, shows model errors and supports a narrow viewport',async()=>{
  const page=await browser.newPage({viewport:{width:390,height:844}}),requests=[]
  await rejectServerApis(page)
  page.on('request',r=>requests.push(r.url()))
  await page.route('**/browser-models/**/*.onnx',route=>route.fulfill({status:503,body:'unavailable'}))
  await page.goto(base+'/browser-replay.html')
  await page.getByRole('alert').waitFor({timeout:30000})
  assert.match(await page.getByRole('alert').innerText(),/503/)
  assert.equal(await page.getByRole('button',{name:'重新准备模型'}).isEnabled(),true)
  assert.ok(!requests.some(url=>url.includes('/api/')))
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth),true)
  await page.close()
})
test('actual native model: automatic initialization, cache reuse, local video and 133 point parity',{skip:!fixtures,timeout:240000},async()=>{
  const native=JSON.parse(await readFile(resolve(fixtures,'reference.json'),'utf8'))
  const context=await browser.newContext({acceptDownloads:true}),page=await context.newPage(),requests=[],modelRequests=[]
  await rejectServerApis(page)
  page.on('request',r=>{requests.push({url:r.url(),method:r.method()});if(r.url().endsWith('.onnx'))modelRequests.push(r.url())})
  const payload={}
  for(const name of ['frame.rgba','pose-input.f32','detector-input.f32'])payload[name]=await readFile(resolve(fixtures,name))
  await page.route('**/__validation/*',route=>route.fulfill({body:payload[new URL(route.request().url()).pathname.split('/').at(-1)]}))
  let started=Date.now()
  await page.goto(base+'/browser-replay.html')
  await page.getByRole('heading',{name:'本机模型已就绪'}).waitFor({timeout:90000})
  report.cold_start_seconds=(Date.now()-started)/1000;assert.equal(modelRequests.length,2)
  modelRequests.length=0;started=Date.now();await page.reload()
  await page.getByRole('heading',{name:'本机模型已就绪'}).waitFor({timeout:90000})
  report.warm_start_seconds=(Date.now()-started)/1000;assert.equal(modelRequests.length,0)
  // Same raw source pixels and same native bbox, independent of video decoding.
  const parity=await page.evaluate(async native=>{
    const {LocalPoseEngine}=await import('/src/browser-replay/localEngine.js')
    const {poseInput,detectorInput}=await import('/src/browser-replay/poseMath.js')
    const pixels=new Uint8ClampedArray(await(await fetch('/__validation/frame.rgba')).arrayBuffer())
    const frame=()=>({width:native.width,height:native.height,data:pixels.slice()})
    const compare=async(name,actual)=>{
      const expected=new Float32Array(await(await fetch('/__validation/'+name)).arrayBuffer())
      let max=0,total=0,changed=0
      for(let i=0;i<expected.length;i++){const d=Math.abs(expected[i]-actual[i]);max=Math.max(max,d);total+=d;if(d>1e-5)changed++}
      return {max,mean:total/expected.length,changed_fraction:changed/expected.length}
    }
    const inputs={pose:await compare('pose-input.f32',poseInput(frame(),native.box).data),detector:await compare('detector-input.f32',detectorInput(frame()).data)}
    const engine=new LocalPoseEngine();await engine.request('initialize',{forceCpu:true})
    const started=performance.now(),detections=await engine.infer('detect',frame()),pose=await engine.infer('pose-primary',frame(),native.box),seconds=(performance.now()-started)/1000
    engine.close();return {inputs,detections,pose,seconds}
  },native)
  const differences=parity.pose.points.map((p,i)=>Math.hypot((p[0]-native.points[i][0])*native.width,(p[1]-native.points[i][1])*native.height))
  report.parity={inputs:parity.inputs,detected_people:parity.detections.length,mean_point_pixels:differences.reduce((a,b)=>a+b)/133,max_point_pixels:Math.max(...differences),same_frame_inference_seconds:parity.seconds}
  assert.equal(parity.pose.points.length,133)
  assert.ok(report.parity.mean_point_pixels<1,JSON.stringify(report.parity))
  assert.ok(report.parity.max_point_pixels<5,JSON.stringify(report.parity))
  assert.equal(parity.detections.length,native.boxes.length)
  await page.locator('#video-file').setInputFiles(resolve(fixtures,'clip.mp4'))
  await page.getByRole('button',{name:'识别当前画面的人物',exact:true}).waitFor()
  await page.getByRole('button',{name:'识别当前画面的人物',exact:true}).click()
  await page.getByRole('button',{name:'人物 1',exact:true}).waitFor({timeout:30000})
  await page.getByRole('button',{name:'人物 1',exact:true}).click()
  await page.getByRole('button',{name:'开始本机分析',exact:true}).click()
  await page.getByText('本机分析完成',{exact:true}).waitFor({timeout:90000})
  const downloadPromise=page.waitForEvent('download')
  await page.getByRole('button',{name:'保存骨架数据'}).click()
  const download=await downloadPromise
  const result=JSON.parse(await readFile(await download.path(),'utf8'))
  assert.equal(result.complete,true);assert.equal(result.video_uploaded,false)
  assert.ok(result.pose_samples.filter(s=>s.observed).length>=2)
  assert.equal(result.pose_samples[0].wholebody.kpts_xy.length,133)
  assert.equal(result.pose_samples[0].wholebody.joint_eligibility.length,133)
  await page.getByRole('checkbox',{name:'真人',exact:true}).uncheck()
  assert.equal(await page.getByRole('button',{name:'播放',exact:true}).isEnabled(),true)
  await page.getByRole('button',{name:'播放',exact:true}).click()
  await page.getByRole('button',{name:'暂停',exact:true}).waitFor()
  report.video={samples:result.pose_samples.length,observed:result.pose_samples.filter(s=>s.observed).length,provider:result.provider}
  report.network={non_get:requests.filter(r=>r.method!=='GET').length,api:requests.filter(r=>r.url.includes('/api/')).length,external:requests.filter(r=>!r.url.startsWith(base)&&!r.url.startsWith('blob:')&&!r.url.startsWith('data:')).length}
  assert.deepEqual(report.network,{non_get:0,api:0,external:0})
  await page.screenshot({path:resolve(fixtures,'desktop.png'),fullPage:true})
  await page.setViewportSize({width:390,height:844})
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true)
  await page.screenshot({path:resolve(fixtures,'mobile.png'),fullPage:true})
  await page.getByRole('button',{name:'重新分析',exact:true}).click()
  await page.getByRole('button',{name:'停止计算',exact:true}).click()
  await page.getByRole('button',{name:'重新准备模型',exact:true}).waitFor()
  assert.equal(await page.getByText('本机分析完成',{exact:true}).count(),0)
  // A corrupted persistent entry must be replaced; the other model stays cached.
  await page.evaluate(async()=>{const cache=await caches.open('climbing-browser-models-v1');const key=(await cache.keys()).find(r=>r.url.endsWith('/detector.onnx'));await cache.put(key,new Response(new Uint8Array([1,2,3])))})
  modelRequests.length=0;await page.reload()
  await page.getByRole('heading',{name:'本机模型已就绪'}).waitFor({timeout:90000})
  assert.equal(modelRequests.length,1);assert.match(modelRequests[0],/detector.onnx$/)
  report.corrupt_cache_recovered=true;report.cancel_released_worker=true
  await writeFile(resolve(fixtures,'browser-report.json'),JSON.stringify(report,null,2))
  await context.close()
})
