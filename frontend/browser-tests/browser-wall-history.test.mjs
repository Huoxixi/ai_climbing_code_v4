import test from 'node:test'
import assert from 'node:assert/strict'
import {chromium} from '@playwright/test'
import {readFile} from 'node:fs/promises'
import {resolve} from 'node:path'
const source=process.env.CLIMB_BROWSER_WALL_VIDEO,base=process.env.CLIMB_BROWSER_WALL_HISTORY_URL||'http://127.0.0.1:4317',evidence=resolve(process.env.CLIMB_BROWSER_WALL_EVIDENCE||'../.tmp/wall-replay-20261019')
test('saved real wall and actual poses render after asynchronous reopen with no model loading',{skip:!source,timeout:30000},async()=>{
  const analysis=JSON.parse(await readFile(resolve(evidence,'analysis.json'),'utf8')),clip=await readFile(source),background=await readFile(resolve(evidence,'chosen-background.png'))
  const browser=await chromium.launch({headless:true})
  try{
    const page=await browser.newPage({acceptDownloads:true,viewport:{width:1280,height:900}}),models=[]
    page.on('request',r=>{if(r.url().endsWith('.onnx'))models.push(r.url())})
    await page.route('**/*.onnx',r=>r.fulfill({status:503,body:'saved replay must not need models'}))
    await page.route('**/fixtures/video.mp4',r=>r.fulfill({body:clip,contentType:'video/mp4'}))
    await page.route('**/fixtures/background.png',r=>r.fulfill({body:background,contentType:'image/png'}))
    await page.goto(base+'/browser-replay.html')
    await page.evaluate(async analysis=>{
      const video=await(await fetch('/fixtures/video.mp4')).blob();analysis.wall_scene.image=await(await fetch('/fixtures/background.png')).blob()
      const db=await new Promise((resolve,reject)=>{const r=indexedDB.open('climbing-browser-history-v1',1);r.onupgradeneeded=()=>{const records=r.result.createObjectStore('records',{keyPath:['owner','id']});records.createIndex('owner','owner');r.result.createObjectStore('content',{keyPath:['owner','id']})};r.onsuccess=()=>resolve(r.result);r.onerror=()=>reject(r.error)})
      await new Promise((resolve,reject)=>{const tx=db.transaction(['records','content'],'readwrite'),owner='0'.repeat(32),id='wall-history-proof';tx.objectStore('records').put({owner,id,name:'V050真实墙面验收',kind:'replay',created_at:Date.now(),duration:27.9,bytes:video.size,observed:229,samples:229});tx.objectStore('content').put({owner,id,video,analysis});tx.oncomplete=resolve;tx.onabort=()=>reject(tx.error)});db.close()
    },analysis)
    const before=models.length
    await page.getByRole('button',{name:'我的记录',exact:true}).click();await page.getByRole('button',{name:'打开',exact:true}).click()
    await page.waitForFunction(()=>document.querySelector('video')?.readyState>=2&&!document.querySelector('video').seeking)
    await page.getByRole('checkbox',{name:'真人',exact:true}).uncheck();await page.locator('.playback-controls input').fill('20')
    await page.waitForFunction(()=>Math.abs(document.querySelector('video').currentTime-20)<.01&&!document.querySelector('video').seeking)
    const pixels=await page.evaluate(async()=>{
      const bitmap=await createImageBitmap(await(await fetch('/fixtures/background.png')).blob()),canvas=document.querySelector('.video-stage canvas'),ctx=canvas.getContext('2d'),reference=document.createElement('canvas');reference.width=canvas.width;reference.height=canvas.height;const r=reference.getContext('2d');r.drawImage(bitmap,0,0);bitmap.close();const a=ctx.getImageData(0,0,canvas.width,canvas.height).data,b=r.getImageData(0,0,canvas.width,canvas.height).data;let changed=0,yellow=0;for(let i=0;i<a.length;i+=4)if(Math.max(Math.abs(a[i]-b[i]),Math.abs(a[i+1]-b[i+1]),Math.abs(a[i+2]-b[i+2]))>30){changed++;if(a[i]>140&&a[i+1]>110&&a[i+2]<130)yellow++}return {changed:changed/(a.length/4),yellow}
    })
    assert.ok(pixels.changed>0&&pixels.changed<.05);assert.ok(pixels.yellow>100);assert.equal(models.length,before)
    await page.setViewportSize({width:390,height:844});await page.screenshot({path:resolve(evidence,'mobile-restored.png'),fullPage:true})
    assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth))
    const exported=page.waitForEvent('download');await page.getByRole('button',{name:'导出视频',exact:true}).click()
    await(await exported).saveAs(resolve(evidence,'V050-real-wall-skeleton-final.mp4'))
    assert.equal(models.length,before)
    console.log(JSON.stringify({restored_pixels:pixels,models_on_reopen:0}))
  }finally{await browser.close()}
})
