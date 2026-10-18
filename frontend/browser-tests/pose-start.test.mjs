import {chromium} from '@playwright/test'
import test, {after} from 'node:test'
import assert from 'node:assert/strict'
import {startFixtureServer} from './fixtures/server.mjs'
import {syntheticMedia} from './fixtures/actions.mjs'
const base=await startFixtureServer(4249), browser=await chromium.launch({headless:true})
const media=await syntheticMedia(browser)
after(()=>browser.close())
for(const width of [1280,390])test(`pose-only start selection persists ${width}`,async()=>{
 const page=await browser.newPage({viewport:{width,height:900}}), errors=[], writes=[]
 page.on('pageerror',e=>errors.push(e.message))
 let start=null
 const state=()=>({task:{status:'idle'},result_version:'prepared',result:{skeleton_only:true,groups:[],metrics:[],source_duration_seconds:8,
  replay_visualization:{pose_samples:[],center_of_mass_trajectory:{segments:[],climbing_window:{start_seconds:start,status:start===null?'start_unconfirmed':'user_confirmed'}}}}})
 await page.route('**/api/climb-replay/jobs/pose-start/**',async route=>{
   const req=route.request()
   if(req.url().includes('/media/'))return route.fulfill({body:media,contentType:'video/webm'})
   if(req.method()==='PUT'){start=req.postDataJSON().start_seconds;writes.push(start)}
   return route.fulfill({json:state()})
 })
 await page.goto(`${base}/e2e/pose-start-harness.html`)
 await page.getByText('尚未确定攀爬起点。',{exact:false}).waitFor()
 await page.waitForFunction(()=>document.querySelector('video')?.readyState>=2)
 await page.getByRole('button',{name:/从这里开始/}).click()
 await page.getByText('（已手动定位）',{exact:false}).waitFor()
 assert.equal(writes.length,1);assert.equal(writes[0],0)
 await page.reload()
 await page.getByText('（已手动定位）',{exact:false}).waitFor()
 await page.getByRole('button',{name:'恢复自动判断',exact:true}).click()
 await page.getByText('尚未确定攀爬起点。',{exact:false}).waitFor()
 assert.deepEqual(writes,[0,null]);assert.deepEqual(errors,[])
 await page.close()
})
