import test from 'node:test'
import assert from 'node:assert/strict'
import {readFile,writeFile} from 'node:fs/promises'
import {resolve} from 'node:path'
import {chromium} from '@playwright/test'

const base=process.env.CLIMB_BROWSER_COMPILED_URL,fixtures=process.env.CLIMB_BROWSER_NATIVE_FIXTURES
test('compiled website runs the shipped worker and reopens its locally saved analysis without models',{skip:!base||!fixtures,timeout:150000},async()=>{
  const browser=await chromium.launch({headless:true})
  try{
    const context=await browser.newContext({acceptDownloads:true}),page=await context.newPage(),requests=[]
    await page.route('**/api/**',route=>route.abort())
    page.on('request',r=>requests.push({url:r.url(),method:r.method()}))
    await page.goto(base+'/browser-replay.html')
    await page.getByRole('heading',{name:'本机模型已就绪'}).waitFor({timeout:90000})
    assert.equal(requests.filter(r=>r.url.endsWith('.onnx')).length,2)
    const cacheInitial=await page.evaluate(async()=>{const cache=await caches.open('climbing-browser-models-v1');return {keys:(await cache.keys()).map(k=>k.url),storage:await navigator.storage.estimate(),warning:!!document.querySelector('.notice')}})
    await page.locator('#video-file').setInputFiles(resolve(fixtures,'clip.mp4'))
    await page.getByRole('button',{name:'识别当前画面的人物',exact:true}).click()
    await page.getByRole('button',{name:'人物 1',exact:true}).waitFor({timeout:30000})
    await page.getByRole('button',{name:'人物 1',exact:true}).click()
    await page.getByRole('button',{name:'开始本机分析',exact:true}).click()
    await page.getByText('已保存到本机“我的记录”',{exact:true}).waitFor({timeout:90000})
    const dataDownload=page.waitForEvent('download')
    await page.getByRole('button',{name:'保存骨架数据',exact:true}).click()
    const result=JSON.parse(await readFile(await(await dataDownload).path(),'utf8'))
    assert.equal(result.complete,true)
    assert.equal(result.pose_samples.length,12)
    assert.ok(result.pose_samples.filter(s=>s.observed).length>=2)
    for(const [human,label]of [[true,'person'],[false,'skeleton']]){
      await page.getByRole('checkbox',{name:'真人',exact:true}).setChecked(human)
      const downloadPromise=page.waitForEvent('download')
      await page.getByRole('button',{name:'导出视频',exact:true}).click()
      const exported=await downloadPromise
      const extension=exported.suggestedFilename().split('.').at(-1)
      await exported.saveAs(resolve(fixtures,`compiled-${label}.${extension}`))
      const playback=await page.evaluate(async()=>{
        const video=document.createElement('video');video.muted=true;video.src=document.querySelector('.export-download').href
        await new Promise((resolve,reject)=>{video.onloadeddata=resolve;video.onerror=reject;video.load()})
        const result={duration:video.duration,width:video.videoWidth,height:video.videoHeight};video.removeAttribute('src');video.load();return result
      })
      assert.ok(Math.abs(playback.duration-1.2)<.05);assert.equal(playback.width,720);assert.equal(playback.height,1280)
    }
    const cacheAfterExport=await page.evaluate(async()=>{const cache=await caches.open('climbing-browser-models-v1');return {keys:(await cache.keys()).map(k=>k.url),storage:await navigator.storage.estimate(),warning:!!document.querySelector('.notice')}})
    await page.reload()
    await page.getByRole('heading',{name:'本机模型已就绪'}).waitFor({timeout:90000})
    assert.equal(requests.filter(r=>r.url.endsWith('.onnx')).length,2,'warm reload must use verified local cache '+JSON.stringify({cacheInitial,cacheAfterExport,models:requests.filter(r=>r.url.endsWith('.onnx'))}))
    await page.getByRole('button',{name:'我的记录',exact:true}).click()
    await page.getByRole('button',{name:'打开',exact:true}).click()
    await page.getByText('已保存的复盘',{exact:true}).waitFor()
    await page.getByRole('button',{name:'播放',exact:true}).click()
    await page.getByRole('button',{name:'暂停',exact:true}).waitFor()
    assert.equal(await page.locator('.intro').count(),0)
    assert.equal(requests.filter(r=>r.url.endsWith('.onnx')).length,2)
    assert.equal(requests.filter(r=>r.method!=='GET').length,0)
    assert.equal(requests.filter(r=>r.url.includes('/api/')).length,0)
    assert.equal(requests.filter(r=>!r.url.startsWith(base)&&!r.url.startsWith('blob:')&&!r.url.startsWith('data:')).length,0)
    await writeFile(resolve(fixtures,'compiled-report.json'),JSON.stringify({compiled_worker:true,samples:result.pose_samples.length,observed:result.pose_samples.filter(s=>s.observed).length,automatic_local_save:true,warm_cache:true,reopen_history:true,person_video_export:true,skeleton_video_export:true,media_uploads:0,external_requests:0},null,2))
    await context.close()
  }finally{await browser.close()}
})
