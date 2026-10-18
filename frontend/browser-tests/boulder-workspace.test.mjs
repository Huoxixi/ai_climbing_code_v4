import test, { after } from 'node:test'
import assert from 'node:assert/strict'
import { chromium } from '@playwright/test'
import { mkdir, writeFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'
import { startFixtureServer } from './fixtures/server.mjs'
import { organized, syntheticMedia } from './fixtures/actions.mjs'
import { replayFileAction, revealTool } from './fixtures/panels.mjs'

const base = await startFixtureServer(4230, process.env.BOULDER_TEST_URL)
const browser = await chromium.launch({ headless: true })
const media = await syntheticMedia(browser)
const portraitMedia = await syntheticMedia(browser,{width:360,height:640})
after(() => browser.close())
const captures = new URL('../../.impeccable/review/', import.meta.url)
await mkdir(captures, { recursive: true })
const board = { id:'constructed-wall', version:1, width:600, height:800, original_asset:{filename:'wall.svg'}, objects:[
  {id:'hold-1',color_group:'黄色',object_version:1,contour:[[100,100],[150,95],[165,140],[115,155]]},
  {id:'hold-2',color_group:'黄色',object_version:1,contour:[[320,280],[365,270],[380,315],[335,330]]},
] }
const records = Array.from({length:7},(_,i)=>({id:`record-${i}`,board_version_id:board.id,version:1,name:i===2?'构造长名称线路 · '.repeat(12):`构造线路 ${i+1}`,color_group:'黄色',difficulty:'V2',status:'completed',created_at:'2026-10-01T00:00:00Z',notes:'',setter:'',members:board.objects.map(o=>({object_id:o.id,roles:[],tags:[],note:''})),media:[]}))
const wall = '<svg xmlns="http://www.w3.org/2000/svg" width="600" height="800"><rect width="600" height="800" fill="#bcbfb9"/><path d="M0 220L600 120M160 0L260 800M0 600L600 490" stroke="#969c94" stroke-width="2"/><path d="M100 100L150 95L165 140L115 155Z M320 280L365 270L380 315L335 330Z" fill="#ebbe2c"/><path d="M210 420L265 420L250 465L210 455Z M420 610L460 600L475 645L430 660Z" fill="#4384a9"/><text x="28" y="766" fill="#39423b" font-size="20">构造素材 · 布局与交互验收</text></svg>'

async function setup(size, options={}) {
  const page = await browser.newPage({viewport:size})
  const playbackMedia = options.portrait ? portraitMedia : media
  if(options.desktop ?? (process.env.BOULDER_DESKTOP === '1'))await page.addInitScript(()=>{window.__AI_CLIMBING_DESKTOP__=true})
  page.setDefaultTimeout(5000)
  const errors=[], writes=[]
  let savedRecord=structuredClone(records[0]), notesFail=Boolean(options.workflow)
  let mediaBytes=0
  let photo = {id:'session',version:1,flow_version:3,status:'awaiting_color',board:structuredClone(board),colors:[],color_groups:[],ai:{},route:null}
  const job = {id:'replay-fixture',status:'succeeded',original_name:'构造视频.webm',route_color:'黄色',video:{fps:24,duration_seconds:8},holds_revision:'r1',hold_review_history:[],media:{source_video:{status:'available'},overlay_video:{status:'available'}},result:{video:{fps:24,duration_seconds:8},holds:[{id:1,bbox:[.2,.2,.15,.15]}],attempt:{contacts:[],action_steps:[]}}}
  if(options.review){job.status='awaiting_hold_review';job.hold_draft=job.result;job.hold_draft.holds[0].polygon=[[.2,.2],[.32,.21],[.35,.29],[.29,.35],[.2,.31]];delete job.result;delete job.media.overlay_video}
  if(options.longName)job.original_name='构造长名称 · '.repeat(18)+'.webm'
  if(options.lowerHold)job.hold_draft.holds[0].polygon=[[.2,.74],[.32,.75],[.35,.83],[.29,.9],[.2,.85]]
  page.on('pageerror',e=>errors.push(e.message))
  await page.route('**/api/**',async route=>{
    const req=route.request(), path=new URL(req.url()).pathname
    if(path.endsWith('.svg'))return route.fulfill({contentType:'image/svg+xml',body:wall})
    if(/\/(source-video|overlay-video|media)$/.test(path)){
      const range=req.headers().range?.match(/bytes=(\d+)-(\d*)/), start=range?+range[1]:0, end=range?.[2]?Math.min(+range[2],playbackMedia.length-1):playbackMedia.length-1
      return route.fulfill({status:range?206:200,contentType:'video/webm',body:playbackMedia.subarray(start,end+1),headers:{'Accept-Ranges':'bytes','Content-Length':String(end-start+1),...(range?{'Content-Range':`bytes ${start}-${end}/${playbackMedia.length}`}:{})}})
    }
    if(req.method()!=='GET'){
      if(options.workflow && path.endsWith('/workflow/upload')){
        writes.push({path,body:null});photo={id:'session',version:1,flow_version:3,status:'awaiting_color',board:structuredClone(board),colors:[],color_groups:[],ai:{},route:null}
        return route.fulfill({json:photo})
      }
      if(options.workflow && /\/media\/uploads\/[^/]+$/.test(path) && req.method()==='PUT'){
        writes.push({path,body:null});mediaBytes=Number(req.headers()['x-upload-offset'])+(req.postDataBuffer()?.length||0)
        return route.fulfill({json:{offset:mediaBytes}})
      }
      writes.push({path,body:req.postDataJSON()})
      if(path==='/api/settings/replay-vision')return route.fulfill({json:{...req.postDataJSON(),api_key:undefined,configured:true,ready:false}})
      if(options.review && path.endsWith('/holds/confirm-all')){job.holds_confirmation={revision:job.holds_revision};return route.fulfill({json:job})}
      if(options.review && path.endsWith('/holds/point/preview'))return route.fulfill({json:{proposal_id:'constructed-proposal',source_polygon:[[.3,.31],[.45,.3],[.5,.42],[.41,.5],[.3,.44]],supporting_frames:2}})
      if(options.review && path.endsWith('/holds/point')){
        assert.equal(req.postDataJSON().proposal_id,'constructed-proposal')
        job.hold_draft.holds.push({id:2,bbox:[.3,.3,.2,.2],polygon:[[.3,.31],[.45,.3],[.5,.42],[.41,.5],[.3,.44]],identity_source:'user_confirmed_video_click'})
        job.holds_revision='r2';job.hold_review_history.push({operation:'add_hold_at_point',version:1,point_xy:req.postDataJSON().point_xy,time_seconds:0})
        return route.fulfill({json:job})
      }
      if(options.review && req.method()==='DELETE' && path.endsWith('/holds/1')){
        job.hold_draft.holds=job.hold_draft.holds.filter(h=>h.id!==1);job.holds_revision='r3';return route.fulfill({json:job})
      }
      if(options.editorWorkflow && path.endsWith('/holds/editor/preview'))return route.fulfill({json:{candidates:[{proposal_id:'editor-proposal',source_polygon:req.postDataJSON().polygon,reference_polygon:req.postDataJSON().polygon}]}})
      if(options.editorWorkflow && path.endsWith('/holds/editor/confirm')){assert.equal(req.postDataJSON().proposal_id,'editor-proposal');return route.fulfill({json:job})}
      if(path.endsWith('/holds/editor/frame'))return route.fulfill({json:{frame_token:'f'.repeat(32),frame_index:0,time_seconds:0,frame_count:192,fps:24,width:600,height:800,aligned:true,quality:'构造素材',image_data_url:'data:image/svg+xml;base64,'+Buffer.from(wall).toString('base64'),holds:options.editorWorkflow?job.hold_draft.holds:[],candidates:options.editorWorkflow?[{candidate_index:0,polygon:[[.1,.1],[.2,.1],[.2,.2]]}]:[],holds_revision:'r1'}})
      if(options.workflow){
        if(path.endsWith('/session/color')){assert.equal(req.postDataJSON().recognize,true);photo={...photo,status:'ready',color:'黄色',route:savedRecord,ai:{status:'not_requested'}};return route.fulfill({json:photo})}
        if(path.endsWith('/session/save')){assert.deepEqual(req.postDataJSON().member_ids,board.objects.map(o=>o.id));photo={...photo,status:'saved',route:savedRecord};return route.fulfill({json:photo})}
        if(path.endsWith('/notes')){
          if(notesFail){return route.fulfill({status:503,json:{detail:'构造保存失败'}})}
          savedRecord={...req.postDataJSON(),version:savedRecord.version+1};return route.fulfill({json:savedRecord})
        }
        if(path.endsWith('/media/uploads'))return route.fulfill({json:{id:'upload',offset:0}})
        if(path.endsWith('/media/uploads/upload/complete')){savedRecord.media.push({id:'extra-'+savedRecord.media.length,kind:'photo',asset:{filename:'wall.svg'},created_at:'2026-10-07T00:00:00Z'});return route.fulfill({json:savedRecord})}
      }
      if(path.includes('/routes/'))return route.fulfill({json:{...records[0],...req.postDataJSON()}})
      throw new Error(`Unexpected mutation: ${path}`)
    }
    const data={
      '/api/auth/session':{authenticated:!options.login,auth_enabled:true,registration_enabled:true,username:'constructed-user',display_name:'构造验收账号'},
      '/api/pilot/edit-lease':{active:false,owned_by_me:false},'/api/holds/mapping':{},'/api/holds/vectors':{},'/api/holds/assets':[], '/api/my-boards':[], '/api/standard-board/routes':[],
      '/api/photo-routes/workflow/current':photo,'/api/photo-routes/v2/routes':records,
      [`/api/photo-routes/v2/boards/${board.id}`]:board,
      '/api/settings/vision':{configured:false},
      '/api/settings/replay-vision':{base_url:'https://example.invalid/v1',model:'constructed-vl',budget_cny:1,image_input_token_reserve:4096,image_cny_each:0,input_cny_per_million:null,output_cny_per_million:null,configured:false,ready:false},
      '/api/climb-replay/jobs':[job],'/api/climb-replay/jobs/replay-fixture':job,
      '/api/climb-replay/jobs/replay-fixture/actions':{task:{status:'succeeded'},result:organized,result_version:'fixture',media_ready:true,export:{status:'idle'},revision_count:0,vocabulary:{techniques:[]}},
      '/api/climb-replay/consent-policy':{version:'fixture',provider:'本机 RTMW-L',execution:'local',uploads_frames:false,enabled:true},'/api/climb-replay/test-videos':{items:[]},
    }
    for(const record of records)data[`/api/photo-routes/v2/routes/${record.id}`]=record.id===savedRecord.id?savedRecord:record
    return route.fulfill({json:Object.hasOwn(data,path)?data[path]:{}})
  })
  await page.route('**/desktop/status',route=>route.fulfill({json:{version:'构造验收',data_directory:'C:/constructed/private/data',local_model_available:true,pose_configured:true,action_configured:false}}))
  return {page,errors,writes,clearPhoto:()=>{photo=null},allowNotes:()=>{notesFail=false}}
}
async function stable(page) { await page.waitForTimeout(200) }

for(const [width,height,desktop] of [[360,800,false],[390,844,false],[1096,704,true],[1280,720,false],[1920,1080,true]])test(`photo entry groups remain together at ${width}px`,async()=>{
  const {page,errors,writes,clearPhoto}=await setup({width,height},{desktop})
  try{
    clearPhoto();await page.goto(base+'/#/photo-routes')
    await page.getByRole('button',{name:desktop?'选择本机照片':'拍摄墙面',exact:true}).waitFor()
    await page.waitForFunction(()=>[...document.querySelectorAll('.photo-work__samples img')].every(img=>img.naturalWidth>0))
    await fit(page,width>=900)
    const layout=await page.evaluate(()=>{
      const rect=selector=>document.querySelector(selector).getBoundingClientRect().toJSON()
      return {content:rect('.photo-work__home-content'),copy:rect('.photo-work__upload-copy'),actions:rect('.photo-work__capture-actions'),upload:rect('.photo-work__upload'),samples:rect('.photo-work__sample-section'),image:rect('.photo-work__samples img')}
    })
    assert.ok(layout.content.width<=880,'entry content has a readable maximum width')
    assert.ok(Math.abs(layout.actions.x-layout.copy.x)<2,'upload actions align with their explanation')
    assert.ok(layout.actions.top-layout.copy.bottom<=20,'the primary action stays close to its explanation')
    assert.ok(layout.samples.top-layout.upload.bottom<=28,'samples follow the upload group instead of anchoring at the screen bottom')
    assert.ok(layout.image.height>=150,'sample photos are large enough to inspect')
    await shot(page,`photo-entry-${width}`)
    const sample=page.getByRole('button',{name:/抱石路线1/})
    assert.equal(await sample.isEnabled(),true,'idle sample photos are available instead of being permanently disabled')
    await sample.click()
    await page.getByRole('button',{name:'确认上传',exact:true}).waitFor()
    assert.deepEqual(errors,[]);assert.deepEqual(writes,[])
  }finally{await page.close()}
})

for (const width of [1280, 1920]) test(`photo workspace web and App layout parity at ${width}px`, async () => {
  const contexts = await Promise.all([false,true].map(desktop => setup({width,height:850},{desktop})))
  try {
    const layouts=[]
    for (const [index,{page,errors,writes}] of contexts.entries()) {
      await page.goto(base+'/#/photo-routes')
      await page.getByLabel('打开调色盘选择线路颜色').waitFor()
      await page.waitForFunction(()=>document.querySelector('.photo-work__image img')?.naturalWidth>0)
      await fit(page,true)
      await panelFit(page)
      layouts.push(await page.evaluate(()=>['.photo-work','.photo-work__layout','.photo-review-viewer','.photo-work__tools','.photo-work__colors','.task-panel__footer'].map(selector=>{
        const element=document.querySelector(selector),rect=element.getBoundingClientRect()
        return {selector,x:rect.x,y:rect.y,width:rect.width,height:rect.height}
      })))
      assert.deepEqual(errors,[])
      assert.deepEqual(writes,[],'opening the shared workspace does not recognize or save')
      if(index===1)await shot(page,`app-photo-shared-${width}`)
    }
    assert.deepEqual(layouts[0],layouts[1],'desktop integration retains the web photo workspace layout')
  } finally {
    await Promise.all(contexts.map(({page})=>page.close()))
  }
})
async function fit(page,desktop=true){
  await stable(page)
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),true,'no horizontal page scroll')
  if(desktop){
    assert.equal(await page.evaluate(()=>document.documentElement.scrollHeight<=innerHeight+1),true,'no vertical page scroll')
    const clipped=await page.evaluate(()=>[...document.querySelectorAll('button')].filter(el=>{const r=el.getBoundingClientRect();return r.width&&r.height&&!el.closest('[data-panel-hidden]')&&(r.top< -1||r.left< -1||r.right>innerWidth+1||r.bottom>innerHeight+1)}).map(el=>el.textContent.trim()))
    assert.deepEqual(clipped,[],'visible buttons must stay inside the workspace')
  }
}
async function panelFit(page){
  for(const panel of await page.locator('.task-panel:visible').all()){
    const next=panel.locator('.task-panel__pages').getByRole('button',{name:'下一页',exact:true})
    for(let i=0;i<30;i++){
    await stable(page)
      const bounds=await panel.locator('.task-panel__viewport').evaluate(el=>({height:el.clientHeight-parseFloat(getComputedStyle(el).paddingTop)-parseFloat(getComputedStyle(el).paddingBottom),content:el.firstElementChild.getBoundingClientRect().height}))
      assert.ok(bounds.content<=bounds.height+2,`tool content ${bounds.content} must fit ${bounds.height}`)
      if(!await next.isVisible() || await next.isDisabled())break
      await next.click()
    }
  }
}
async function shot(page,name){if(process.env.BOULDER_CAPTURE){await page.evaluate(()=>{document.documentElement.style.scrollBehavior='auto';window.scrollTo(0,0)});await writeFile(new URL(name+'.viewport.json',captures),JSON.stringify(await page.evaluate(()=>({scrollY,visualViewportOffsetTop:visualViewport?.offsetTop,header:document.querySelector('.app-header')?.getBoundingClientRect().toJSON(),shellScrollTop:document.querySelector('.app-shell')?.scrollTop})),null,2));await page.screenshot({path:fileURLToPath(new URL(name+'.png',captures)),fullPage:true})}}

for(const [width,height]of [[1096,704],[1440,900],[390,844]])test(`replay upload directly offers frame sampling at ${width}px`,async()=>{
  const {page,errors,writes}=await setup({width,height},{desktop:width>=900})
  try{
    await page.goto(base+'/#/climb-replay')
    await page.locator('input[type=file]').first().setInputFiles({name:'constructed.webm',mimeType:'video/webm',buffer:media})
    await page.waitForFunction(()=>document.querySelector('.video-canvas video')?.readyState>=2)
    await stable(page)
    const picker=page.getByRole('button',{name:'从画面点选样本岩点',exact:true})
    assert.equal(await picker.isVisible(),true,'sampling is visible without turning a tool page')
    assert.equal(await page.locator('#replay-saved-route').count(),0)
    assert.equal(await page.locator('.setup-panel .task-panel__pages').count(),0)
    if(width>=900)assert.ok(await page.locator('.video-stage').evaluate(el=>el.getBoundingClientRect().height>=440),'compact tools preserve a large video preview')
    await shot(page,`replay-direct-color-${width}`)
    await picker.click()
    await page.getByLabel('在暂停的视频画面中点击目标线路岩点取色').waitFor()
    await page.keyboard.press('Escape')
    assert.equal(await page.getByRole('heading',{name:'线路取色',exact:true}).count(),1)
    assert.equal(await page.locator('.setup-panel .work-tabs,.setup-panel input[type=checkbox],.setup-panel .task-panel__pages').count(),0)
    assert.equal(await page.getByRole('button',{name:'上传并本地识别岩点',exact:true}).isDisabled(),true)
    assert.deepEqual(writes,[])
    assert.deepEqual(errors,[])
  }finally{await page.close()}
})

for(const [width,height]of [[900,720],[1096,704],[1280,720],[1366,768],[1440,900],[1920,1080],[390,844],[360,800]])test(`boulder workspace tasks fit ${width}×${height}`,async()=>{
  const {page,errors,writes,clearPhoto}=await setup({width,height}), desktop=width>=900
  try{
    await page.goto(base+'/#/photo-routes');await page.getByLabel('打开调色盘选择线路颜色').waitFor()
    await page.waitForFunction(()=>document.querySelector('.photo-work__image img')?.naturalWidth>0)
    await fit(page,desktop)
    if(width===1280)await shot(page,'desktop')
    if(width===390)await shot(page,'mobile')
    if(width===1440)await shot(page,'user-1440')
    if(desktop)await panelFit(page)
    assert.equal(await page.locator('.photo-work__tools').evaluate(el=>{const footer=el.querySelector('.task-panel__footer').getBoundingClientRect();return [...el.querySelectorAll('.photo-work__colors button')].every(b=>{const r=b.getBoundingClientRect();return !r.width||r.bottom<=footer.top})}),true,'palette never overlaps the fixed actions')
    if(width===1096)await shot(page,'fix-color-1096')
    await page.getByRole('button',{name:'我的记录',exact:true}).first().click()
    await page.getByRole('button',{name:/查看线路：构造线路 1/}).waitFor();await fit(page,desktop)
    await page.getByRole('navigation',{name:'线路记录分页'}).getByRole('button',{name:'下一页'}).click()
    await page.getByRole('button',{name:/查看线路：构造线路 4/}).waitFor()
    if(width===1366)await shot(page,'records-1366')
    await page.getByRole('button',{name:/查看线路：构造线路 4/}).click();await page.getByRole('button',{name:'岩点备注',exact:true}).waitFor();await fit(page,desktop)
    if(width===1920)await shot(page,'detail-1920')
    if(desktop)await panelFit(page)
    await page.getByRole('button',{name:'媒体',exact:true}).click();await fit(page,desktop)
    if(desktop)await panelFit(page)
    await page.getByRole('button',{name:'AI 复盘',exact:true}).first().click();await page.getByRole('button',{name:/最近分析/}).waitFor();await fit(page,desktop)
    if(width===1440)await shot(page,'replay-setup')
    if(width===390)await shot(page,'mobile-replay-setup')
    await page.locator('input[type=file]').first().setInputFiles({name:'constructed.webm',mimeType:'video/webm',buffer:media});await page.waitForFunction(()=>document.querySelector('.video-canvas video')?.readyState>=2)
    if(width===1440)await shot(page,'replay-color')
    await page.getByRole('button',{name:/最近分析/}).click()
    await page.getByRole('button',{name:/构造视频.webm/}).first().click()
    await page.waitForFunction(()=>document.querySelector('.unified-replay video')?.readyState>=2)
    await fit(page,desktop)
    await page.locator('.unified-replay video').evaluate(async v=>{await v.play();await new Promise(resolve=>setTimeout(resolve,350));v.pause()});await page.waitForFunction(()=>!document.querySelector('.unified-replay video').seeking);await page.waitForTimeout(700)
    if(width===1280)await shot(page,'replay-result')
    if(width===390)await shot(page,'mobile-replay-result')
    if(desktop)await panelFit(page)
    if(width===1280){
      const editorPosition=await page.locator('.unified-replay video').evaluate(v=>v.currentTime)
      const editorOpener=page.getByRole('button',{name:'放大单帧／手绘轮廓',exact:true}).first();await editorOpener.click()
      await page.getByRole('application',{name:'岩点轮廓画布'}).waitFor();await fit(page,true);await panelFit(page);await fit(page,true);await shot(page,'editor')
      const editorDialog=page.getByRole('dialog',{name:'单帧精修',exact:true})
      for(let i=0;i<36;i++){await page.keyboard.press(i<18?'Tab':'Shift+Tab');assert.equal(await editorDialog.evaluate(el=>el.contains(document.activeElement)),true,'editor traps keyboard focus away from background actions')}
      await page.keyboard.press('Escape');assert.equal(await editorDialog.count(),0,'Escape follows the editor close flow');assert.equal(await editorOpener.evaluate(el=>el===document.activeElement),true,'editor restores opener focus');assert.ok(Math.abs(await page.locator('.unified-replay video').evaluate(v=>v.currentTime)-editorPosition)<.1,'editor close preserves playback position')
      writes.splice(0)
    }
    const video=page.locator('.unified-replay video')
    await video.evaluate(v=>{v.pause();v.currentTime=2});await page.waitForFunction(()=>!document.querySelector('.unified-replay video').seeking);const position=await video.evaluate(v=>v.currentTime)
    await page.getByRole('button',{name:'更多资料',exact:true}).click()
    await page.getByRole('dialog',{name:'更多复盘资料'}).waitFor()
    await page.getByRole('button',{name:'关闭面板',exact:true}).click()
    assert.ok(Math.abs(await video.evaluate(v=>v.currentTime)-position)<.1,'panel switch preserves playback position')
    await page.getByRole('button',{name:'设置',exact:true}).first().click();await page.getByRole('button',{name:'AI 服务',exact:true}).click();await fit(page,desktop)
    if(width===1440)await shot(page,'settings')
    if(!desktop)await page.getByRole('button',{name:'完成',exact:true}).click();await page.getByRole('button',{name:'我的账号',exact:true}).first().click();await fit(page,desktop)
    if(width===1280)await shot(page,'account')
    assert.deepEqual(errors,[]);assert.deepEqual(writes,[],'navigation never starts analysis or saves')
    clearPhoto()
  }finally{await page.close()}
})

for(const width of [360,390,900,1096,1280])test(`hold selection and confirmation share the viewport at ${width}px`,async()=>{
  const {page,errors,writes}=await setup({width,height:width===360?800:width===390?844:704},{review:true,portrait:true})
  try{
    await page.goto(base+'/#/climb-replay')
    await page.getByRole('button',{name:/最近分析/}).click()
    await page.getByRole('button',{name:/构造视频.webm/}).first().click()
    await page.waitForFunction(()=>document.querySelector('.video-canvas video')?.readyState>=2)
    await page.locator('.video-canvas video').evaluate(async v=>{await v.play();await new Promise(resolve=>v.requestVideoFrameCallback(resolve));v.pause()})
      await stable(page)
    await fit(page,width>=900)
    assert.equal(await page.locator('.replay-review-tools').count(),0,'no separate inspector narrows the video')
    const bounds=await page.locator('.video-canvas').boundingBox()
    assert.ok(bounds.height>=400,`portrait video uses the available height: ${JSON.stringify(await page.evaluate(()=>[...document.querySelectorAll('.app-shell,.app-header,.shell-main,.replay-page,.replay-heading,.replay-workspace,.video-column,.player-tools,.playback-review,.video-stage,.video-canvas,.hold-global-actions,.mobile-tabs')].map(el=>({class:el.className,height:el.clientHeight,top:el.getBoundingClientRect().top,flex:getComputedStyle(el).flex}))))}`)
    assert.ok(Math.abs(bounds.width/bounds.height-360/640)<.01,'canvas follows video aspect with no internal letterboxing')
    assert.equal(await page.locator('.hold-box').count(),0,'holds never use bounding-box outlines')
    assert.deepEqual((await page.locator('.hold-contours polygon').first().getAttribute('points')).split(' ').map(p=>p.split(',').map(n=>Math.round(Number(n)))),[[20,20],[32,21],[35,29],[29,35],[20,31]],'display follows the saved contour rather than its bounding box')
    const globalConfirm=page.getByRole('button',{name:'确认全部岩点',exact:true})
    const enabledColor=await globalConfirm.evaluate(el=>getComputedStyle(el).backgroundColor)
    assert.equal(await globalConfirm.locator('svg').evaluate(el=>getComputedStyle(el).animationName),'none','ready confirmation icon must remain still')
    await shot(page,`review-idle-${width}`)
    await page.getByRole('button',{name:'选择岩点 1',exact:true}).click()
    assert.equal(await page.getByRole('button',{name:'删除所选岩点',exact:true}).isEnabled(),true)
    assert.equal(await page.getByRole('button',{name:'修改所选轮廓',exact:true}).isEnabled(),true)
    await shot(page,`canvas-selected-${width}`)
    await page.getByRole('button',{name:'取消岩点选择',exact:true}).click()
    await page.getByRole('button',{name:'补删点',exact:true}).click()
    await stable(page)
    const draw=page.getByRole('button',{name:'在视频画面上拖出单个漏检岩点的大概范围',exact:true}),r=await draw.boundingBox()
    assert.ok(r?.width>0&&r?.height>0,'drawing canvas is visible')
    await page.mouse.move(r.x+r.width*.55,r.y+r.height*.55);await page.mouse.down()
    await page.mouse.move(r.x+r.width*.75,r.y+r.height*.75,{steps:8});await page.mouse.up()
    const confirm=page.getByRole('button',{name:'轮廓正确，确认补入',exact:true})
    await confirm.waitFor()
    await fit(page,width>=900)
    const position=await page.evaluate(()=>({scrollY,frame:document.querySelector('.video-canvas').getBoundingClientRect().toJSON(),confirm:document.querySelector('.canvas-hold-actions').getBoundingClientRect().toJSON()}))
    const reserved=await page.evaluate(()=>({footer:document.querySelector('.hold-global-actions').getBoundingClientRect().toJSON(),nav:document.querySelector('.mobile-tabs').getBoundingClientRect().toJSON(),height:innerHeight}))
    assert.ok(position.frame.bottom<=reserved.footer.top+1,'global confirmation reserves space below the entire video and native playback controls')
    assert.ok(reserved.footer.bottom<=(width<900?reserved.nav.top:reserved.height)+1,'global confirmation stays above navigation and within the viewport')
    assert.equal(position.scrollY,0,'hold review stays in one viewport at every size')
    if(width>=900)assert.equal(position.scrollY,0,'preview never scrolls away from the frame')
    assert.ok(position.confirm.top>=position.frame.top&&position.confirm.bottom<=position.frame.bottom&&position.confirm.left>=position.frame.left&&position.confirm.right<=position.frame.right,'confirmation is on the video itself')
    assert.deepEqual(writes.map(w=>w.path),['/api/climb-replay/jobs/replay-fixture/holds/point/preview'],'drag only requests a contour preview')
    for(const [i,value]of [.55,.55,.75,.75].entries())assert.ok(Math.abs(writes[0].body.region_xyxy[i]-value)<.005,'drag coordinates map to the actual video, excluding surrounding workspace')
    if(width===900){
      await page.getByRole('button',{name:'取消候选岩点',exact:true}).click()
      assert.equal(await page.getByRole('group',{name:'候选岩点操作'}).count(),0)
      assert.equal(writes.length,1,'cancelling a candidate never saves it')
      await page.mouse.move(r.x+r.width*.55,r.y+r.height*.55);await page.mouse.down()
      await page.mouse.move(r.x+r.width*.75,r.y+r.height*.75,{steps:8});await page.mouse.up();await confirm.waitFor()
    }
    assert.equal(await globalConfirm.isDisabled(),true,'pending contour blocks global confirmation')
    assert.notEqual(await globalConfirm.evaluate(el=>getComputedStyle(el).backgroundColor),enabledColor,'disabled confirmation has a distinct neutral surface')
    await shot(page,`canvas-preview-${width}`)
    if(width===1096){
      await page.getByRole('group',{name:'候选岩点操作'}).getByRole('button',{name:'修改轮廓',exact:true}).click()
      await page.locator('.edited-contour').waitFor()
      assert.equal(await page.getByRole('button',{name:'自由描边',exact:true}).getAttribute('aria-pressed'),'true','opening an existing contour starts with freehand')
      assert.equal((await page.locator('.edited-contour').getAttribute('points')).split(' ').length,5,'candidate contour is carried into vertex editing')
      page.once('dialog',d=>d.accept());await page.getByRole('button',{name:'关闭精修',exact:true}).click()
      await confirm.waitFor()
      assert.ok(writes.at(-1).path.endsWith('/holds/editor/frame'),'opening or cancelling contour editing does not save or analyse')
    }
    await confirm.click()
    await page.getByText('已补入岩点并保存草稿，可继续补点；全部补完后再确认并分析。').waitFor()
    await fit(page,width>=900)
    assert.equal(await page.getByRole('button',{name:'开始本地分析',exact:true}).isVisible(),false)
    assert.deepEqual(writes.filter(w=>!w.path.endsWith('/holds/editor/frame')).map(w=>w.path),[...Array(width===900?2:1).fill('/api/climb-replay/jobs/replay-fixture/holds/point/preview'),'/api/climb-replay/jobs/replay-fixture/holds/point'],'confirm saves only the draft')
    await page.getByRole('button',{name:'补删点',exact:true}).click()
    await page.waitForFunction(()=>document.querySelector('.video-canvas video')?.readyState>=2)
    await page.locator('.video-canvas video').evaluate(async v=>{await v.play();await new Promise(resolve=>v.requestVideoFrameCallback(resolve));v.pause()})
    await page.getByRole('button',{name:'选择岩点 1',exact:true}).click()
    assert.equal(await page.getByRole('button',{name:'结束补删点',exact:true}).getAttribute('aria-pressed'),'true')
    await shot(page,`hold-add-delete-${width}`)
    await page.getByRole('button',{name:'删除所选岩点',exact:true}).click()
    await page.getByText('已删除岩点并保存草稿，请继续检查并确认全部岩点。').waitFor()
    assert.ok(writes.at(-1).path.endsWith('/holds/1'),'on-video deletion uses the selected hold identity')
    assert.equal(await page.getByRole('button',{name:'选择岩点 1',exact:true}).count(),0)
    assert.deepEqual(errors,[])
  }finally{await page.close()}
})

for(const width of [1280,1096,390])test(`confirmed hold layout and continuous zoom at ${width}px`,async()=>{
  const {page,errors,writes}=await setup({width,height:width===390?844:704},{review:true,portrait:true})
  try{
    await page.goto(base+'/#/climb-replay');await page.getByRole('button',{name:/最近分析/}).click()
    await page.getByRole('button',{name:/构造视频.webm/}).first().click()
    await page.waitForFunction(()=>document.querySelector('.video-canvas video')?.readyState>=2)
    await page.getByRole('button',{name:'确认全部岩点',exact:true}).click()
    await page.getByRole('button',{name:'开始本地分析',exact:true}).waitFor()
    await stable(page)
    const geometry=await page.evaluate(()=>({feedback:document.querySelector('.hold-inline-feedback').getBoundingClientRect().toJSON(),
      frame:document.querySelector('.review-media-viewport').getBoundingClientRect().toJSON(),
      footer:document.querySelector('.hold-global-actions').getBoundingClientRect().toJSON(),
      pageOverflow:document.documentElement.scrollWidth>innerWidth+1||document.documentElement.scrollHeight>innerHeight+1}))
    assert.ok(geometry.feedback.width>280 && geometry.feedback.height<80,'confirmation copy has a readable line measure')
    assert.ok(geometry.frame.height>180 && geometry.frame.width>100,'confirmation cannot collapse the video')
    assert.ok(geometry.frame.bottom<=geometry.footer.top+1 && geometry.footer.bottom<=page.viewportSize().height,'controls stay below the video and inside the window')
    assert.equal(geometry.pageOverflow,false)
    await shot(page,`confirmed-sampling-${width}`)
    const samples=await page.evaluate(()=>new Promise(resolve=>{
      const select=document.querySelector('[aria-label="视频放大倍数"]'),values=[],start=performance.now()
      select.value='4';select.dispatchEvent(new Event('change',{bubbles:true}))
      function measure(){const canvas=document.querySelector('.video-canvas').getBoundingClientRect(),view=document.querySelector('.review-media-viewport').getBoundingClientRect();values.push(canvas.height/view.height);if(performance.now()-start<340)requestAnimationFrame(measure);else resolve(values)}
      requestAnimationFrame(measure)
    }))
    assert.ok(samples.some(n=>n>1.05&&n<3.8),'zoom renders intermediate sizes instead of a single jump')
    assert.ok(Math.abs(samples.at(-1)-4)<.01)
    await page.getByLabel('视频放大倍数',{exact:true}).selectOption('2')
    await page.getByLabel('视频放大倍数',{exact:true}).selectOption('1')
    await page.waitForFunction(()=>document.querySelector('.review-media-viewport')?.dataset.zoomAnimating==='false')
    await page.emulateMedia({reducedMotion:'reduce'})
    await page.getByLabel('视频放大倍数',{exact:true}).selectOption('2')
    assert.equal(await page.locator('.review-media-viewport').getAttribute('data-zoom-animating'),'false','reduced motion keeps direct zoom control')
    assert.equal(writes.filter(w=>!w.path.endsWith('/holds/confirm-all')).length,0,'zoom does not save or analyze')
    assert.deepEqual(errors,[])
  }finally{await page.close()}
})

for(const width of [1280,390])test(`zoomed hold drawing maps back to the original frame at ${width}px`,async()=>{
  const {page,errors,writes}=await setup({width,height:width===390?844:720},{review:true,portrait:true})
  try{
    await page.goto(base+'/#/climb-replay');await page.getByRole('button',{name:/最近分析/}).click()
    await page.getByRole('button',{name:/构造视频.webm/}).first().click()
    const video=page.locator('.video-canvas video'),viewport=page.locator('.review-media-viewport')
    await page.waitForFunction(()=>document.querySelector('.video-canvas video')?.readyState>=2)
    await video.evaluate(async v=>{await v.play();await new Promise(resolve=>v.requestVideoFrameCallback(resolve));v.pause();v.currentTime=2})
    await page.waitForFunction(()=>!document.querySelector('.video-canvas video').seeking)
    await page.getByRole('button',{name:'补删点',exact:true}).click()
    assert.equal(await page.getByRole('button',{name:'选择岩点工具',exact:true}).count(),0,'selection is part of add/delete')
    await page.getByText('点击删点，拖框补点',{exact:true}).waitFor()
    const initialWindow=await viewport.boundingBox()
    for(const zoom of [2,4]){
      await page.getByLabel('视频放大倍数',{exact:true}).selectOption(String(zoom))
      await page.waitForFunction(()=>document.querySelector('.review-media-viewport')?.dataset.zoomAnimating==='false')
      await page.getByRole('button',{name:'平移放大画面',exact:true}).click()
      const pan=page.getByRole('button',{name:'拖动平移放大画面',exact:true}),area=await viewport.boundingBox()
      await page.mouse.move(area.x+area.width*.5,area.y+area.height*.5);await page.mouse.down()
      await page.mouse.move(area.x+area.width*.7,area.y+area.height*.62,{steps:8});await page.mouse.up()
      await pan.focus();await page.keyboard.press('ArrowRight')
      assert.equal(writes.length,zoom===2?0:1,'zoom and pan do not request processing')
      await page.getByRole('button',{name:'结束补删点',exact:true}).click()
      const frame=await page.locator('.video-canvas').boundingBox(),window=await viewport.boundingBox()
      assert.ok(Math.abs(frame.height/window.height-zoom)<.01)
      assert.ok(Math.abs(frame.width/frame.height-360/640)<.01,'zoom retains the original aspect ratio')
      if(width===1280)assert.ok(window.width>initialWindow.width+40,'zoom uses the side space rather than the original portrait viewport')
      assert.ok(frame.x<=window.x+1&&frame.y<=window.y+1&&frame.x+frame.width>=window.x+window.width-1&&frame.y+frame.height>=window.y+window.height-1,'panning never exposes blank canvas')
      if(zoom===4 && frame.width>window.width+50){
        await page.mouse.move(window.x+window.width*.5,window.y+window.height*.5);await page.mouse.wheel(40,0)
        await page.waitForFunction(oldX=>Math.abs(document.querySelector('.video-canvas').getBoundingClientRect().x-oldX)>1,frame.x)
        const moved=await page.locator('.video-canvas').boundingBox()
        assert.ok(moved.x<frame.x,'trackpad swipe pans horizontally without leaving add/delete');Object.assign(frame,moved)
      }
      const start={x:window.x+window.width*.65,y:window.y+window.height*.65},end={x:window.x+window.width*.8,y:window.y+window.height*.8}
      await page.mouse.move(start.x,start.y);await page.mouse.down();await page.mouse.move(end.x,end.y,{steps:8});await page.mouse.up()
      await page.getByRole('group',{name:'候选岩点操作'}).waitFor()
      const expected=[(start.x-frame.x)/frame.width,(start.y-frame.y)/frame.height,(end.x-frame.x)/frame.width,(end.y-frame.y)/frame.height]
      const preview=writes.at(-1);assert.ok(preview.path.endsWith('/holds/point/preview'))
      for(let i=0;i<4;i++)assert.ok(Math.abs(preview.body.region_xyxy[i]-expected[i])<.005,'panned and zoomed selection keeps original video coordinates')
      await stable(page)
      const actions=await page.getByRole('group',{name:'候选岩点操作'}).boundingBox(),currentWindow=await viewport.boundingBox()
      assert.ok(actions.x>=currentWindow.x&&actions.y>=currentWindow.y&&actions.x+actions.width<=currentWindow.x+currentWindow.width+1&&actions.y+actions.height<=currentWindow.y+currentWindow.height+1,`unscaled candidate actions stay in the visible viewport: ${JSON.stringify({actions,currentWindow})}`)
      assert.ok(Math.abs(await video.evaluate(v=>v.currentTime)-2)<.01,'zoom, pan and selection preserve the paused frame')
      assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1&&document.documentElement.scrollHeight<=innerHeight+1),true,'zoom stays inside the work area without page scrolling')
      const globalAction=await page.getByRole('button',{name:'确认全部岩点',exact:true}).boundingBox()
      assert.ok(globalAction.y+globalAction.height<=page.viewportSize().height,'global action stays in view')
      await shot(page,`zoom-preview-${width}-${zoom}`)
      if(zoom===2)await page.getByRole('button',{name:'取消候选岩点',exact:true}).click()
    }
    await page.getByRole('button',{name:'轮廓正确，确认补入',exact:true}).click()
    await page.getByText('已补入岩点并保存草稿，可继续补点；全部补完后再确认并分析。').waitFor()
    assert.equal(await page.getByLabel('视频放大倍数',{exact:true}).inputValue(),'4','saving preserves magnification')
    await page.getByRole('button',{name:'补删点',exact:true}).click()
    await page.getByLabel('视频放大倍数',{exact:true}).selectOption('8')
    await page.waitForFunction(()=>document.querySelector('.review-media-viewport')?.dataset.zoomAnimating==='false')
    const touchWindow=await viewport.boundingBox(),beforeTouch=await page.locator('.video-canvas').boundingBox(),beforeWrites=writes.length
    const cdp=await page.context().newCDPSession(page)
    const touches=[{x:touchWindow.x+touchWindow.width*.45,y:touchWindow.y+touchWindow.height*.5,id:1},{x:touchWindow.x+touchWindow.width*.55,y:touchWindow.y+touchWindow.height*.5,id:2}]
    await cdp.send('Input.dispatchTouchEvent',{type:'touchStart',touchPoints:[touches[0]]})
    await cdp.send('Input.dispatchTouchEvent',{type:'touchStart',touchPoints:touches})
    await cdp.send('Input.dispatchTouchEvent',{type:'touchMove',touchPoints:touches.map(p=>({...p,x:p.x+40}))})
    await cdp.send('Input.dispatchTouchEvent',{type:'touchEnd',touchPoints:[]})
    await page.waitForFunction(oldX=>Math.abs(document.querySelector('.video-canvas').getBoundingClientRect().x-oldX)>1,beforeTouch.x)
    assert.equal(writes.length,beforeWrites,'two-finger swipe never creates a box preview or saves')
    await cdp.detach()
    await page.getByRole('button',{name:'平移放大画面',exact:true}).click()
    const limits=await viewport.boundingBox()
    for(const direction of [1,-1]){
      await page.mouse.move(limits.x+limits.width*.5,limits.y+limits.height*.5);await page.mouse.down()
      await page.mouse.move(limits.x+limits.width*(.5+direction*10),limits.y+limits.height*(.5+direction*10),{steps:8});await page.mouse.up()
      const bounded=await page.locator('.video-canvas').boundingBox()
      assert.ok(bounded.x<=limits.x+1&&bounded.y<=limits.y+1&&bounded.x+bounded.width>=limits.x+limits.width-1&&bounded.y+bounded.height>=limits.y+limits.height-1,'8× pan clamps to the real image edges')
    }
    await page.mouse.move(limits.x+limits.width*.5,limits.y+limits.height*.5)
    await page.keyboard.down('Control');await page.mouse.wheel(0,100);await page.keyboard.up('Control')
    await page.waitForFunction(()=>document.querySelector('[aria-label="视频放大倍数"]').value==='4')
    await page.getByLabel('视频放大倍数',{exact:true}).selectOption('1')
    await page.waitForFunction(()=>document.querySelector('.review-media-viewport')?.dataset.zoomAnimating==='false')
    const full=await page.locator('.video-canvas').boundingBox(),window=await viewport.boundingBox()
    assert.ok(Math.abs(full.x-window.x)<1&&Math.abs(full.y-window.y)<1&&Math.abs(full.width/window.width-1)<.01,'1× restores the complete frame')
    // Clicking the real contour, away from its number, must select in add/delete mode.
    assert.equal(await page.getByRole('button',{name:'结束补删点',exact:true}).getAttribute('aria-pressed'),'true')
    await page.mouse.click(full.x+full.width*.27,full.y+full.height*.28)
    await page.getByRole('group',{name:'所选岩点操作'}).waitFor()
    await page.getByRole('button',{name:'删除所选岩点',exact:true}).waitFor()
    await shot(page,`zoom-selected-${width}`)
    await page.getByRole('button',{name:'取消岩点选择',exact:true}).click()
    assert.equal(writes.filter(w=>w.path.endsWith('/holds/point')).length,1)
    assert.ok(writes.every(w=>w.path.includes('/holds/point')),'no analysis, editor or render request')
    assert.deepEqual(errors,[])
  }finally{await page.close()}
})

for(const width of [1280,390])test(`editor keeps a clear save action and simplified tools at ${width}px`,async()=>{
  const {page,errors,writes}=await setup({width,height:width===390?844:720},{review:true,portrait:true,editorWorkflow:true})
  try{
    await page.goto(base+'/#/climb-replay');await page.getByRole('button',{name:/最近分析/}).click()
    await page.getByRole('button',{name:/构造视频.webm/}).first().click()
    await page.waitForFunction(()=>document.querySelector('.video-canvas video')?.readyState>=2)
    await page.getByRole('button',{name:'选择岩点 1',exact:true}).click()
    await page.getByRole('button',{name:'修改所选轮廓',exact:true}).click()
    const dialog=page.getByRole('dialog',{name:'单帧精修',exact:true})
    await dialog.locator('.edited-contour').waitFor()
    assert.equal(await dialog.getByText('周围背景',{exact:true}).count(),0)
    assert.equal(await dialog.getByLabel('选择已有待复核岩点候选',{exact:true}).count(),0)
    assert.equal(await dialog.getByRole('button',{name:'多边形描边',exact:true,includeHidden:true}).count(),0)
    assert.equal(await dialog.getByRole('button',{name:'框选识别区',exact:true,includeHidden:true}).count(),0)
    const check=dialog.getByRole('button',{name:'核对当前轮廓',exact:true})
    await check.waitFor();await stable(page)
    let r=await check.boundingBox();assert.ok(r.y>=0&&r.y+r.height<=page.viewportSize().height,'review action stays in view')
    const vertex=dialog.getByRole('button',{name:'轮廓顶点 1',exact:true})
    await vertex.focus();await page.keyboard.press('ArrowRight')
    const remove=dialog.getByRole('button',{name:'删除选中顶点',exact:true,includeHidden:true})
    await revealTool(page,remove);await remove.click()
    assert.equal((await dialog.locator('.edited-contour').getAttribute('points')).split(' ').length,4,'precision editor retains vertex editing')
    assert.ok(writes.every(w=>w.path.endsWith('/holds/editor/frame')),'vertex edits stay local')
    await check.click()
    const save=dialog.getByRole('button',{name:'确认保存轮廓修改',exact:true});await save.waitFor();await stable(page)
    await shot(page,`editor-tools-${width}`)
    await dialog.evaluate(el=>el.scrollTop=0);await stable(page)
    r=await save.boundingBox();assert.ok(r.y>=0&&r.y+r.height<=page.viewportSize().height&&r.height>=44,'save action stays visible without scrolling')
    assert.equal(await save.innerText(),'确认保存')
    assert.notEqual(await save.evaluate(el=>getComputedStyle(el).backgroundColor),await dialog.getByRole('button',{name:'关闭精修',exact:true}).evaluate(el=>getComputedStyle(el).backgroundColor),'save has the primary surface')
    if(width===1280)await fit(page,true)
    await shot(page,`editor-save-${width}`)
    await save.click();await dialog.getByText('已保存到岩点草稿，可继续补点',{exact:false}).waitFor()
    assert.equal(writes.filter(w=>w.path.endsWith('/holds/editor/preview')).length,1)
    assert.equal(writes.filter(w=>w.path.endsWith('/holds/editor/confirm')).length,1)
    assert.ok(writes.every(w=>w.path.includes('/holds/editor/')),'save does not analyse or render')
    assert.deepEqual(errors,[])
  }finally{await page.close()}
})

for(const width of [390,1096])test(`review file menu preserves playback and keyboard access at ${width}px`,async()=>{
  const {page,errors,writes}=await setup({width,height:width===390?844:704},{review:true,portrait:true,longName:true,lowerHold:true})
  try{
    await page.goto(base+'/#/climb-replay');await page.getByRole('button',{name:/最近分析/}).click()
    await page.getByRole('button',{name:/构造长名称/}).first().click()
    const video=page.locator('.video-canvas video')
    await page.waitForFunction(()=>document.querySelector('.video-canvas video')?.readyState>=2)
    await video.evaluate(async v=>{await v.play();v.pause();v.currentTime=2})
    await page.waitForFunction(()=>Math.abs(document.querySelector('.video-canvas video').currentTime-2)<.01&&!document.querySelector('.video-canvas video').seeking)
    await fit(page,true)
    const trigger=page.getByRole('button',{name:'视频与资料',exact:true})
    await trigger.focus();await page.keyboard.press('Enter')
    const menu=page.locator('.review-file-popover:popover-open');await menu.waitFor()
    const rect=await menu.boundingBox()
    assert.ok(rect.x>=0&&rect.y>=0&&rect.x+rect.width<=width&&rect.y+rect.height<=page.viewportSize().height,'native popover escapes the canvas and stays in view')
    assert.equal(await menu.getByRole('button',{name:'更换视频',exact:true}).isVisible(),true)
    assert.equal(await menu.getByRole('button',{name:'删除整次记录',exact:true}).isVisible(),true)
    assert.ok((await menu.locator('.review-menu-filename').textContent()).includes('构造长名称'),'record deletion has an explicit file context')
    const filename=await menu.locator('.review-menu-filename>span').evaluate(el=>({height:el.getBoundingClientRect().height,line:Number.parseFloat(getComputedStyle(el).lineHeight),padding:getComputedStyle(el).paddingBottom}))
    assert.ok(filename.height<=filename.line*2+1&&filename.padding==='0px','long filename clips cleanly at two lines without revealing a third')
    assert.equal(await menu.getByRole('button',{name:'更换视频',exact:true}).evaluate(el=>getComputedStyle(el).borderTopWidth),'0px','file actions use menu rows rather than an outlined button wall')
    await shot(page,`review-menu-${width}`)
    await page.keyboard.press('Escape');assert.equal(await menu.count(),0)
    assert.equal(await trigger.evaluate(el=>el===document.activeElement),true,'Escape returns focus to the file control')
    await replayFileAction(page,'记录与版本');await page.getByRole('dialog',{name:'岩点记录与版本'}).waitFor()
    await page.keyboard.press('Escape')
    assert.ok(Math.abs(await video.evaluate(v=>v.currentTime)-2)<.01,'opening file management never resets playback')
    const visibility=page.getByRole('checkbox',{name:'显示岩点轮廓',exact:true})
    await visibility.uncheck();assert.equal(await page.getByRole('button',{name:'选择岩点 1',exact:true}).count(),0)
    await visibility.check();await page.getByRole('button',{name:'选择岩点 1',exact:true}).click()
    const hold=await page.locator('.hold-contours polygon').boundingBox(),action=await page.locator('.canvas-hold-actions').boundingBox()
    assert.ok(action.y+action.height<=hold.y,'actions avoid a hold near the bottom of the video')
    await shot(page,`review-low-hold-${width}`)
    assert.deepEqual(writes,[],'menus, display controls and selection never save or analyse')
    assert.deepEqual(errors,[])
  }finally{await page.close()}
})

test('unpaginated palette grows above its footer at 899px',async()=>{
  const {page}=await setup({width:899,height:704})
  try{
    await page.goto(base+'/#/photo-routes');await page.getByLabel('打开调色盘选择线路颜色').waitFor()
    await stable(page)
    const colors=page.locator('.photo-work__colors')
    assert.ok(await colors.getByRole('button').count()>=8,'exercise the full preset palette')
    assert.equal(await page.locator('.photo-work__tools').evaluate(el=>el.querySelector('.photo-work__colors').getBoundingClientRect().bottom<=el.querySelector('.task-panel__footer').getBoundingClientRect().top),true)
    await fit(page,false);await shot(page,'fix-color-899')
  }finally{await page.close()}
})

for(const [width,height]of [[1280,720],[360,800]])test(`boulder authentication fits ${width}×${height}`,async()=>{
  const {page,errors,writes}=await setup({width,height},{login:true})
  try{
    await page.goto(base+'/#/photo-routes');await page.getByRole('heading',{name:'登录攀岩助手'}).waitFor();await fit(page,width>=1100);await shot(page,`login-${width}`)
    await page.getByRole('button',{name:'有邀请码？创建账号'}).click();await page.getByRole('heading',{name:'创建账号'}).waitFor();await fit(page,width>=1100);await shot(page,`register-${width}`)
    assert.deepEqual(writes,[]);assert.deepEqual(errors,[])
  }finally{await page.close()}
})

for(const [width,height] of [[1096,704],[1280,720],[390,844]])test(`settings contain service fields and reachable save controls at ${width}×${height}`,async()=>{
  const {page,errors,writes}=await setup({width,height},{desktop:width>=900})
  try{
    await page.goto(base+'/#/photo-routes');await page.getByRole('button',{name:'设置',exact:true}).first().click()
    if(width>=900){await page.getByText('C:/constructed/private/data',{exact:true}).waitFor();assert.equal(await page.getByRole('heading',{name:'文件存储'}).isVisible(),true)}
    await page.getByRole('button',{name:'AI 服务',exact:true}).click()
    const model=page.getByLabel('模型',{exact:true}), save=page.getByRole('button',{name:'保存评语服务',exact:true})
    await model.fill('constructed-edited-vl')
    await page.getByRole('button',{name:'账号',exact:true}).click();await page.getByRole('button',{name:'AI 服务',exact:true}).click()
    assert.equal(await model.inputValue(),'constructed-edited-vl','tab switching preserves unsaved fields')
    assert.equal(await page.getByRole('button',{name:'桌面配置',exact:true}).count(),0)
    assert.equal(await page.locator('.settings-page').innerText().then(text=>text.includes('阿里云')),false)
    await shot(page,`settings-service-top-${width}`)
    assert.equal(await page.getByLabel('输入 · 元／百万 token',{exact:true}).count(),0)
    await page.getByText('高级设置',{exact:true}).click()
    assert.equal(await page.getByLabel('启用费用估算与预算',{exact:true}).isChecked(),false)
    await page.getByLabel('启用费用估算与预算',{exact:true}).check()
    await page.getByText('图片计费与预留',{exact:true}).click()
    await page.getByLabel('额外图片费用 · 元／张',{exact:true}).scrollIntoViewIfNeeded()
    await save.scrollIntoViewIfNeeded()
    const rect=await save.boundingBox();assert.ok(rect.y>=0 && rect.y+rect.height<=height,'save remains inside the viewport after scrolling')
    await fit(page,width>=900);await shot(page,`settings-service-${width}`)
    assert.deepEqual(writes,[],'opening and editing settings never calls the service')
    await save.click();await page.getByRole('status').filter({hasText:'请补充计费参数'}).waitFor()
    assert.equal(writes.length,1);assert.equal(writes[0].path,'/api/settings/replay-vision');assert.equal(writes[0].body.model,'constructed-edited-vl')
    assert.deepEqual(errors,[])
  }finally{await page.close()}
})

for(const [width,height]of [[1280,720],[390,844]])test(`photo upload, explicit recognition, notes retry and media at ${width}px`,async()=>{
  const {page,errors,writes,clearPhoto,allowNotes}=await setup({width,height},{workflow:true}), desktop=width>=1100
  const photo={name:'constructed.png',mimeType:'image/png',buffer:Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a7S8AAAAASUVORK5CYII=','base64')}
  try{
    clearPhoto();await page.goto(base+'/#/photo-routes');await page.locator('input[type=file]').first().setInputFiles(photo)
    await page.getByRole('button',{name:'确认上传',exact:true}).waitFor();await fit(page,desktop);await page.getByRole('button',{name:'确认上传',exact:true}).click()
    await page.getByLabel('打开调色盘选择线路颜色').waitFor();assert.equal(writes.length,1,'upload does not recognize')
    await page.getByLabel('打开调色盘选择线路颜色').fill('#ebbe2c');await page.getByLabel('打开调色盘选择线路颜色').dispatchEvent('input');assert.equal(writes.length,1,'color selection does not recognize')
    await page.getByRole('button',{name:'识别黄色线路',exact:true}).click();await page.getByRole('button',{name:'保存线路',exact:true}).filter({visible:true}).click()
    await page.getByRole('button',{name:'岩点备注',exact:true}).waitFor();await fit(page,desktop)
    const name=page.getByLabel('线路名称',{exact:true});await name.fill('构造保存线路')
    await page.getByRole('button',{name:'岩点备注',exact:true}).click();await page.locator('.is-route-contour').first().click()
    await (await revealTool(page,page.getByLabel('岩点备注',{exact:true}))).fill('构造岩点备注')
    const retry=page.locator('.photo-work__tools button').filter({hasText:'重试保存备注'})
    await retry.waitFor({state:'attached'});allowNotes();await (await revealTool(page,retry)).click()
    await page.getByText('所有修改均已保存',{exact:true}).waitFor()
    const saved=writes.filter(w=>w.path.endsWith('/notes')).at(-1).body
    assert.equal(saved.name,'构造保存线路');assert.equal(saved.members[0].note,'构造岩点备注')
    await page.getByRole('button',{name:'媒体',exact:true}).click()
    const add=page.getByRole('button',{name:'添加媒体',exact:true});await (await revealTool(page,add)).click()
    await page.getByRole('dialog',{name:'添加到这条线路'}).waitFor();await page.keyboard.press('Escape');assert.equal(await page.getByRole('dialog').count(),0,'Escape closes the panel')
    assert.equal(await add.evaluate(el=>el===document.activeElement),true,'focus returns to the opener')
    for(let i=0;i<2;i++){await Promise.all([page.waitForResponse(r=>r.url().endsWith('/media/uploads/upload/complete')),page.locator('input[type=file]').first().setInputFiles(photo)]);await stable(page)}
    await page.getByRole('navigation',{name:'线路媒体分页',includeHidden:true}).waitFor({state:'attached'});await (await revealTool(page,page.locator('.record-media button').filter({hasText:'下一份'}))).click()
    assert.equal(await page.locator('.record-media__item').count(),1)
    await fit(page,desktop);if(desktop)await panelFit(page)
    assert.equal(writes.some(w=>w.path.includes('/analysis/')),false);assert.deepEqual(errors,[])
  }finally{await page.close()}
})

test('setter workspace retains its original tokens and controls',async()=>{
 const {page,errors,writes}=await setup({width:1280,height:720})
 try{
   await page.goto(base+'/#/dashboard');await page.locator('.workspace-setter').waitFor()
   assert.equal(await page.locator('.workspace-boulder').count(),0)
   assert.equal(await page.locator('.workspace-setter').evaluate(el=>getComputedStyle(el).getPropertyValue('--ui-ground').trim()===getComputedStyle(document.documentElement).getPropertyValue('--ui-ground').trim()),true)
   await page.getByRole('button',{name:'设置',exact:true}).click();await page.getByRole('heading',{name:'账号',exact:true}).waitFor()
   assert.equal(await page.getByRole('heading',{name:'DeepSeek API'}).isVisible(),true,'setter settings keep their original simultaneous panels')
   assert.deepEqual(errors,[]);assert.deepEqual(writes,[])
 }finally{await page.close()}
})

for(const [width,height]of [[1280,720],[390,844]])test(`minimal empty workspaces remain actionable at ${width}px`,async()=>{
  const {page,errors,writes,clearPhoto}=await setup({width,height},{workflow:true})
  try{
    clearPhoto();await page.goto(base+'/#/photo-routes');await page.getByRole('button',{name:'拍摄墙面',exact:true}).waitFor();await fit(page,width>=1100);await shot(page,`photo-empty-${width}`)
    await page.getByRole('button',{name:'AI 复盘',exact:true}).first().click();await page.getByText('导入视频',{exact:true}).waitFor();await fit(page,width>=1100)
    assert.equal(await page.getByRole('heading',{name:'AI 复盘',exact:true}).count(),1,'the page has one visible task title')
    assert.equal(await page.getByLabel('优先复用已确认岩点',{exact:true}).isVisible(),false,'material-specific tools wait for a video')
    await page.locator('input[type=file]').first().setInputFiles({name:'constructed.webm',mimeType:'video/webm',buffer:media});await page.waitForFunction(()=>document.querySelector('.video-canvas video')?.readyState>=2);assert.equal(await page.locator('.setup-panel input[type=checkbox]').count(),0);assert.equal(await page.getByRole('button',{name:'上传并本地识别岩点',exact:true}).isDisabled(),true);await fit(page,width>=1100)
    assert.deepEqual(writes,[]);assert.deepEqual(errors,[])
  }finally{await page.close()}
})
