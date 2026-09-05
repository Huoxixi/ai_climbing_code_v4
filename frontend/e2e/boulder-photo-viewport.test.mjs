import test from 'node:test'
import assert from 'node:assert/strict'
import { createRequire } from 'node:module'
const require = createRequire(import.meta.url)
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || '@playwright/test')
const base = process.env.BOULDER_TEST_URL || 'http://127.0.0.1:4174'

test('zoomed photo: drag never adds objects; click coordinates remain in source image', async () => {
  const browser = await chromium.launch({headless:true})
  try {
    const page = await browser.newPage({viewport:{width:1440,height:1000}})
    await page.goto(`${base}/e2e/harness.html`)
    await page.locator('.route-v2__home button').first().click()
    await page.locator('.route-v2__sample-list button').first().click()
    await page.locator('.photo-review-viewer__viewport').waitFor({timeout:60000})
    await page.locator('.route-v2__color-list button').filter({hasText:'黄色'}).click()
    await page.getByRole('button',{name:'放大',exact:true}).click({clickCount:3})
    const group = page.locator('.route-v2__review-panel > details').first()
    await group.locator('summary').click()
    await page.getByRole('button',{name:'补加漏识别对象',exact:true}).click()
    const before = await page.locator('.route-v2__contours g[role=button]').count()
    const view = await page.locator('.photo-review-viewer__viewport').boundingBox()
    const point = {x:view.x+view.width/2,y:view.y+view.height/2}
    await page.mouse.move(point.x,point.y); await page.mouse.down()
    await page.mouse.move(point.x,point.y+60,{steps:8}); await page.mouse.up()
    assert.equal(await page.locator('.route-v2__contours g[role=button]').count(),before)
    const image = await page.locator('.route-v2__photo-stage').boundingBox()
    const uploaded = await page.locator('.route-v2__photo-stage > img').evaluate(img => ({width:img.naturalWidth,height:img.naturalHeight}))
    const expected = {x:(point.x-image.x)/image.width*uploaded.width,y:(point.y-image.y)/image.height*uploaded.height}
    const requestPromise = page.waitForRequest(request => request.method()==='POST' && /\/objects$/.test(request.url()))
    await page.mouse.click(point.x,point.y)
    const request = await requestPromise
    const contour = request.postDataJSON().contour
    assert.ok(Math.abs(contour.reduce((sum,p)=>sum+p[0],0)/4-expected.x)<1)
    assert.ok(Math.abs(contour.reduce((sum,p)=>sum+p[1],0)/4-expected.y)<1)
    assert.equal((await request.response()).status(),200)
  } finally { await browser.close() }
})

test('touch photo: two-finger pinch zooms without changing the photo objects', async () => {
  const browser = await chromium.launch({headless:true})
  try {
    const context = await browser.newContext({viewport:{width:390,height:844},isMobile:true,hasTouch:true})
    const page = await context.newPage()
    await page.goto(`${base}/e2e/harness.html`)
    await page.locator('.route-v2__home button').first().click()
    await page.locator('.route-v2__sample-list button').first().click()
    const viewport = page.locator('.photo-review-viewer__viewport')
    await viewport.waitFor({timeout:60000})
    await viewport.scrollIntoViewIfNeeded()
    const box = await viewport.boundingBox(), x=box.x+box.width/2, y=box.y+box.height/2
    const session = await context.newCDPSession(page)
    await session.send('Input.dispatchTouchEvent',{type:'touchStart',touchPoints:[{x:x-20,y,id:1},{x:x+20,y,id:2}]})
    await session.send('Input.dispatchTouchEvent',{type:'touchMove',touchPoints:[{x:x-50,y,id:1},{x:x+50,y,id:2}]})
    await session.send('Input.dispatchTouchEvent',{type:'touchEnd',touchPoints:[]})
    assert.ok(parseInt(await page.getByLabel('照片缩放比例').innerText())>100)
    await page.getByRole('button',{name:'完整显示',exact:true}).click()
    assert.equal(await page.getByLabel('照片缩放比例').innerText(),'100%')
  } finally { await browser.close() }
})
