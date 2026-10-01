import test, { after } from 'node:test'
import assert from 'node:assert/strict'
import { createRequire } from 'node:module'
import { mkdir } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'
const require=createRequire(import.meta.url)
const {chromium}=require(process.env.PLAYWRIGHT_MODULE || '@playwright/test')
const browser=await chromium.launch({headless:true})
after(()=>browser.close())
const shots=new URL('../../.tmp/unified-replay-20260930/style-v4/',import.meta.url)
await mkdir(shots,{recursive:true})
for(const width of [1280,390]) test(`ending retains data in a usable orb at ${width}px`, async()=>{
  const page=await browser.newPage({viewport:{width,height:900}})
  try {
    await page.goto('http://127.0.0.1:8766/analysis/case3')
    await page.getByRole('button',{name:'数据回顾',exact:true}).click()
    await page.waitForFunction(()=>Array.from(document.querySelectorAll('.summary-route .summary-row')).length===3 && Array.from(document.querySelectorAll('.summary-route .summary-row')).every(row=>getComputedStyle(row).opacity==='1'))
    assert.deepEqual(await page.locator('.summary-route .summary-row > span').allTextContents(),['线路总岩点','使用岩点','使用岩点比例'])
    await page.screenshot({path:fileURLToPath(new URL(`preview-route-${width}.png`,shots)),fullPage:true})
    await page.getByRole('button',{name:'展开复盘数据',exact:true}).waitFor({timeout:22000})
    await page.getByLabel('基础数据',{exact:true}).waitFor({state:'detached'})
    await page.waitForFunction(()=>getComputedStyle(document.querySelector('.replay-data-orb')).opacity==='1')
    await page.screenshot({path:fileURLToPath(new URL(`preview-orb-${width}.png`,shots)),fullPage:true})
    const orb=await page.getByRole('button',{name:'展开复盘数据',exact:true}).boundingBox()
    const download=await page.getByRole('link',{name:'下载分析视频',exact:true}).boundingBox()
    assert.ok(orb.x+orb.width<=width)
    assert.ok(download.x+download.width<=orb.x || download.y+download.height<=orb.y || download.y>=orb.y+orb.height)
    await page.getByRole('button',{name:'展开复盘数据',exact:true}).click()
    assert.equal(await page.locator('.cinema-summary.pinned').count(),1)
    assert.equal(await page.getByText('未见 ≥1 秒',{exact:true}).count(),1)
    await page.waitForTimeout(20000)
    assert.equal(await page.locator('.cinema-summary.pinned').count(),1)
    await page.getByRole('button',{name:'收起复盘数据',exact:true}).click()
    await page.getByRole('button',{name:'展开复盘数据',exact:true}).waitFor()
    await page.getByRole('button',{name:'展开复盘数据',exact:true}).click()
    await page.getByLabel('基础数据',{exact:true}).press('Escape')
    await page.getByRole('button',{name:'展开复盘数据',exact:true}).waitFor()
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false)
  } finally { await page.close() }
})
