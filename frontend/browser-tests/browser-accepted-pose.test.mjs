import test from 'node:test'
import assert from 'node:assert/strict'
import {readFile,writeFile} from 'node:fs/promises'
import {resolve} from 'node:path'
import {chromium} from '@playwright/test'
const fixtures=process.env.CLIMB_ACCEPTED_POSE_FIXTURES
test('fresh browser primary/rotated inference and continuous display agree with desktop 19.2',{skip:!fixtures,timeout:600000},async()=>{
  const reference=JSON.parse(await readFile(resolve(fixtures,'reference.json'),'utf8')),browser=await chromium.launch({headless:true})
  try{
    const page=await browser.newPage(),base=process.env.CLIMB_BROWSER_BASE_URL||'http://127.0.0.1:4187'
    await page.route('**/__accepted/*',async route=>{
      const name=new URL(route.request().url()).pathname.split('/').at(-1)
      if(name==='blank')return route.fulfill({contentType:'text/html',body:'<!doctype html><title>Local acceptance</title>'})
      assert.match(name,/^\d+-\d+\.rgba$/)
      await route.fulfill({body:await readFile(resolve(fixtures,name))})
    })
    await page.goto(base+'/__accepted/blank')
    const report=await page.evaluate(async ({reference,workerUrl})=>{
      let engine
      if(workerUrl){
        const worker=new Worker(workerUrl,{type:'module'}),pending=new Map();let id=0
        worker.onmessage=({data})=>{if(data.type==='progress')return;const p=pending.get(data.id);if(!p)return;pending.delete(data.id);data.type==='error'?p.reject(new Error(data.message)):p.resolve(data.result)}
        worker.onerror=e=>{for(const p of pending.values())p.reject(new Error(e.message));pending.clear()}
        const request=(type,data={},transfer=[])=>new Promise((resolve,reject)=>{const key=++id;pending.set(key,{resolve,reject});worker.postMessage({id:key,type,...data},transfer)})
        engine={request,infer:(type,image,box,metadata)=>request(type,{image,box,metadata},[image.data.buffer]),close:()=>worker.terminate()}
      }else{const {LocalPoseEngine}=await import('/src/browser-replay/localEngine.js');engine=new LocalPoseEngine()}
      await engine.request('initialize',{forceCpu:true})
      const report=[]
      try{
        for(const item of reference){
          await engine.request('reset-sequence');const frames=[],displays=new Map()
          for(const f of item.frames){
            const pixels=new Uint8ClampedArray(await(await fetch('/__accepted/'+f.file)).arrayBuffer())
            const result=await engine.infer('pose',{width:f.size[0],height:f.size[1],data:pixels},f.box,{time:f.time,index:f.index,track:1})
            if(result.previous_display)displays.set(result.previous_display.index,result.previous_display.payload)
            const errors=result.points.map((p,j)=>Math.hypot((p[0]-f.expected.points[j][0])*f.size[0],(p[1]-f.expected.points[j][1])*f.size[1]))
            const primaryErrors=result.primary_native.points.map((p,j)=>Math.hypot((p[0]-f.primary.points[j][0])*f.size[0],(p[1]-f.primary.points[j][1])*f.size[1]))
            frames.push({index:f.index,mean:errors.reduce((a,b)=>a+b)/133,max:Math.max(...errors),primaryMax:Math.max(...primaryErrors),selected:result.image_observation_refinement.selected_joints,expectedSelected:f.selected_joints})
          }
          const temporal=[]
          for(const f of item.frames){
            const expected=f.temporal_display?.updates||[],actual=displays.get(f.index)?.updates||[]
            for(const u of expected){const match=actual.find(a=>a.joint===u.joint);temporal.push({index:f.index,joint:u.joint,matched:!!match,distance:match?Math.hypot((match.xy[0]-u.xy[0])*f.size[0],(match.xy[1]-u.xy[1])*f.size[1]):null})}
          }
          report.push({case:item.case,frames,temporal,actual_temporal_frames:displays.size})
        }
        return report
      }finally{engine.close()}
    },{reference,workerUrl:process.env.CLIMB_ACCEPTED_POSE_WORKER_URL})
    await writeFile(resolve(fixtures,process.env.CLIMB_ACCEPTED_POSE_WORKER_URL?'compiled-browser-report.json':'browser-report.json'),JSON.stringify(report,null,2))
    for(const item of report)for(const frame of item.frames){
      assert.ok(frame.mean<1.5,JSON.stringify({case:item.case,...frame}))
      assert.ok(frame.max<8,JSON.stringify({case:item.case,...frame}))
      assert.deepEqual(frame.selected,frame.expectedSelected)
    }
    const compared=report.flatMap(r=>r.temporal)
    assert.ok(compared.length>0)
    for(const entry of compared){assert.equal(entry.matched,true,JSON.stringify(entry));assert.ok(entry.distance<1.5,JSON.stringify(entry))}
  }finally{await browser.close()}
})
