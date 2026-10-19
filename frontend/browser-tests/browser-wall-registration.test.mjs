import test,{after} from 'node:test'
import assert from 'node:assert/strict'
import {chromium} from '@playwright/test'
import {startFixtureServer} from './fixtures/server.mjs'
const base=await startFixtureServer(4355,process.env.CLIMB_BROWSER_REGISTRATION_URL,{args:['--config','vite.browser.config.js']})
const browser=await chromium.launch({headless:true})
after(()=>browser.close())
test('wall alignment follows a known camera transform, excludes a person and rejects unrelated shots',{timeout:90000},async()=>{
  const page=await browser.newPage()
  await page.route('**/*.onnx',r=>r.fulfill({status:503,body:'not used'}))
  await page.goto(base+'/browser-replay.html')
  const result=await page.evaluate(async workerUrl=>{
    const worker=new Worker(new URL(workerUrl,location.href),{type:'module'})
    let id=0
    const request=(type,canvas,boxes=[])=>new Promise((resolve,reject)=>{
      const timer=setTimeout(()=>reject(new Error('registration timeout')),45000)
      worker.onmessage=e=>{clearTimeout(timer);e.data.error?reject(new Error(e.data.error)):resolve(e.data.result)};worker.onerror=e=>{clearTimeout(timer);reject(new Error(e.message))}
      const image=canvas.getContext('2d').getImageData(0,0,canvas.width,canvas.height)
      worker.postMessage({id:++id,type,image,boxes},[image.data.buffer])
    })
    const make=()=>{const c=document.createElement('canvas');c.width=540;c.height=960;return c}
    const reference=make(),ctx=reference.getContext('2d');ctx.fillStyle='#ccbca6';ctx.fillRect(0,0,540,960)
    let seed=42
    const random=()=>{seed=(Math.imul(seed,1664525)+1013904223)>>>0;return seed/2**32}
    for(let i=0;i<1800;i++){const x=random()*540,y=random()*960;ctx.fillStyle=`rgb(${Math.floor(random()*240)},${Math.floor(random()*240)},${Math.floor(random()*240)})`;ctx.beginPath();ctx.arc(x,y,2+random()*9,0,Math.PI*2);ctx.fill();ctx.strokeStyle='#34302a';ctx.stroke()}
    const moved=make(),m=moved.getContext('2d');m.fillStyle='#000';m.fillRect(0,0,540,960);m.setTransform(1.02,.006,-.004,1.02,4,-6);m.drawImage(reference,0,0)
    const inverse=m.getTransform().inverse();m.resetTransform();m.fillStyle='#101040';m.fillRect(200,230,140,500)
    for(let i=0;i<80;i++){m.fillStyle=i%2?'#fafafa':'#c03060';m.fillRect(205+i%8*16,235+Math.floor(i/8)*45,10,20)}
    const unrelated=make(),u=unrelated.getContext('2d');u.fillStyle='#fff';u.fillRect(0,0,540,960)
    try{
      const quality=await request('reference',reference),aligned=await request('register',moved,[[200/540,230/960,340/540,730/960]]),rejected=await request('register',unrelated)
      const errors=[[.2,.2],[.8,.2],[.2,.8],[.8,.8]].map(([x,y])=>{
        const p=inverse.transformPoint({x:x*540,y:y*960}),h=aligned.matrix,d=h[6]*x+h[7]*y+h[8]
        return Math.hypot((h[0]*x+h[1]*y+h[2])/d*540-p.x,(h[3]*x+h[4]*y+h[5])/d*960-p.y)
      })
      return {quality,aligned,rejected,errors}
    }finally{worker.terminate()}
  },process.env.CLIMB_BROWSER_REGISTRATION_WORKER||'/src/browser-replay/wall.worker.js')
  assert.equal(result.aligned.valid,true,JSON.stringify(result));assert.ok(Math.max(...result.errors)<3,JSON.stringify(result.errors))
  assert.equal(result.rejected.valid,false);assert.ok(!result.rejected.matrix)
  await page.close()
})
