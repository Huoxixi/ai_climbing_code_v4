import test from 'node:test'
import { createHash } from 'node:crypto'
import assert from 'node:assert/strict'
import { mkdir, readFile } from 'node:fs/promises'
import { createRequire } from 'node:module'
const require = createRequire(import.meta.url)
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || '@playwright/test')
const base = process.env.BOULDER_TEST_URL || 'http://127.0.0.1:4174'
const output = new URL('../test-results/boulder/', import.meta.url)
await mkdir(output, { recursive:true })

async function heading(page, text) {
  try { await page.locator('.route-v2__header h1').filter({ hasText:text }).waitFor({ timeout:60000 }) } catch (error) { console.log('Expected',text,'actual:',await page.locator('.route-v2').innerText()); throw error }
}
async function enabledClick(locator) {
  await locator.waitFor()
  for (let i=0; await locator.isDisabled() && i<100; i++) await new Promise(resolve => setTimeout(resolve, 50))
  assert.equal(await locator.isDisabled(), false, 'control must be enabled')
  await locator.click()
}
async function noOverflow(page) {
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1), false, 'page must not overflow horizontally')
}
async function shot(page, name) { await page.evaluate(() => { document.documentElement.style.scrollBehavior='auto'; window.scrollTo(0,0) }); await noOverflow(page); await page.screenshot({ path:new URL(`${name}.png`,output).pathname.replace(/^\/(\w:)/,'$1'), fullPage:true }) }

for (const device of ['desktop','mobile']) {
  test(`${device}: real samples, review, edit, failure recovery, library and physical canvas`, { timeout:300000 }, async () => {
    const browser = await chromium.launch({ headless:true })
    const context = await browser.newContext(device === 'mobile' ? { viewport:{ width:390,height:844 }, isMobile:true, hasTouch:true, deviceScaleFactor:1 } : { viewport:{ width:1440,height:1000 } })
    const page = await context.newPage(), errors=[]
    page.on('pageerror', error => errors.push(error.message))
    try {
      await page.goto(`${base}/e2e/harness.html`)
      await heading(page,'抱石线路')
      assert.equal(await page.locator('.route-v2__home button').count(),2)
      assert.equal(await page.locator('.mobile-asset-switch').count(),0)
      const nav = page.getByRole('navigation',{ name:device === 'mobile' ? '移动端导航' : '主导航', exact:true })
      assert.equal(await nav.getByRole('button',{name:'抱石线路',exact:true}).getAttribute('aria-current'),'page')
      await shot(page,`${device}-home`)

      for (const sample of [1,2]) {
        await page.locator('.route-v2__home button').first().click()
        await heading(page,'上传岩壁照片')
        if (sample===1) await shot(page,`${device}-upload`)
        const uploadRequest = page.waitForRequest(request => request.url().endsWith('/boards/upload') && request.method()==='POST')
        await page.locator('.route-v2__sample-list button').nth(sample-1).click()
        const request = await uploadRequest
        const uploaded = await (await request.response()).json()
        const sampleBytes = await readFile(new URL(`../src/assets/boulder-samples/boulder-${sample}.jpg`,import.meta.url))
        assert.ok(uploaded.board.original_asset.filename.startsWith(createHash('sha256').update(sampleBytes).digest('hex')), 'uploaded image must match the real sample')
        await heading(page,'复核识别结果')
        const viewport = page.locator('.photo-review-viewer__viewport')
        const image = page.locator('.route-v2__photo-stage')
        const viewportBox = await viewport.boundingBox(), imageBox = await image.boundingBox()
        assert.ok(imageBox.height <= viewportBox.height + 1 && imageBox.width <= viewportBox.width + 1, 'whole photo fits initially')
        await page.getByRole('button',{name:'放大',exact:true}).click()
        assert.ok((await image.boundingBox()).height > imageBox.height, 'zoom enlarges the actual photo and overlays')
        await page.getByRole('button',{name:'完整显示',exact:true}).click()
        assert.ok(Math.abs((await image.boundingBox()).height-imageBox.height)<1, 'fit resets zoom')
        assert.equal(await page.locator('.route-v2__review-panel').evaluate(el => getComputedStyle(el).overflowY), 'auto')
        const colors = page.locator('.route-v2__color-list button')
        assert.ok(await colors.count()>0,'real recognition must produce objects')
        await colors.filter({hasText:sample===1?'黄色':'蓝色'}).first().click()
        const contours=page.locator('.route-v2__contours g[role="button"]')
        const count=await contours.count()
        assert.ok(count>0)
        console.log(`${device} sample ${sample}: ${count} objects in selected color`)
        for (let i=0;i<count;i++) {
          await contours.nth(i).press('Enter')
          const confirm=page.getByRole('button',{name:'确认该对象与孔位',exact:true})
          if (await page.getByLabel('孔位（可多选）',{exact:true}).inputValue()==='') await enabledClick(page.locator('.route-v2__nearby-holes button').first())
          await enabledClick(confirm)
        }
        if (sample===1) await shot(page,`${device}-review`)
        await enabledClick(page.getByRole('button',{name:'确认复核，开始编辑',exact:true}))
        await heading(page,'编辑抱石线路')
        await page.getByRole('button',{name:'返回复核',exact:true}).click()
        await heading(page,'复核识别结果')
        await enabledClick(page.getByRole('button',{name:'确认复核，开始编辑',exact:true}))
        await heading(page,'编辑抱石线路')
        const wall=page.locator('.photo-technical-wall')
        const box=await wall.boundingBox()
        const footer=await page.locator('.route-v2__next').boundingBox()
        assert.ok(footer.y >= box.y+box.height-1, 'next-step controls must not cover the board')
        assert.ok(Math.abs(box.width/box.height - 6200/4100)<.015,'boulder wall must retain physical aspect ratio')
        assert.equal(await page.locator('.photo-reference-holes circle').count(),600)
        await page.getByLabel('定线者',{exact:true}).fill(`验收-${device}`)
        const name=`样例${sample}-${device}-${Date.now()}`
        await page.getByLabel('线路名称',{exact:true}).fill(name)
        const objects=page.locator('.photo-wall-object')
        await objects.first().press('Enter'); await page.getByLabel('起点',{exact:true}).check()
        await objects.last().press('Enter'); await page.getByLabel('终点',{exact:true}).check()
        if (sample===1) {
          await shot(page,`${device}-editor`)
          // A failed save must keep the user in the editor and retain input.
          await page.route('**/api/photo-routes/v2/routes/*', async route => {
            if (route.request().method()==='PUT') await route.fulfill({status:503,json:{detail:'验收：临时保存失败'}})
            else await route.continue()
          })
          await page.getByRole('button',{name:'保存完成，进入线路库',exact:true}).click()
          await page.getByRole('button',{name:'重试保存',exact:true}).waitFor()
          await heading(page,'编辑抱石线路')
          assert.equal(await page.getByLabel('线路名称',{exact:true}).inputValue(),name)
          await page.getByRole('button',{name:'返回复核',exact:true}).click()
          await heading(page,'编辑抱石线路')
          await page.unroute('**/api/photo-routes/v2/routes/*')
          await page.getByRole('button',{name:'重试保存',exact:true}).click()
        }
        await enabledClick(page.getByRole('button',{name:'保存完成，进入线路库',exact:true}))
        await heading(page,'抱石线路库')
        await page.getByRole('button',{name:new RegExp(name)}).first().click()
        await heading(page,'编辑抱石线路')
        assert.equal(await page.getByLabel('线路名称',{exact:true}).inputValue(),name)
        assert.equal(await page.getByLabel('线路名称',{exact:true}).isDisabled(),true)
        if (sample===1) {
          await page.getByRole('button',{name:'创建新草稿继续编辑',exact:true}).click()
          await page.getByLabel('线路名称',{exact:true}).waitFor()
          await page.getByLabel('线路备注',{exact:true}).fill('从已完成版本继续的草稿')
          await page.getByRole('button',{name:'存草稿并退出',exact:true}).click()
          await heading(page,'抱石线路库')
          await page.getByLabel('搜索线路',{exact:true}).fill(name)
          await page.waitForResponse(response => response.url().includes('/routes?search=') && response.ok())
          const checks=page.locator('.route-v2__route-list article input[type=checkbox]')
          await checks.first().check(); await checks.nth(1).check()
          await page.locator('.route-v2__overlay .photo-technical-wall').waitFor()
          assert.equal(await page.locator('.route-v2__overlay-legend > span').count(),2)
          await checks.first().uncheck(); await checks.nth(1).uncheck()
        } else await page.getByRole('button',{name:'返回线路库',exact:true}).click()
        await heading(page,'抱石线路库')
        if (sample===1) await shot(page,`${device}-library`)
        await page.getByRole('button',{name:'返回首页',exact:true}).click()
      }
      for (const label of ['板库','定线']) {
        await nav.getByRole('button',{name:label,exact:true}).click()
        const frame=page.locator('.board-frame')
        await frame.waitFor()
        await page.waitForFunction(() => document.querySelector('.board-frame').getBoundingClientRect().width>100)
        const size=await frame.boundingBox()
        assert.ok(Math.abs(size.width/size.height-2440/3660)<.015,'standard board must retain physical aspect ratio')
        const diameter=await page.locator('.board-hole').first().evaluate(el => parseFloat(getComputedStyle(el,'::after').width))
        assert.ok(diameter<5,'holes should be fine rather than heavy')
        await shot(page,`${device}-${label==='板库'?'board-library':'studio'}`)
      }
      await nav.getByRole('button',{name:'资产',exact:true}).click()
      assert.equal(await page.locator('.mobile-asset-switch button').count(),2)
      await noOverflow(page)
      assert.deepEqual(errors,[])
    } finally { await browser.close() }
  })
}

test('read-only upload controls respect editing permission', async () => {
  const browser=await chromium.launch({headless:true})
  try {
    const page=await browser.newPage()
    await page.goto(`${base}/e2e/harness.html?readonly=1`)
    await page.locator('.route-v2__home button').first().click()
    assert.equal(await page.getByRole('button',{name:'选择照片',exact:true}).isDisabled(),true)
    assert.equal(await page.locator('.route-v2__sample-list button').first().isDisabled(),true)
  } finally { await browser.close() }
})
