import test,{after} from 'node:test'
import assert from 'node:assert/strict'
import {readFile,mkdir,writeFile} from 'node:fs/promises'
import {resolve} from 'node:path'
import {fileURLToPath} from 'node:url'
import {chromium} from '@playwright/test'
import {existsSync} from 'node:fs'
import {execFileSync} from 'node:child_process'
import {startFixtureServer} from './fixtures/server.mjs'

const root=fileURLToPath(new URL('../../',import.meta.url)),fixtures=process.env.CLIMB_BROWSER_NATIVE_FIXTURES||resolve(root,'.tmp/browser-local-replay-20261017'),evidence=resolve(root,'.tmp/browser-video-export-20261018')
await mkdir(evidence,{recursive:true})
const base=await startFixtureServer(4337,process.env.CLIMB_BROWSER_EXPORT_URL,{args:['--config','vite.browser.config.js']})
const browser=await chromium.launch({headless:true})
after(()=>browser.close())
const native=JSON.parse(await readFile(resolve(fixtures,'reference.json'),'utf8')),clip=await readFile(resolve(fixtures,'clip.mp4'))
const report={}
const ffmpeg=process.env.CLIMB_BROWSER_FFMPEG||resolve(root,'../../.tools/boulder-python/imageio_ffmpeg/binaries/ffmpeg-win-x86_64-v7.1.exe')
function independentlyDecode(path){
  if(!existsSync(ffmpeg))return null
  const output=execFileSync(ffmpeg,['-nostdin','-v','error','-progress','pipe:1','-nostats','-i',path,'-f','null','-'],{windowsHide:true,encoding:'utf8'})
  const frames=Number([...output.matchAll(/^frame=(\d+)/gm)].at(-1)[1]),duration=Number([...output.matchAll(/^out_time_us=(\d+)/gm)].at(-1)[1])/1e6
  assert.equal(frames,27,'a floating-point time boundary must not create a duplicate final frame');assert.ok(Math.abs(duration-.9)<.001)
  return {frames,duration}
}
async function fixturePage(){
  const context=await browser.newContext({acceptDownloads:true}),page=await context.newPage(),requests=[]
  await page.route('**/api/**',route=>route.abort())
  await page.route('**/browser-models/**/*.onnx',route=>route.fulfill({status:503,body:'history exports must not need model initialization'}))
  await page.route('**/__fixtures/clip.mp4',route=>route.fulfill({body:clip,contentType:'video/mp4'}))
  page.on('request',r=>requests.push({url:r.url(),method:r.method()}))
  await page.goto(base+'/browser-replay.html')
  await page.getByRole('heading',{name:'视频复盘',exact:true}).waitFor()
  await page.evaluate(async native=>{
    const {saveReplay,LOCAL_HISTORY_OWNER}=await import('/src/browser-replay/localHistory.js'),video=await(await fetch('/__fixtures/clip.mp4')).blob()
    const sample={observed:true,kpts_xy:native.points.slice(0,17),kpts_score:native.scores.slice(0,17),joint_eligibility:native.points.slice(0,17).map((p,i)=>native.scores[i]>=.5&&p.every(v=>v>0&&v<1))}
    const analysis={complete:true,start_seconds:.2,end_seconds:1.1,sample_fps:10,video:{width:native.width,height:native.height,duration_seconds:1.2},pose_samples:Array.from({length:9},(_,i)=>({...sample,time_seconds:.2+i/10}))}
    await saveReplay(LOCAL_HISTORY_OWNER,{name:'导出验收片段',video,analysis})
  },native)
  await page.getByRole('button',{name:'我的记录',exact:true}).click()
  await page.getByRole('button',{name:'打开',exact:true}).click()
  await page.getByRole('button',{name:'导出视频',exact:true}).waitFor()
  await page.waitForFunction(()=>document.querySelector('video')?.readyState>=2)
  return {context,page,requests}
}
async function inspectExport(page){
  return page.evaluate(async()=>{
    const link=document.querySelector('.export-download'),video=document.createElement('video');video.muted=true;video.src=link.href
    await new Promise((resolve,reject)=>{video.onloadeddata=resolve;video.onerror=()=>reject(new Error('exported file cannot play'));video.load()})
    video.currentTime=Math.min(.45,video.duration/2);await new Promise(resolve=>video.onseeked=resolve)
    const canvas=document.createElement('canvas');canvas.width=video.videoWidth;canvas.height=video.videoHeight
    const ctx=canvas.getContext('2d',{willReadFrequently:true});ctx.drawImage(video,0,0)
    const pixels=ctx.getImageData(0,0,canvas.width,canvas.height).data;let total=0,yellow=0
    for(let i=0;i<pixels.length;i+=4){total+=(pixels[i]+pixels[i+1]+pixels[i+2])/3;if(pixels[i]>140&&pixels[i+1]>110&&pixels[i+2]<130)yellow++}
    const stats={duration:video.duration,width:video.videoWidth,height:video.videoHeight,mean:total/(pixels.length/4),yellow,seekable:video.seekable.length>0,filename:link.download}
    video.removeAttribute('src');video.load();return stats
  })
}

test('saved replay exports playable person+skeleton and pure skeleton files locally without models',{timeout:90000},async()=>{
  const {context,page,requests}=await fixturePage(),afterHistory=requests.length
  const first=page.waitForEvent('download');await page.getByRole('button',{name:'导出视频',exact:true}).click()
  const personDownload=await first,personPath=resolve(evidence,'person.'+personDownload.suggestedFilename().split('.').at(-1));await personDownload.saveAs(personPath);report.independent_person_decode=independentlyDecode(personPath)
  report.person=await inspectExport(page)
  assert.ok(Math.abs(report.person.duration-.9)<.05,JSON.stringify(report.person));assert.equal(report.person.width,720);assert.equal(report.person.height,1280);assert.ok(report.person.mean>45);assert.equal(report.person.seekable,true)
  await page.getByRole('checkbox',{name:'真人',exact:true}).uncheck()
  assert.equal(await page.locator('.export-download').count(),0,'changing the picture mode invalidates the previous download')
  const second=page.waitForEvent('download');await page.getByRole('button',{name:'导出视频',exact:true}).click()
  const skeletonDownload=await second,skeletonPath=resolve(evidence,'skeleton.'+skeletonDownload.suggestedFilename().split('.').at(-1));await skeletonDownload.saveAs(skeletonPath);report.independent_skeleton_decode=independentlyDecode(skeletonPath)
  report.skeleton=await inspectExport(page)
  assert.ok(Math.abs(report.skeleton.duration-.9)<.05);assert.ok(report.skeleton.mean<35);assert.ok(report.skeleton.yellow>100);assert.match(report.skeleton.filename,/纯骨架/)
  assert.equal(requests.slice(afterHistory).filter(r=>r.url.endsWith('.onnx')).length,0)
  assert.equal(requests.filter(r=>r.method!=='GET'||r.url.includes('/api/')).length,0)
  await page.evaluate(()=>{window.scrollTo(0,0);return document.fonts.ready})
  await page.setViewportSize({width:1280,height:800});await page.screenshot({path:resolve(evidence,'desktop.png'),fullPage:true})
  await page.setViewportSize({width:390,height:844});await page.screenshot({path:resolve(evidence,'mobile.png'),fullPage:true})
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true)
  await page.getByRole('checkbox',{name:'骨架',exact:true}).uncheck();assert.equal(await page.getByRole('button',{name:'导出视频',exact:true}).isDisabled(),true)
  report.network={uploads:0,account_requests:0,model_requests_during_export:0};await writeFile(resolve(evidence,'report.json'),JSON.stringify(report,null,2))
  await context.close()
})

test('cancel and missing WebCodecs leave records reusable and allow retry',{timeout:45000},async()=>{
  const {context,page}=await fixturePage()
  const previousDownload=page.waitForEvent('download');await page.getByRole('button',{name:'导出视频',exact:true}).click();await previousDownload
  await page.getByRole('button',{name:'导出视频',exact:true}).click()
  await page.getByRole('button',{name:'取消导出',exact:true}).click()
  await page.getByText('已取消导出，原视频和本机记录保留。',{exact:true}).waitFor()
  assert.equal(await page.locator('.export-download').count(),0,'a canceled export must not display a stale download')
  const result=await page.evaluate(async()=>{
    const {exportReplayVideo}=await import('/src/browser-replay/videoExport.js'),{listLocalHistory,readHistory}=await import('/src/browser-replay/localHistory.js')
    const [meta]=await listLocalHistory(),record=await readHistory(meta.owner,meta.id),before=JSON.stringify(record.analysis)
    const controller=new AbortController();let canceled=false,unsupported=false
    try{await exportReplayVideo({file:record.video,analysis:record.analysis,signal:controller.signal,onProgress:s=>{if(s.stage==='encoding')controller.abort(new DOMException('test cancel','AbortError'))}})}catch(e){canceled=e.name==='AbortError'}
    const encoder=window.VideoEncoder;try{window.VideoEncoder=undefined;await exportReplayVideo({file:record.video,analysis:record.analysis})}catch(e){unsupported=/当前浏览器不支持/.test(e.message)}finally{window.VideoEncoder=encoder}
    return {canceled,unsupported,unchanged:before===JSON.stringify((await readHistory(meta.owner,meta.id)).analysis)}
  })
  assert.deepEqual(result,{canceled:true,unsupported:true,unchanged:true})
  const downloading=page.waitForEvent('download');await page.getByRole('button',{name:'导出视频',exact:true}).click();await downloading
  await context.close()
})

test('a device without H264 encoding falls back to a playable WebM file',{timeout:45000},async()=>{
  const {context,page}=await fixturePage()
  await page.evaluate(()=>{const original=VideoEncoder.isConfigSupported.bind(VideoEncoder);VideoEncoder.isConfigSupported=config=>config.codec.startsWith('avc')?Promise.resolve({supported:false,config}):original(config)})
  await page.getByRole('checkbox',{name:'真人',exact:true}).uncheck()
  const downloading=page.waitForEvent('download');await page.getByRole('button',{name:'导出视频',exact:true}).click()
  const download=await downloading;assert.match(download.suggestedFilename(),/\.webm$/)
  const stats=await inspectExport(page);assert.ok(Math.abs(stats.duration-.9)<.05);assert.ok(stats.yellow>100);assert.ok(stats.mean<35)
  await download.saveAs(resolve(evidence,'fallback.webm'))
  independentlyDecode(resolve(evidence,'fallback.webm'))
  await context.close()
})
