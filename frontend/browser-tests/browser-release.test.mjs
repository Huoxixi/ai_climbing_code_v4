import test from 'node:test'
import assert from 'node:assert/strict'
import {readFile} from 'node:fs/promises'
import {resolve} from 'node:path'
import {chromium} from '@playwright/test'

const base=process.env.CLIMB_BROWSER_PACKAGE_URL
const fixtures=process.env.CLIMB_BROWSER_NATIVE_FIXTURES
assert.ok(base&&fixtures,'Compiled release URL and public fixture directory are required')

test('production package loads its real worker/models and exports a local record without legacy APIs',{timeout:180000},async()=>{
  const browser=await chromium.launch({headless:true})
  try{
    const context=await browser.newContext({acceptDownloads:true}),page=await context.newPage(),requests=[]
    const clip=await readFile(resolve(fixtures,'clip.mp4')),native=JSON.parse(await readFile(resolve(fixtures,'reference.json'),'utf8'))
    await page.route('**/__fixtures/synthetic.mp4',route=>route.fulfill({body:clip,contentType:'video/mp4'}))
    page.on('request',r=>requests.push({url:r.url(),method:r.method()}))
    await page.goto(base+'/')
    await page.getByRole('heading',{name:'本机模型已就绪',exact:true}).waitFor({timeout:100000})
    assert.equal(requests.filter(r=>r.url.endsWith('.onnx')).length,2)
    assert.equal(await page.getByText(/登录|注册|邀请码|用户管理|AI 复盘/).count(),0)
    for(const width of [1280,390]){
      await page.setViewportSize({width,height:844})
      assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true)
    }
    await page.evaluate(async native=>{
      const video=await(await fetch('/__fixtures/synthetic.mp4')).blob()
      const db=await new Promise((resolve,reject)=>{const q=indexedDB.open('climbing-browser-history-v1',1);q.onsuccess=()=>resolve(q.result);q.onerror=()=>reject(q.error);q.onupgradeneeded=()=>{const d=q.result;const s=d.createObjectStore('records',{keyPath:['owner','id']});s.createIndex('owner','owner');d.createObjectStore('content',{keyPath:['owner','id']})}})
      const sample={observed:true,kpts_xy:native.points.slice(0,17),kpts_score:native.scores.slice(0,17),joint_eligibility:Array(17).fill(true)}
      const analysis={complete:true,start_seconds:.2,end_seconds:1.1,sample_fps:10,video:{width:720,height:1280,duration_seconds:1.2},pose_samples:Array.from({length:9},(_,i)=>({...sample,time_seconds:.2+i/10}))}
      const owner='0'.repeat(32),id='synthetic-release-check'
      await new Promise((resolve,reject)=>{const tx=db.transaction(['records','content'],'readwrite');tx.oncomplete=resolve;tx.onerror=()=>reject(tx.error);tx.objectStore('records').put({owner,id,name:'合成画面发布检查',created_at:Date.now(),duration:1.2,bytes:video.size,observed:9,samples:9});tx.objectStore('content').put({owner,id,video,analysis})})
      db.close()
    },native)
    await page.getByRole('button',{name:'我的记录',exact:true}).click()
    await page.getByRole('button',{name:'打开',exact:true}).click()
    await page.waitForFunction(()=>document.querySelector('video')?.readyState>=2)
    const modelRequests=requests.filter(r=>r.url.endsWith('.onnx')).length
    for(const human of [true,false]){
      await page.getByRole('checkbox',{name:'真人',exact:true}).setChecked(human)
      const downloading=page.waitForEvent('download')
      await page.getByRole('button',{name:'导出视频',exact:true}).click()
      const download=await downloading
      assert.match(download.suggestedFilename(),/\.(mp4|webm)$/)
      const bytes=await readFile(await download.path())
      assert.ok(bytes.length>1000)
      const metadata=await page.evaluate(async()=>{
        const video=document.createElement('video');video.muted=true;video.src=document.querySelector('.export-download').href
        await new Promise((resolve,reject)=>{video.onloadeddata=resolve;video.onerror=reject;video.load()})
        return {width:video.videoWidth,height:video.videoHeight,duration:video.duration}
      })
      assert.deepEqual([metadata.width,metadata.height],[720,1280])
      assert.ok(Math.abs(metadata.duration-.9)<.05)
    }
    assert.equal(requests.filter(r=>r.url.endsWith('.onnx')).length,modelRequests)
    assert.equal(requests.filter(r=>r.method!=='GET'||r.url.includes('/api/')).length,0)
    await context.close()
  }finally{await browser.close()}
})
