import {chromium} from '@playwright/test'
import test,{after} from 'node:test'
import assert from 'node:assert/strict'
import {startFixtureServer} from './fixtures/server.mjs'
const base=await startFixtureServer(4224)
const browser=await chromium.launch({headless:true})
after(()=>browser.close())
test('actual canvas shows simple supported feet and preserves original pixels',async()=>{
  const page=await browser.newPage()
  await page.goto(base)
  const result=await page.evaluate(async()=>{
    const {registeredDisplayPoses,drawAnalysisView,analysisFrame}=await import('/src/services/replayAnalysisView.js')
    const video={width:100,height:200,fps:10,frame_count:20}
    const source=document.createElement('canvas');source.width=100;source.height=200
    source.getContext('2d').fillStyle='rgb(30,40,50)';source.getContext('2d').fillRect(0,0,100,200)
    source.videoWidth=100;source.videoHeight=200
    const points=Array.from({length:17},()=>[.5,.3]);points[15]=[.5,.8];points[16]=[.7,.8]
    const whole=Array.from({length:133},()=>[.5,.3]);whole[17]=[.4,.83];whole[19]=[.53,.84]
    whole[20]=[.6,.83];whole[22]=[.73,.84]
    const sample={source_frame_id:0,time_seconds:0,observed:true,wall_alignment:'reference',
      wall_reference_transform:[[1,0,0],[0,1,0],[0,0,1]],kpts_xy:points,kpts_score:Array(17).fill(.9),
      wholebody:{schema:'coco-wholebody-133',coordinates:'source_image_normalized',kpts_xy:whole,kpts_score:Array(133).fill(.9)}}
    const canvas=document.createElement('canvas');canvas.width=200;canvas.height=200;const ctx=canvas.getContext('2d')
    const draw=()=>drawAnalysisView(ctx,source,analysisFrame(video),[],[],{pose_samples:registeredDisplayPoses({video,pose_samples:[sample]})},0)
    draw();const pixel=(x,y)=>[...ctx.getImageData(x,y,1,1).data]
    const shown=pixel(147,162),original=pixel(20,166)
    sample.wholebody.kpts_score[17]=0;draw();const absent=pixel(147,162)
    return {shown,original,absent,pointCount:registeredDisplayPoses({video,pose_samples:[sample]})[0].feet.kpts_xy.length}
  })
  assert.deepEqual(result.original,[30,40,50,255])
  assert.ok(result.shown[0]>100)
  assert.deepEqual(result.absent,[14,16,15,255])
  assert.equal(result.pointCount,6)
  await page.close()
})

