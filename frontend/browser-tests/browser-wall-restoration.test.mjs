import test from 'node:test'
import assert from 'node:assert/strict'
import {chromium} from '@playwright/test'
import {readFile,writeFile} from 'node:fs/promises'
import {resolve} from 'node:path'
import {startFixtureServer} from './fixtures/server.mjs'
const source=process.env.CLIMB_BROWSER_WALL_VIDEO,evidence=resolve(process.env.CLIMB_BROWSER_WALL_EVIDENCE||'../.tmp/wall-replay-20261019')

test('existing real poses gain a wall in place; cancellation, manual choice and last-frame search are safe',{skip:!source,timeout:480000},async()=>{
  const analysis=JSON.parse(await readFile(resolve(evidence,'analysis.json'),'utf8'));delete analysis.wall_scene
  const tailSample=analysis.pose_samples.find(s=>Math.abs(s.time_seconds-27.5)<.01)
  // Focused reruns can use a genuine contiguous 1.2-second portion of the
  // already verified browser observations, without fabricating or resampling.
  if(process.env.CLIMB_BROWSER_WALL_RESTORE_QUICK){analysis.pose_samples=analysis.pose_samples.slice(0,12);analysis.end_seconds=analysis.pose_samples.at(-1).time_seconds+.1}
  const video=await readFile(source),tail=await readFile(resolve(evidence,'tail-empty-fixture.mp4'))
  const base=await startFixtureServer(4356,process.env.CLIMB_BROWSER_WALL_RESTORE_URL,{args:['--config','vite.browser.config.js']})
  const browser=await chromium.launch({headless:true})
  try{
    const context=await browser.newContext({acceptDownloads:true}),page=await context.newPage(),errors=[]
    page.on('pageerror',e=>errors.push(e.message))
    await page.route('**/fixtures/source.mp4',r=>r.fulfill({body:video,contentType:'video/mp4'}))
    await page.route('**/*.onnx',r=>r.fulfill({status:503,body:'legacy records must open without models'}))
    await page.goto(base+'/browser-replay.html')
    await page.evaluate(async analysis=>{
      const {saveReplay,LOCAL_HISTORY_OWNER}=await import('/src/browser-replay/localHistory.js'),video=await(await fetch('/fixtures/source.mp4')).blob()
      await saveReplay(LOCAL_HISTORY_OWNER,{id:'shared-id',name:'另一个owner保持',video,analysis})
      await saveReplay('a'.repeat(32),{id:'shared-id',name:'旧记录墙面验收',video,analysis})
    },analysis)
    await page.getByRole('button',{name:'我的记录',exact:true}).click()
    await page.locator('.record-list li').filter({hasText:'旧记录墙面验收'}).getByRole('button',{name:'打开',exact:true}).click()
    await page.waitForFunction(()=>document.querySelector('video')?.readyState>=2)
    await page.unroute('**/*.onnx')
    await page.getByRole('button',{name:'寻找无人背景',exact:true}).click()
    await page.getByRole('button',{name:'停止寻找',exact:true}).click()
    await page.getByText('已停止，已有骨架和背景保留。',{exact:true}).waitFor({timeout:30000})
    assert.equal(await page.getByRole('button',{name:'寻找无人背景',exact:true}).isEnabled(),true)
    await page.locator('.playback-controls input').fill('0')
    await page.waitForFunction(()=>document.querySelector('video').currentTime<.01&&!document.querySelector('video').seeking)
    await page.getByRole('button',{name:'使用当前帧作为背景',exact:true}).click()
    await page.getByText(/无人背景：/).waitFor({timeout:180000})
    await page.getByRole('checkbox',{name:'真人',exact:true}).uncheck()
    const persisted=await page.evaluate(async()=>{
      const {readHistory}=await import('/src/browser-replay/localHistory.js'),old=await readHistory('a'.repeat(32),'shared-id'),other=await readHistory('0'.repeat(32),'shared-id')
      return {old:old.analysis,other:other.analysis,selection:old.analysis.wall_scene.selection,image:old.analysis.wall_scene.image.size}
    })
    assert.deepEqual(persisted.old.pose_samples,analysis.pose_samples);assert.deepEqual(persisted.other,analysis)
    assert.equal(persisted.selection,'manual');assert.ok(persisted.image>1000)
    await page.getByRole('button',{name:'重新寻找无人背景',exact:true}).click()
    await page.getByText(/无人背景：/).waitFor({timeout:180000})
    const automatic=await page.evaluate(async()=>{const {readHistory}=await import('/src/browser-replay/localHistory.js');const record=await readHistory('a'.repeat(32),'shared-id');return {index:record.analysis.wall_scene.search_index,time:record.analysis.wall_scene.source_time_seconds}})
    assert.equal(automatic.index,'presentation-timestamps');assert.ok(automatic.time<.01)
    await page.getByRole('button',{name:'重新寻找无人背景',exact:true}).click();await page.getByRole('button',{name:'停止寻找',exact:true}).click()
    await page.getByText('已停止，已有骨架和背景保留。',{exact:true}).waitFor()
    assert.equal(await page.getByLabel('骨架背景',{exact:true}).inputValue(),'wall')
    const captureTime=Number(Math.min(20,analysis.end_seconds-.2).toFixed(2))
    await page.locator('.playback-controls input').fill(String(captureTime))
    await page.waitForFunction(time=>Math.abs(document.querySelector('video').currentTime-time)<.01&&!document.querySelector('video').seeking,captureTime)
    await page.locator('.video-stage').screenshot({path:resolve(evidence,'manual-restored.png')})
    await page.close()

    // A controlled one-second fixture uses actual source images: a person in
    // the first half and a clean wall only in the last half. This tests search
    // behavior, not tracking quality or a second real climb.
    const probe=await context.newPage()
    await probe.route('**/fixtures/tail.mp4',r=>r.fulfill({body:tail,contentType:'video/mp4'}))
    await probe.route('**/fixtures/blank.html',r=>r.fulfill({contentType:'text/html',body:'<!doctype html><html></html>'}))
    await probe.goto(base+'/fixtures/blank.html')
    const sample=tailSample
    assert.ok(sample?.observed)
    const search=await probe.evaluate(async sample=>{
      const {LocalPoseEngine}=await import('/src/browser-replay/localEngine.js'),{prepareWallScene}=await import('/src/browser-replay/wallScene.js'),engine=new LocalPoseEngine()
      await engine.request('initialize',{forceCpu:true})
      const file=await(await fetch('/fixtures/tail.mp4')).blob(),analysis={complete:true,video:{width:720,height:1280,duration_seconds:1},pose_samples:[0,.1,.2].map(t=>({...sample,time_seconds:t}))}
      analysis.pose_samples[1]={...analysis.pose_samples[1],scene_exclusions:[[0,0,1,1]]}
      const before=JSON.stringify(analysis)
      try{
        const scene=await prepareWallScene({file,analysis,engine})
        const controller=new AbortController();let canceled=false
        try{await prepareWallScene({file,analysis,engine,signal:controller.signal,onProgress:()=>controller.abort(new DOMException('test cancel','AbortError'))})}catch(e){canceled=e.name==='AbortError'}
        return {time:scene.source_time_seconds,checked:scene.checked_frames,aligned:scene.aligned,matrices:scene.registrations.map(r=>r.matrix),canceled,raw_preserved:JSON.stringify(analysis)===before}
      }finally{engine.close()}
    },sample)
    assert.ok(search.time>.9);assert.equal(search.checked,2);assert.equal(search.aligned,2);assert.equal(search.matrices[1],null);assert.ok(search.canceled&&search.raw_preserved)
    assert.deepEqual(errors,[])
    await writeFile(resolve(evidence,'restoration-report.json'),JSON.stringify({legacy_observations:analysis.pose_samples.length,manual_selection:true,automatic,cancel_model_preparation:true,cancel_retains_wall:true,legacy_owner_preserved:true,other_owner_same_id_unchanged:true,poses_unchanged:true,tail_only_fixture:search},null,2))
    await context.close()
  }finally{await browser.close()}
})
