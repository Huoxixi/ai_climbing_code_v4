import { chromium } from '@playwright/test'
import test, { after } from 'node:test'
import assert from 'node:assert/strict'
import { mkdir } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'
import { startFixtureServer } from './fixtures/server.mjs'
import { organized, syntheticMedia } from './fixtures/actions.mjs'
const base = await startFixtureServer(4211)
const browser = await chromium.launch({headless:true})
const media = await syntheticMedia(browser)
const shots = new URL('../../.tmp/replay-professional-ui/',import.meta.url)
await mkdir(shots,{recursive:true})
after(()=>browser.close())

test('ordinary events stay silent and cannot trigger paid explanations',async()=>{
  const page=await browser.newPage(),writes=[]
  const result=structuredClone(organized)
  result.commentary_policy={important_only:true,selected_event_count:0}
  result.groups.forEach(g=>{g.important_action=null;g.action_features=[{limb:'left_hand',commentary:'左手向上移动。'}]})
  await page.route('**/api/climb-replay/**',async route=>{
    if(/\/(media|overlay-video|source-video)$/.test(new URL(route.request().url()).pathname))return route.fulfill({body:media,contentType:'video/webm'})
    if(route.request().method()==='POST')writes.push(route.request().postDataJSON())
    return route.fulfill({json:{task:{status:'idle'},result,cloud_configured:true,export:{status:'idle'}}})
  })
  try{
    await page.goto(base+'/e2e/actions-harness.html')
    await page.locator('.no-current-action').waitFor()
    assert.equal(await page.locator('.commentary-segment').count(),0)
    await page.getByText('生成 AI 重要动作解说',{exact:true}).click()
    await page.getByLabel('同意发送本次动作证据，并确认费用').check()
    assert.equal(await page.getByRole('button',{name:'解说重要动作',exact:true}).isDisabled(),true)
    assert.deepEqual(writes,[])
  }finally{await page.close()}
})

for (const width of [1280,390]) test(`commentary, independent consent and inline statistics at ${width}px`,async()=>{
  const page=await browser.newPage({viewport:{width,height:900},reducedMotion:'reduce'})
  const result=structuredClone(organized), writes=[], errors=[]
  const group=result.groups[0]
  group.events=[]
  group.action_features=[{id:'a:left_foot',limb:'left_foot',start_seconds:0,end_seconds:1.5,
    commentary:'左脚抬高后向右移动。',commentary_basis:'vision_evidence'}]
  group.important_action={title:'高抬腿',limb:'left_foot',commentary:'左脚抬高后向右移动。',commentary_basis:'vision_evidence',quality:{status:'observed'}}
  result.priority_focus={kind:'review',title:'本次最值得回看',text:'左脚抬高后向右移动。',start_seconds:0,end_seconds:1.5,
    next_check:'按原片时间回看，核对这段肢体移动的方向与前后衔接。'}
  result.commentary_disclaimer='AI 评语基于视频中的可见信息，可能存在识别偏差，请结合原片核对。'
  const state={task:{status:'succeeded'},result,result_version:'new-v1',media_ready:true,
    cloud_configured:true,consent_version:'evidence-commentary-v1',budget_cny:1,export:{status:'idle'}}
  page.on('pageerror',e=>errors.push(e.message))
  await page.route('**/api/climb-replay/**',async route=>{
    const request=route.request(), path=new URL(request.url()).pathname
    if (path.endsWith('/media')||path.endsWith('/overlay-video')||path.endsWith('/source-video')) return route.fulfill({body:media,contentType:'video/webm'})
    if (request.method()==='POST') writes.push(request.postDataJSON())
    return route.fulfill({json:state})
  })
  try {
    await page.goto(base+'/e2e/actions-harness.html')
    await page.getByText('左脚抬高后向右移动。',{exact:true}).waitFor()
    assert.equal(await page.getByText(result.commentary_disclaimer,{exact:true}).count(),1)
    assert.equal(await page.locator('.summary-focus').count(),0)
    await page.getByText('生成 AI 重要动作解说',{exact:true}).click()
    const generate=page.getByRole('button',{name:'解说重要动作',exact:true})
    assert.equal(await generate.isDisabled(),true)
    assert.equal(writes.length,0)
    await page.getByLabel('同意发送本次动作证据，并确认费用').check()
    await generate.click()
    assert.deepEqual(writes,[{cloud_consent:true,consent_version:'evidence-commentary-v1',budget_confirmed:true}])
    assert.equal(await page.getByRole('button',{name:'复盘总结',exact:true}).count(),0)
    assert.equal(await page.locator('.summary-focus,.summary-overlay,.summary-orb').count(),0)
    await page.getByRole('button',{name:'基础数据统计',exact:true}).click()
    await page.getByRole('region',{name:'基础数据统计',exact:true}).waitFor()
    if (!process.env.REPLAY_SKIP_SCREENSHOTS) await page.screenshot({path:fileURLToPath(new URL(`commentary-${width}.png`,shots)),fullPage:true})
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true)
    assert.deepEqual(errors,[])
  } finally {await page.close()}
})

test('vision settings save is owner API only and prices may remain unknown',async()=>{
  const page=await browser.newPage({viewport:{width:390,height:900}}), writes=[], errors=[]
  page.on('pageerror',e=>errors.push(e.message))
  await page.route('**/api/settings/replay-vision',async route=>{
    if(route.request().method()==='PUT') writes.push(route.request().postDataJSON())
    return route.fulfill({json:{base_url:'https://example.invalid/v1',model:'test-vl',budget_cny:1,cost_control_enabled:false,
      image_input_token_reserve:4096,image_cny_each:0,input_cny_per_million:null,output_cny_per_million:null,
      configured:route.request().method()==='PUT',ready:route.request().method()==='PUT'}})
  })
  try{
    await page.goto(base+'/e2e/replay-vision-harness.html')
    assert.equal(await page.getByLabel('输入 · 元／百万 token',{exact:true}).count(),0)
    assert.equal(await page.getByText('单次总预算（元，含重试）',{exact:true}).count(),0)
    await page.getByLabel('API 密钥',{exact:true}).fill('constructed-key')
    await page.getByRole('button',{name:'保存评语服务',exact:true}).click()
    await page.getByRole('status').filter({hasText:'生成评语前仍需单独确认'}).waitFor()
    assert.equal(writes.length,1)
    assert.equal(writes[0].input_cny_per_million,null)
    assert.equal(writes[0].cost_control_enabled,false)
    assert.equal(writes[0].api_key,'constructed-key')
    assert.equal(await page.getByLabel('API 密钥',{exact:true}).inputValue(),'')
    assert.match(await page.getByRole('status').innerText(),/尚未发送请求/)
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true)
    if (!process.env.REPLAY_SKIP_SCREENSHOTS) await page.screenshot({path:fileURLToPath(new URL('settings-390.png',shots)),fullPage:true})
    assert.deepEqual(errors,[])
  }finally{await page.close()}
})

test('unpriced model calls require consent and show no budget promise',async()=>{
  const page=await browser.newPage({viewport:{width:1280,height:850}}), writes=[]
  const state={task:{status:'succeeded',usage:[{stage:'action_commentary',usage_complete:true}]},
    result:structuredClone(organized),result_version:'optional-pricing',media_ready:true,
    cost:{known_amount:null,usage_complete:false},cloud_configured:true,cost_control_enabled:false,
    consent_version:'evidence-commentary-v1',budget_cny:null,export:{status:'idle'}}
  await page.route('**/api/climb-replay/**',async route=>{
    if(/\/(media|overlay-video|source-video)$/.test(new URL(route.request().url()).pathname))return route.fulfill({body:media,contentType:'video/webm'})
    if(route.request().method()==='POST')writes.push(route.request().postDataJSON())
    return route.fulfill({json:state})
  })
  try{
    await page.goto(base+'/e2e/actions-harness.html')
    await page.getByText('生成 AI 重要动作解说',{exact:true}).click()
    await page.getByText('未启用费用估算',{exact:false}).waitFor()
    const generate=page.getByRole('button',{name:'解说重要动作',exact:true})
    assert.equal(await generate.isDisabled(),true)
    assert.ok(!(await page.locator('.local-check').innerText()).includes('当前总预算'))
    await page.getByLabel('同意发送本次动作证据，并确认费用').check()
    await generate.click()
    assert.deepEqual(writes,[{cloud_consent:true,consent_version:'evidence-commentary-v1',budget_confirmed:true}])
  }finally{await page.close()}
})

test('saved commentary recovery is explicitly local and requires no cloud consent',async()=>{
  const page=await browser.newPage({viewport:{width:1280,height:850}}), writes=[]
  const state={task:{status:'failed',error:'评语已保存，视频生成失败。',usage:[{status:'succeeded',stage:'action_commentary'}]},
    result:structuredClone(organized),result_version:'previous-local',media_ready:true,
    saved_commentary_available:true,saved_response_count:1,cloud_configured:false,export:{status:'idle'}}
  await page.route('**/api/climb-replay/**',async route=>{
    if(/\/(media|overlay-video|source-video)$/.test(new URL(route.request().url()).pathname))return route.fulfill({body:media,contentType:'video/webm'})
    if(route.request().method()==='POST')writes.push(route.request().postDataJSON())
    return route.fulfill({json:state})
  })
  try{
    await page.goto(base+'/e2e/actions-harness.html')
    await page.getByText('生成 AI 重要动作解说',{exact:true}).click()
    const recover=page.getByRole('button',{name:'恢复已保存评语',exact:true})
    assert.equal(await recover.isEnabled(),true)
    await recover.click()
    assert.deepEqual(writes,[{cloud_consent:false,consent_version:null,budget_confirmed:false,reuse_saved_commentary:true}])
  }finally{await page.close()}
})

for (const width of [1280,390]) test(`event cards and failed commentary retry never authorize a visual request at ${width}px`,async()=>{
  const page=await browser.newPage({viewport:{width,height:900}}),writes=[],errors=[]
  const result=structuredClone(organized)
  result.groups=result.groups.slice(0,2)
  result.groups[0].action_features=[{limb:'left_hand',commentary:'左手向上移动。',commentary_basis:'local_observation'},
    {limb:'body',commentary:'身体向左移动。',commentary_basis:'local_observation'}]
  result.groups[1].action_features=[{limb:'right_foot',commentary:'右脚向上移动。',commentary_basis:'local_observation'}]
  result.groups[0].important_action={title:'重心调整',limb:'body',commentary:'双脚保持位置，估算重心向左转移，身体随之横移。',quality:{status:'observed'}}
  result.groups[1].important_action={title:'高抬腿',limb:'right_foot',commentary:'右腿屈膝抬高，膝部接近髋部高度，为较高落脚位置做准备。',quality:{status:'observed'}}
  const state={task:{status:'failed',failed_stage:'commentary',usage:[{status:'succeeded'}]},result,
    result_version:'events',media_ready:false,cloud_configured:true,vision_status:'succeeded',
    local_commentary_retry_available:true,vision_request_count:1,saved_response_count:1,export:{status:'idle'}}
  page.on('pageerror',e=>errors.push(e.message))
  await page.route('**/api/climb-replay/**',async route=>{
    if(/\/(media|overlay-video|source-video)$/.test(new URL(route.request().url()).pathname))return route.fulfill({body:media,contentType:'video/webm'})
    if(route.request().method()==='POST')writes.push(route.request().postDataJSON())
    return route.fulfill({json:state})
  })
  try{
    await page.goto(base+'/e2e/actions-harness.html')
    await page.locator('.commentary-segment').first().waitFor()
    assert.equal(await page.locator('.commentary-segment').count(),2)
    assert.equal(await page.locator('.commentary-segment').first().locator('.motion-name').count(),1)
    assert.match(await page.locator('.commentary-segment').first().innerText(),/动作 1｜重心调整/)
    await page.getByText('生成 AI 重要动作解说',{exact:true}).click()
    assert.match(await page.locator('.local-check').innerText(),/本次重试不会再次调用视觉服务/)
    assert.equal(await page.getByLabel('同意发送本次动作证据，并确认费用').count(),0)
    await page.getByRole('button',{name:'只重试评语处理（本地）',exact:true}).click()
    assert.deepEqual(writes,[{retry_saved_response:true}])
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true)
    assert.deepEqual(errors,[])
  }finally{await page.close()}
})

test('unsegmented timeline cannot be sent even after checking paid consent',async()=>{
  const page=await browser.newPage(),writes=[]
  const result=structuredClone(organized)
  result.event_validation={analysis_valid:false,message:'尚未切分出至少两个不同的动作时间段，已禁止生成收费评语。'}
  const state={task:{status:'idle'},result,cloud_configured:true,export:{status:'idle'}}
  await page.route('**/api/climb-replay/**',async route=>{
    if(/\/(media|overlay-video|source-video)$/.test(new URL(route.request().url()).pathname))return route.fulfill({body:media,contentType:'video/webm'})
    if(route.request().method()==='POST')writes.push(route.request().postDataJSON())
    return route.fulfill({json:state})
  })
  try{
    await page.goto(base+'/e2e/actions-harness.html')
    await page.getByText('生成 AI 重要动作解说',{exact:true}).click()
    await page.getByLabel('同意发送本次动作证据，并确认费用').check()
    assert.equal(await page.getByRole('button',{name:'解说重要动作',exact:true}).isDisabled(),true)
    assert.equal(await page.locator('.commentary-segment').count(),0)
    assert.deepEqual(writes,[])
  }finally{await page.close()}
})

test('old paid returns remain visible while repeat visual requests are removed',async()=>{
  const page=await browser.newPage(),writes=[]
  const state={task:{status:'failed'},result:structuredClone(organized),result_version:'local-events',
    cloud_configured:true,legacy_saved_vision_return:true,saved_response_count:1,vision_request_count:1,export:{status:'idle'}}
  await page.route('**/api/climb-replay/**',async route=>{
    if(/\/(media|overlay-video|source-video)$/.test(new URL(route.request().url()).pathname))return route.fulfill({body:media,contentType:'video/webm'})
    if(route.request().method()==='POST')writes.push(route.request().postDataJSON())
    return route.fulfill({json:state})
  })
  try{
    await page.goto(base+'/e2e/actions-harness.html')
    await page.getByText('生成 AI 重要动作解说',{exact:true}).click()
    assert.match(await page.locator('.local-check').innerText(),/旧视觉返回已保留/)
    assert.equal(await page.getByRole('button',{name:'解说重要动作',exact:true}).count(),0)
    assert.equal(await page.getByLabel('同意发送本次动作证据，并确认费用').count(),0)
    assert.deepEqual(writes,[])
  }finally{await page.close()}
})
