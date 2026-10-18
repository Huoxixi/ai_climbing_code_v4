import {chromium} from '@playwright/test'
import test,{after} from 'node:test'
import assert from 'node:assert/strict'
import {startFixtureServer} from './fixtures/server.mjs'
const base=await startFixtureServer(4239),browser=await chromium.launch({headless:true})
after(()=>browser.close())
test('storage selection shows restart location and handles cancel and error',async()=>{
 const page=await browser.newPage({viewport:{width:390,height:900}})
 await page.addInitScript(()=>{window.__AI_CLIMBING_DESKTOP__=true})
 let response={cancelled:true},code=200
 await page.route('**/desktop/status',r=>r.fulfill({json:{data_directory:'C:\\攀岩\\data',update_label:'本机已更新：2026.10.17'}}))
 await page.route('**/desktop/storage/choose',r=>r.fulfill({status:code,json:response}))
 await page.route('**/api/**',r=>r.fulfill({json:new URL(r.request().url()).pathname.endsWith('/jobs')?[]:{version:'local-v1'}}))
 try{
  await page.goto(base+'/e2e/local-replay-harness.html')
  const button=page.getByRole('button',{name:'选择文件夹',exact:true})
  await page.getByText('本机已更新：2026.10.17',{exact:true}).waitFor()
  await button.click()
  await button.waitFor({state:'visible'})
  assert.equal(await page.getByText(/新位置：/).count(),0)
  response={directory:'D:\\我的攀岩',restart_required:true}
  await button.click()
  await page.getByText(/新位置：D:/).waitFor()
  assert.equal(await page.getByText('C:\\攀岩\\data',{exact:true}).count(),1)
  response={detail:'请选择空文件夹，以免覆盖已有文件。'};code=422
  await button.click()
  await page.getByRole('status').filter({hasText:'请选择空文件夹'}).waitFor()
  assert.equal(await page.locator('body').evaluate(el=>el.scrollWidth>window.innerWidth),false)
 }finally{await page.close()}
})
