import test,{after} from 'node:test'
import assert from 'node:assert/strict'
import {chromium} from '@playwright/test'
import {startFixtureServer} from './fixtures/server.mjs'
import {organized,syntheticMedia} from './fixtures/actions.mjs'
const base=await startFixtureServer(4197)
const browser=await chromium.launch({headless:true})
const media=await syntheticMedia(browser)
after(()=>browser.close())
const geometry={width:640,height:360,fps:24,frame_count:192,duration_seconds:8}
const pointSet=Array.from({length:17},(_,i)=>[.35+(i%2)*.15,.2+i*.025])
const poses=Array.from({length:17},(_,i)=>({source_frame_id:i*12,time_seconds:i/2,observed:true,kpts_xy:pointSet,
  source_kpts_xy:pointSet,kpts_score:Array(17).fill(.9)}))

async function fixture(width=1280,backgroundStatus='ready'){
  const page=await browser.newPage({viewport:{width,height:900}})
  const png=await page.evaluate(()=>{const c=document.createElement('canvas');c.width=640;c.height=360;const ctx=c.getContext('2d');ctx.fillStyle='#506040';ctx.fillRect(0,0,640,360);return Array.from(Uint8Array.from(atob(c.toDataURL().split(',')[1]),ch=>ch.charCodeAt(0)))})
  const state={task:{status:'succeeded'},result_version:'prepared',export:{status:'idle'},result:{...structuredClone(organized),
    replay_visualization:{version:'registered-observation-limb-labels-v14',video:geometry,pose_samples:poses,contacts:[],center_of_mass_trajectory:{segments:[]}}},
    background:backgroundStatus==='ready'?{status:'ready',binding:'bg-v1',reference_to_background:[[1,0,0],[0,1,0],[0,0,1]]}:
      {status:'unavailable',reason:'no_empty_frame',message:'未找到可靠的无人画面，不能单独显示真实场景骨架。'}}
  const writes=[],errors=[]
  page.on('pageerror',error=>errors.push(error.message))
  await page.route('**/api/climb-replay/**',async route=>{
    const req=route.request(),url=new URL(req.url())
    if(url.pathname.endsWith('/source-video')){
      const range=req.headers().range
      if(range){const match=/bytes=(\d+)-(\d*)/.exec(range),start=Number(match?.[1]||0),end=match?.[2]?Math.min(Number(match[2]),media.length-1):media.length-1
        return route.fulfill({status:206,body:media.subarray(start,end+1),contentType:'video/webm',headers:{'Accept-Ranges':'bytes','Content-Range':`bytes ${start}-${end}/${media.length}`}})}
      return route.fulfill({body:media,contentType:'video/webm',headers:{'Accept-Ranges':'bytes'}})
    }
    if(url.pathname.endsWith('/background'))return route.fulfill({body:Buffer.from(png),contentType:'image/png'})
    if(url.pathname.endsWith('/export')&&req.method()==='POST'){
      const payload=req.postDataJSON();writes.push(payload)
      // Return the same id on cache hits to verify repeated downloads still work.
      state.export_media={...payload,id:JSON.stringify(payload)};state.export={status:'succeeded'}
    }
    if(url.pathname.endsWith('/media')||url.pathname.endsWith('/package'))return route.fulfill({body:Buffer.from('constructed-file'),contentType:url.pathname.endsWith('/package')?'application/zip':'video/mp4',headers:{'Content-Disposition':'attachment; filename='+ (url.pathname.endsWith('/package')?'climb-replay-package.zip':'climb-replay.mp4')}})
    return route.fulfill({json:state})
  })
  await page.goto(base+'/e2e/local-player-harness.html')
  const job={id:'composed',status:'succeeded',media:{source_video:{status:'available'}},result:{video:geometry,holds:[]}}
  await page.evaluate(job=>window.localPlayerHarness.setJob(job),job)
  await page.getByRole('group',{name:'画面内容',exact:true}).waitFor()
  if(backgroundStatus==='ready')await page.getByText('正在载入无人背景…',{exact:true}).waitFor({state:'hidden'})
  return {page,state,writes,errors,job}
}

for(const width of [1280,390])test(`seven pictures, live position and independent export at ${width}px`,async()=>{
  const {page,writes,errors}=await fixture(width)
  try{
    const choices=page.getByRole('group',{name:'画面内容',exact:true})
    const skeleton=choices.getByRole('checkbox',{name:'骨架',exact:true}),human=choices.getByRole('checkbox',{name:'真人',exact:true}),diagram=choices.getByRole('checkbox',{name:'动作示意图',exact:true})
    assert.equal(await skeleton.isChecked(),false);assert.equal(await human.isChecked(),true);assert.equal(await diagram.isChecked(),true)
    assert.equal(await choices.getByRole('checkbox',{name:'资料',exact:true}).count(),0)
    await page.waitForFunction(()=>document.querySelector('video')?.readyState>=2)
    await page.locator('video').evaluate(async video=>{video.pause();const seeked=new Promise(resolve=>video.addEventListener('seeked',resolve,{once:true}));video.currentTime=1;video.playbackRate=.5;await seeked})
    const initial=await page.locator('video').evaluate(v=>({time:v.currentTime,rate:v.playbackRate,paused:v.paused}))
    assert.equal(initial.time,1,JSON.stringify(await page.locator('video').evaluate(v=>({time:v.currentTime,duration:v.duration,seekable:v.seekable.length,buffered:v.buffered.length}))))
    for(const [sk,hu,di] of [[true,true,true],[true,true,false],[true,false,false],[true,false,true],[false,false,true],[false,true,true],[false,true,false]]){
      // Enable additions first, so no transition passes through zero pictures.
      for(const [locator,on] of [[skeleton,sk],[human,hu],[diagram,di]])if(on)await locator.check()
      for(const [locator,on] of [[skeleton,sk],[human,hu],[diagram,di]])if(!on)await locator.uncheck()
      const attributes=await page.locator('canvas').evaluate(c=>({width:c.width,height:c.height}))
      assert.deepEqual(attributes,{width:640*(Number(sk||hu)+Number(di)),height:360})
      const playback=await page.locator('video').evaluate(v=>({time:v.currentTime,rate:v.playbackRate,paused:v.paused}))
      assert.equal(playback.time,1);assert.equal(playback.rate,.5);assert.equal(playback.paused,true)
    }
    assert.equal(await human.isDisabled(),true)
    assert.equal(writes.length,0)
    await page.getByRole('button',{name:'导出',exact:true}).click()
    const sheet=page.getByRole('dialog',{name:'导出复盘',exact:true})
    const exports=sheet.getByRole('group',{name:'导出内容',exact:true})
    assert.equal(await exports.getByRole('checkbox').count(),4)
    await exports.getByRole('checkbox',{name:'真人',exact:true}).uncheck()
    assert.equal(await sheet.getByRole('button',{name:'导出文件',exact:true}).isDisabled(),true)
    await exports.getByRole('checkbox',{name:'资料',exact:true}).check()
    assert.equal(await human.isChecked(),true)
    for(let repeat=0;repeat<2;repeat++){
      const download=page.waitForEvent('download')
      await sheet.getByRole('button',{name:'导出文件',exact:true}).click()
      assert.equal((await download).suggestedFilename(),'climb-replay-package.zip')
    }
    assert.equal(writes.length,2)
    assert.equal(writes[0].show_human,false);assert.equal(writes[0].include_data,true)
    const link=sheet.getByRole('link',{name:'下载资料包',exact:true})
    assert.match(await link.getAttribute('href'),/data_only=true/)
    assert.match(await link.getAttribute('href'),/export_id=/)
    await exports.getByRole('checkbox',{name:'动作示意图',exact:true}).check()
    assert.equal(await sheet.getByRole('link').count(),0)
    await page.screenshot({path:`.tmp-replay-composition-${width}.png`,fullPage:true})
    assert.deepEqual(errors,[])
    const overflow=await page.evaluate(()=>document.documentElement.scrollWidth>window.innerWidth)
    assert.equal(overflow,false)
  }finally{await page.close()}
})

test('unavailable background blocks only invalid combinations; controls disappear before success',async()=>{
  const {page,job,errors}=await fixture(1280,'unavailable')
  try{
    const choices=page.getByRole('group',{name:'画面内容',exact:true})
    await choices.getByRole('checkbox',{name:'骨架',exact:true}).check()
    assert.equal(await choices.getByRole('checkbox',{name:'真人',exact:true}).isDisabled(),true)
    await choices.getByRole('checkbox',{name:'骨架',exact:true}).uncheck()
    await choices.getByRole('checkbox',{name:'真人',exact:true}).uncheck()
    assert.equal(await choices.getByRole('checkbox',{name:'骨架',exact:true}).isDisabled(),true)
    assert.equal(await choices.getByRole('checkbox',{name:'动作示意图',exact:true}).isDisabled(),true)
    await page.evaluate(job=>window.localPlayerHarness.setJob({...job,status:'running'}),job)
    await choices.waitFor({state:'hidden'})
    assert.deepEqual(errors,[])
  }finally{await page.close()}
})

test('switching during playback, seeking and fullscreen keep one source timeline',async()=>{
  const {page,errors}=await fixture()
  try{
    await page.getByLabel('播放速度',{exact:true}).selectOption('0.5')
    await page.getByRole('button',{name:'播放复盘视频',exact:true}).click()
    await page.waitForFunction(()=>document.querySelector('video')?.currentTime>.2)
    const before=await page.locator('video').evaluate(v=>v.currentTime)
    const choices=page.getByRole('group',{name:'画面内容',exact:true})
    await choices.getByRole('checkbox',{name:'骨架',exact:true}).check()
    await choices.getByRole('checkbox',{name:'真人',exact:true}).uncheck()
    const playing=await page.locator('video').evaluate(v=>({time:v.currentTime,paused:v.paused,rate:v.playbackRate}))
    assert.equal(playing.paused,false);assert.equal(playing.rate,.5);assert.ok(playing.time>=before)
    await page.getByRole('slider',{name:'复盘视频进度',exact:true}).evaluate(input=>{input.value='2.5';input.dispatchEvent(new Event('input',{bubbles:true}))})
    await page.waitForFunction(()=>{const v=document.querySelector('video');return !v.seeking && v.currentTime>=2.49})
    await page.getByRole('button',{name:'全屏复盘',exact:true}).click()
    await page.waitForFunction(()=>document.fullscreenElement?.classList.contains('replay-view'))
    assert.equal(await choices.isVisible(),true)
    await choices.getByRole('checkbox',{name:'动作示意图',exact:true}).uncheck()
    assert.equal(await page.locator('canvas').getAttribute('width'),'640')
    assert.equal(await page.locator('video').evaluate(v=>v.paused),false)
    await page.evaluate(()=>document.exitFullscreen())
    assert.deepEqual(errors,[])
  }finally{await page.close()}
})
