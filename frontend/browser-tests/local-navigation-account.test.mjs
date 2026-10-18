import { chromium } from '@playwright/test'
import test,{after} from 'node:test'
import assert from 'node:assert/strict'
import { mkdir } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'
import { startFixtureServer } from './fixtures/server.mjs'
const base=await startFixtureServer(4241)
const browser=await chromium.launch({headless:true})
after(()=>browser.close())
const captures=new URL('../../.impeccable/review/local-navigation-account/',import.meta.url)
await mkdir(captures,{recursive:true})
for(const [width,desktop] of [[1280,false],[390,false],[1280,true]])test(`local navigation and merged account at ${width}px desktop=${desktop}`,async()=>{
  const page=await browser.newPage({viewport:{width,height:850}}),errors=[],writes=[]
  page.setDefaultTimeout(5000)
  await page.addInitScript(desktop=>{window.__AI_CLIMBING_DESKTOP__=desktop;sessionStorage.setItem('climbing-active-workspace','setter')},desktop)
  page.on('pageerror',e=>errors.push(e.message))
  await page.route('**/api/**',async route=>{
    const req=route.request(),path=new URL(req.url()).pathname
    if(req.method()!=='GET')writes.push(path)
    const states={
      '/api/auth/session':{authenticated:true,auth_enabled:false,username:'owner',display_name:'本地账号'},
      '/api/pilot/edit-lease':{active:false,owned_by_me:false},
      '/api/holds/mapping':{},'/api/holds/vectors':{},'/api/holds/assets':[],'/api/my-boards':[],
      '/api/photo-routes/workflow/current':null,'/api/photo-routes/v2/routes':[],
      '/api/settings/vision':{configured:false},
      '/api/settings/replay-vision':{configured:false,ready:false,base_url:'',model:'',cost_control_enabled:false},
    }
    return route.fulfill({json:Object.hasOwn(states,path)?states[path]:{}})
  })
  await page.route('**/desktop/status',route=>route.fulfill({json:{data_directory:'C:/synthetic/local-data'}}))
  try{
    await page.goto(base+'/#/dashboard')
    await page.locator('.workspace-boulder').waitFor()
    assert.ok(page.url().endsWith('#/photo-routes'))
    assert.equal(await page.locator('.workspace-setter,.workspace-gateway').count(),0)
    assert.equal(await page.getByRole('button',{name:'我的账号',exact:true}).count(),0)
    assert.equal(await page.getByRole('link',{name:'返回项目选择',exact:true}).count(),0)
    await page.getByRole('button',{name:'设置',exact:true}).click()
    await page.getByRole('heading',{name:'账号',exact:true}).waitFor()
    await page.getByText('仅自己可见',{exact:true}).waitFor()
    await page.locator('summary').filter({hasText:'数据与隐私'}).click()
    await page.locator('summary').filter({hasText:'本机草稿'}).click()
    const logout=page.getByRole('button',{name:'退出当前账号',exact:true})
    await logout.scrollIntoViewIfNeeded()
    assert.equal(await logout.isVisible(),true)
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false)
    await page.screenshot({path:fileURLToPath(new URL(`${desktop?'app':width===390?'mobile':'desktop'}.png`,captures)),fullPage:true})
    if(desktop)assert.equal(await page.getByRole('heading',{name:'文件存储',exact:true}).isVisible(),true)
    await page.getByRole('button',{name:'AI 服务',exact:true}).click()
    await page.getByRole('heading',{name:'动作评语',exact:true}).waitFor()
    await page.evaluate(()=>{location.hash='#/account'})
    await page.waitForFunction(()=>location.hash==='#/settings')
    await page.getByRole('button',{name:'账号',exact:true}).click()
    await logout.click()
    await page.getByText('已退出登录',{exact:true}).waitFor()
    assert.equal(await page.locator('.workspace-gateway').count(),0)
    await page.getByRole('button',{name:'登录本地账号',exact:true}).click()
    await page.locator('.workspace-boulder').waitFor()
    await page.evaluate(()=>{location.hash='#/projects'})
    await page.waitForFunction(()=>location.hash==='#/photo-routes')
    assert.deepEqual(writes,['/api/auth/logout'])
    assert.deepEqual(errors,[])
  }finally{await page.close()}
})
