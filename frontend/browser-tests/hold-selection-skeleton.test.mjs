import { chromium } from '@playwright/test'
import test,{after} from 'node:test'
import assert from 'node:assert/strict'
import { startFixtureServer } from './fixtures/server.mjs'
import { syntheticMedia } from './fixtures/actions.mjs'
const base=await startFixtureServer(4261), browser=await chromium.launch({headless:true})
after(()=>browser.close())
const media=await syntheticMedia(browser)
for(const width of [1280,390])test(`all-photo holds, manual route and shared precision editor at ${width}`,async()=>{
  const page=await browser.newPage({viewport:{width,height:900}});page.setDefaultTimeout(8000)
  let session={id:'photo',status:'ready',flow_version:4,version:1,color:'自选',ai:{status:'not_requested'},route:{id:'route',members:[]},board:{id:'board',width:600,height:800,version:1,original_asset:{filename:'fixture.svg'},objects:[{id:'yellow',color_group:'黄色',contour:[[100,100],[200,100],[200,200],[100,200]],object_version:1},{id:'blue',color_group:'蓝色',contour:[[300,300],[400,300],[400,400],[300,400]],object_version:1}]}}
  const errors=[],writes=[];page.on('pageerror',e=>errors.push(e.message))
  await page.route('**/api/**',async route=>{
    const req=route.request(),path=new URL(req.url()).pathname
    if(path.endsWith('fixture.svg'))return route.fulfill({contentType:'image/svg+xml',body:'<svg xmlns="http://www.w3.org/2000/svg" width="600" height="800"><rect width="600" height="800" fill="#bbb"/></svg>'})
    if(req.method()==='POST'){
      const payload=req.postDataJSON();writes.push({path,payload})
      if(path.endsWith('/members'))session={...session,version:session.version+1,route:{...session.route,members:payload.member_ids.map(object_id=>({object_id}))}}
      if(path.endsWith('/edit-contour')){session.version++;session.board.version++;session.board.objects.find(o=>o.id===payload.object_id).contour=payload.contour}
      return route.fulfill({json:session})
    }
    const states={'/api/auth/session':{authenticated:true,auth_enabled:false,username:'fixture'},'/api/photo-routes/workflow/current':session,'/api/photo-routes/v2/routes':[]}
    return route.fulfill({json:states[path]||{}})
  })
  try{
    await page.goto(base+'/#/photo-routes')
    await page.getByRole('heading',{name:'选择路线岩点',exact:true}).waitFor()
    const polygons=page.locator('.photo-work__image polygon');assert.equal(await polygons.count(),2)
    await polygons.nth(0).press('Enter');await page.waitForFunction(()=>!document.querySelector('.photo-work.is-busy'));await page.waitForFunction(()=>document.querySelectorAll('.is-route-contour').length===1)
    await polygons.nth(1).press('Enter');await page.waitForFunction(()=>!document.querySelector('.photo-work.is-busy'));await page.waitForFunction(()=>document.querySelectorAll('.is-route-contour').length===2)
    await polygons.nth(0).press('Enter');await page.waitForFunction(()=>!document.querySelector('.photo-work.is-busy'));await page.waitForFunction(()=>document.querySelectorAll('.is-route-contour').length===1)
    assert.deepEqual(session.route.members,[{object_id:'blue'}])
    await page.getByRole('button',{name:'岩点精修',exact:true}).click()
    const dialog=page.getByRole('dialog',{name:'单帧精修'});await dialog.waitFor()
    await dialog.getByLabel('选择要修改轮廓的岩点',{exact:true}).selectOption('2')
    await dialog.getByRole('button',{name:'核对当前轮廓',exact:true}).click()
    await dialog.getByRole('button',{name:'确认保存轮廓修改',exact:true}).click()
    await page.waitForFunction(()=>document.querySelector('.editor-savebar button')?.textContent.includes('核对'))
    assert.equal(writes.at(-1).payload.object_id,'blue');assert.equal(writes.at(-1).payload.contour.length,4)
    assert.equal(await dialog.getByRole('button',{name:'下一帧',exact:true}).count(),0)
    await dialog.getByRole('button',{name:'关闭精修',exact:true}).click()
    assert.deepEqual(errors,[])
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1),false)
  }finally{await page.close()}
})
test('upload skeleton without sampling a hold color',async()=>{
  const page=await browser.newPage();page.setDefaultTimeout(8000)
  let metadata,job=null
  await page.route('**/api/**',async route=>{
    const req=route.request(),path=new URL(req.url()).pathname
    if(path==='/api/climb-replay/uploads'){metadata=req.postDataJSON();return route.fulfill({json:{id:'upload',offset:0}})}
    if(req.method()==='PUT')return route.fulfill({json:{offset:media.length}})
    if(path.endsWith('/complete')){job={id:'skeleton',status:'queued',skeleton_only:true};return route.fulfill({json:job})}
    const states={'/api/auth/session':{authenticated:true,auth_enabled:false,username:'fixture'},'/api/photo-routes/workflow/current':null,'/api/photo-routes/v2/routes':[], '/api/climb-replay/jobs':job?[job]:[], '/api/climb-replay/consent-policy':{version:'test'},'/api/climb-replay/test-videos':[]}
    return route.fulfill({json:states[path]||{}})
  })
  try{
    await page.goto(base+'/#/climb-replay')
    await page.locator('input[type=file]').first().setInputFiles({name:'video.webm',mimeType:'video/webm',buffer:media})
    const skip=page.getByRole('button',{name:'跳过岩点，只生成骨架',exact:true});await skip.waitFor();assert.equal(await skip.isEnabled(),true)
    await skip.click();await page.waitForFunction(()=>document.body.textContent.includes('正在处理')||document.body.textContent.includes('等待'))
    assert.equal(metadata.skip_holds,true);assert.equal(metadata.route_color,'');assert.equal(metadata.route_color_sample,null)
  }finally{await page.close()}
})

