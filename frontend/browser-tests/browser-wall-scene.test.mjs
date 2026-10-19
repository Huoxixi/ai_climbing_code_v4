import test from 'node:test'
import assert from 'node:assert/strict'
import {chromium} from '@playwright/test'
import {mkdir,readFile,writeFile} from 'node:fs/promises'
import {resolve} from 'node:path'
import {startFixtureServer} from './fixtures/server.mjs'

const source=process.env.CLIMB_BROWSER_WALL_VIDEO
const evidence=resolve(process.env.CLIMB_BROWSER_WALL_EVIDENCE||'../.tmp/wall-replay-20261019')
test('real V050: detect an empty wall, align the climb, play, export and reopen without inference',{skip:!source,timeout:1800000},async()=>{
  await mkdir(evidence,{recursive:true})
  const base=await startFixtureServer(4353,process.env.CLIMB_BROWSER_WALL_URL,{args:['--config','vite.browser.config.js']})
  const browser=await chromium.launch({headless:true})
  try{
    const context=await browser.newContext({acceptDownloads:true,viewport:{width:1280,height:1000}}),page=await context.newPage(),requests=[],errors=[]
    page.on('request',r=>requests.push({url:r.url(),method:r.method()}));page.on('pageerror',e=>errors.push(e.message))
    await page.route('**/api/**',route=>route.abort())
    await page.goto(base+'/browser-replay.html')
    await page.getByRole('heading',{name:'本机模型已就绪'}).waitFor({timeout:360000})
    console.log('model ready')
    await page.locator('#video-file').setInputFiles(resolve(source))
    await page.waitForFunction(()=>document.querySelector('video')?.readyState>=2)
    await page.locator('.playback-controls input').fill('5')
    await page.waitForFunction(()=>Math.abs(document.querySelector('video').currentTime-5)<.01&&!document.querySelector('video').seeking)
    await page.getByRole('button',{name:'识别当前画面的人物',exact:true}).click()
    await page.getByRole('button',{name:'人物 1',exact:true}).click({timeout:30000})
    await page.getByRole('button',{name:'开始本机分析',exact:true}).click()
    // Poll for user-visible stages, retaining the last result if the run fails.
    const deadline=Date.now()+1500000
    let last=''
    while(Date.now()<deadline){
      const state=await page.locator('.analysis-status').innerText(),wall=await page.locator('.wall-controls').count()?await page.locator('.wall-controls').innerText():'',error=await page.locator('[role=alert]').allTextContents()
      const text=wall||state
      if(text!==last){console.log(text);last=text}
      if(error.length)throw new Error(error.join('\n'))
      if(wall.includes('无人背景：')&&!wall.includes('正在对齐'))break
      await new Promise(r=>setTimeout(r,5000))
    }
    await page.getByText(/无人背景：/).waitFor({timeout:1000})
    const downloading=page.waitForEvent('download')
    await page.getByRole('button',{name:'保存骨架数据',exact:true}).click()
    const analysis=JSON.parse(await readFile(await(await downloading).path(),'utf8'))
    await writeFile(resolve(evidence,'analysis.json'),JSON.stringify(analysis,null,2))
    const backgroundDownload=page.waitForEvent('download')
    await page.evaluate(async()=>{
      const db=await new Promise((resolve,reject)=>{const r=indexedDB.open('climbing-browser-history-v1',1);r.onsuccess=()=>resolve(r.result);r.onerror=()=>reject(r.error)})
      const records=await new Promise((resolve,reject)=>{const r=db.transaction('content').objectStore('content').getAll();r.onsuccess=()=>resolve(r.result);r.onerror=()=>reject(r.error)})
      const blob=records.find(r=>r.analysis?.wall_scene?.image)?.analysis.wall_scene.image;db.close()
      if(!blob)throw new Error('No persisted wall image')
      const a=document.createElement('a'),url=URL.createObjectURL(blob);a.href=url;a.download='chosen-background.png';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000)
    })
    await(await backgroundDownload).saveAs(resolve(evidence,'chosen-background.png'))
    await page.getByRole('checkbox',{name:'真人',exact:true}).uncheck()
    assert.equal(await page.getByLabel('骨架背景',{exact:true}).inputValue(),'wall')
    assert.equal(analysis.pose_samples.length,229);assert.equal(analysis.complete,true)
    assert.ok(analysis.pose_samples.filter(s=>s.observed).length>200)
    assert.ok(analysis.wall_scene.source_time_seconds<1.5)
    assert.ok(analysis.wall_scene.aligned>=analysis.wall_scene.observed*.95,JSON.stringify(analysis.wall_scene))
    for(const time of [8,14,20,27]){
      await page.locator('.playback-controls input').fill(String(time))
      await page.waitForFunction(t=>Math.abs(document.querySelector('video').currentTime-t)<.01&&!document.querySelector('video').seeking,time)
      await page.locator('.video-stage').screenshot({path:resolve(evidence,`preview-${time}.png`)})
    }
    await page.getByRole('button',{name:'播放',exact:true}).click()
    await page.getByRole('button',{name:'暂停',exact:true}).waitFor()
    await page.getByRole('button',{name:'暂停',exact:true}).click()
    console.log('preview passed; exporting')
    const videoDownload=page.waitForEvent('download',{timeout:180000})
    await page.getByRole('button',{name:'导出视频',exact:true}).click()
    const exported=await videoDownload,extension=exported.suggestedFilename().split('.').at(-1),output=resolve(evidence,'V050-real-wall-skeleton.'+extension)
    await exported.saveAs(output)
    const playback=await page.evaluate(async()=>{
      const video=document.createElement('video');video.muted=true;video.src=document.querySelector('.export-download').href
      await new Promise((r,j)=>{video.onloadeddata=r;video.onerror=j;video.load()})
      const result={width:video.videoWidth,height:video.videoHeight,duration:video.duration};video.removeAttribute('src');video.load();return result
    })
    assert.equal(playback.width,720);assert.equal(playback.height,1280);assert.ok(Math.abs(playback.duration-22.9)<.05)
    // Manual selection must reject a person and retain the previous good scene.
    await page.locator('.playback-controls input').fill('10')
    await page.waitForFunction(()=>Math.abs(document.querySelector('video').currentTime-10)<.01&&!document.querySelector('video').seeking)
    await page.getByRole('button',{name:'使用当前帧作为背景',exact:true}).click()
    await page.getByText('这一帧检测到人物，请选择无人画面。',{exact:true}).waitFor({timeout:30000})
    assert.equal(await page.getByLabel('骨架背景',{exact:true}).inputValue(),'wall')
    assert.equal(await page.locator('.export-download').count(),0)
    const countBefore=requests.filter(r=>r.url.endsWith('.onnx')).length
    await page.getByRole('button',{name:'我的记录',exact:true}).click();await page.getByRole('button',{name:'打开',exact:true}).click()
    await page.getByRole('checkbox',{name:'真人',exact:true}).uncheck()
    await page.getByText(/无人背景：/).waitFor()
    assert.equal(requests.filter(r=>r.url.endsWith('.onnx')).length,countBefore,'reopen must reuse the saved background and poses')
    await page.locator('.playback-controls input').fill('14');await page.locator('.video-stage').screenshot({path:resolve(evidence,'reopened.png')})
    await page.setViewportSize({width:390,height:844});await page.screenshot({path:resolve(evidence,'mobile.png'),fullPage:true})
    assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth))
    assert.equal(requests.filter(r=>r.method!=='GET'||r.url.includes('/api/')).length,0)
    assert.equal(requests.filter(r=>!r.url.startsWith(base)&&!r.url.startsWith('blob:')&&!r.url.startsWith('data:')).length,0)
    assert.deepEqual(errors,[])
    const report={source:source.split(/[\\/]/).at(-1),start:5,end:27.9,samples:analysis.pose_samples.length,observed:analysis.wall_scene.observed,aligned:analysis.wall_scene.aligned,background_time:analysis.wall_scene.source_time_seconds,background_quality:analysis.wall_scene.quality,playback,output,manual_person_rejected:true,reopened_without_inference:true,media_uploads:0,external_requests:0,errors}
    await writeFile(resolve(evidence,'browser-report.json'),JSON.stringify(report,null,2));console.log(JSON.stringify(report))
    await context.close()
  }finally{await browser.close()}
})
