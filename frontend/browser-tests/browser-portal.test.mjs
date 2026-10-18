import test,{after} from 'node:test'
import assert from 'node:assert/strict'
import {readFile,mkdir,writeFile} from 'node:fs/promises'
import {resolve} from 'node:path'
import {fileURLToPath} from 'node:url'
import {chromium} from '@playwright/test'
import {startFixtureServer} from './fixtures/server.mjs'
const root=fileURLToPath(new URL('../../',import.meta.url)),captures=resolve(root,'.impeccable/review/browser-core')
await mkdir(captures,{recursive:true})
const base=await startFixtureServer(4335,undefined,{args:['--config','vite.browser.config.js']})
const browser=await chromium.launch({headless:true})
after(()=>browser.close())
const report={}
async function corePage(){
  const context=await browser.newContext(),page=await context.newPage(),requests=[]
  await page.route('**/api/**',route=>route.abort())
  await page.route('**/browser-models/**/*.onnx',route=>route.fulfill({status:503,body:'no model download in UI tests'}))
  page.on('request',r=>requests.push(r.url()))
  await page.goto(base+'/browser-replay.html')
  await page.getByRole('heading',{name:'视频复盘',exact:true}).waitFor()
  return {context,page,requests}
}

test('opens directly without accounts or server API requests and supports desktop/mobile',{timeout:30000},async()=>{
  const {context,page,requests}=await corePage()
  assert.equal(await page.getByRole('button',{name:'选择本地视频',exact:false}).count(),1)
  assert.equal(await page.getByText(/登录|注册|邀请码|用户管理|首次设置管理员/).count(),0)
  assert.equal(await page.getByRole('link',{name:'下载桌面版'}).getAttribute('href'),'/downloads/climbing-assistant-windows.exe')
  await page.getByRole('alert').waitFor()
  await page.evaluate(()=>document.fonts.ready)
  await page.setViewportSize({width:1280,height:800})
  await page.screenshot({path:resolve(captures,'desktop.png'),fullPage:true})
  for(const width of [780,390]){await page.setViewportSize({width,height:844});assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true)}
  await page.screenshot({path:resolve(captures,'mobile.png'),fullPage:true})
  await page.getByRole('button',{name:'我的记录',exact:true}).click()
  await page.getByRole('heading',{name:'还没有本机记录'}).waitFor()
  await page.getByRole('button',{name:'本机存储',exact:true}).click()
  await page.getByRole('heading',{name:'当前浏览器'}).waitFor()
  await page.screenshot({path:resolve(captures,'storage-mobile.png'),fullPage:true})
  assert.equal(requests.filter(url=>url.includes('/api/')).length,0)
  report.direct_entry=true;report.account_requests=0
  await context.close()
})

test('existing account records remain usable without migration, with atomic quota handling and scoped deletion',{timeout:30000},async()=>{
  const {context,page}=await corePage()
  const clip=await readFile(resolve(process.env.CLIMB_BROWSER_NATIVE_FIXTURES||resolve(root,'.tmp/browser-local-replay-20261017'),'clip.mp4'))
  await page.route('**/__fixtures/clip.mp4',route=>route.fulfill({body:clip,contentType:'video/mp4'}))
  const legacyOwner='a'.repeat(32),otherOwner='b'.repeat(32)
  const checked=await page.evaluate(async({legacyOwner,otherOwner})=>{
    const {saveReplay,listHistory,listLocalHistory,readHistory,LOCAL_HISTORY_OWNER}=await import('/src/browser-replay/localHistory.js')
    const video=await(await fetch('/__fixtures/clip.mp4')).blob()
    const analysis={complete:true,start_seconds:0,end_seconds:1.2,sample_fps:10,video:{width:720,height:1280,duration_seconds:1.2},pose_samples:[]}
    const a=await saveReplay(legacyOwner,{id:'shared-id',name:'原账号的本机记录',video,analysis})
    await saveReplay(otherOwner,{id:'shared-id',name:'另一条旧记录',video,analysis})
    await saveReplay(LOCAL_HISTORY_OWNER,{name:'无需登录的新记录',video,analysis})
    const original=IDBObjectStore.prototype.put
    IDBObjectStore.prototype.put=function(value){if(this.name==='content')throw new DOMException('simulated quota','QuotaExceededError');return original.call(this,value)}
    let quotaFailed=false
    try{await saveReplay(LOCAL_HISTORY_OWNER,{name:'不完整记录',video,analysis})}catch{quotaFailed=true}finally{IDBObjectStore.prototype.put=original}
    return {quotaFailed,count:(await listLocalHistory()).length,legacyCount:(await listHistory(legacyOwner)).length,bytes:(await readHistory(legacyOwner,a.id)).video.size}
  },{legacyOwner,otherOwner})
  assert.deepEqual(checked,{quotaFailed:true,count:3,legacyCount:1,bytes:clip.length})
  await page.reload()
  await page.getByRole('button',{name:'我的记录',exact:true}).click()
  await page.locator('.record-list').getByText('原账号的本机记录',{exact:true}).waitFor()
  await page.getByText('无需登录的新记录',{exact:true}).waitFor()
  const downloads=[];page.on('request',r=>{if(r.url().endsWith('.onnx'))downloads.push(r.url())})
  const row=page.locator('.record-list li').filter({hasText:'原账号的本机记录'})
  await row.getByRole('button',{name:'打开',exact:true}).click()
  await page.getByText('已保存的复盘',{exact:true}).waitFor()
  assert.equal(downloads.length,0)
  await page.getByRole('button',{name:'播放',exact:true}).click()
  await page.getByRole('button',{name:'暂停',exact:true}).waitFor()
  await page.getByRole('button',{name:'返回我的记录',exact:true}).click()
  await page.getByRole('button',{name:'删除记录：原账号的本机记录',exact:true}).click()
  await page.getByRole('button',{name:'取消',exact:true}).click()
  await row.getByText('原账号的本机记录',{exact:true}).waitFor()
  await page.getByRole('button',{name:'删除记录：原账号的本机记录',exact:true}).click()
  await page.getByRole('button',{name:'确认删除',exact:true}).click()
  await row.waitFor({state:'detached'})
  await page.getByText('另一条旧记录',{exact:true}).waitFor()
  await page.setViewportSize({width:1280,height:800})
  await page.screenshot({path:resolve(captures,'history-desktop.png'),fullPage:true})
  await page.getByRole('button',{name:'新建复盘',exact:true}).click()
  await page.getByRole('button',{name:'选择本地视频',exact:false}).waitFor()
  report.history={legacy_preserved:true,no_migration:true,reopen_without_models:true,quota_preserves_existing:true,delete_uses_owner_and_id:true}
  await writeFile(resolve(captures,'report.json'),JSON.stringify(report,null,2))
  await context.close()
})
