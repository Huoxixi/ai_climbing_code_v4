import test,{after} from 'node:test'
import assert from 'node:assert/strict'
import {spawn} from 'node:child_process'
import {setTimeout as delay} from 'node:timers/promises'
import {readdirSync,readFileSync,mkdirSync,writeFileSync} from 'node:fs'
import {createHash} from 'node:crypto'
import path from 'node:path'
import {fileURLToPath} from 'node:url'
import {chromium} from '@playwright/test'
import {startFixtureServer} from './fixtures/server.mjs'

const project=fileURLToPath(new URL('../../',import.meta.url))
const backend=path.join(project,'backend')
const python=path.join(process.env.USERPROFILE,'.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe')
const runtimePackages='D:/ai_climbing_code/desktop-deliveries/AiClimbing-0.1.14-replay.20261009/runtime/Lib/site-packages'
const root=path.join(project,'.tmp/video-preview-20261015',`real-browser-${process.pid}`)
mkdirSync(root,{recursive:true})
const target='http://127.0.0.1:4240'
const server=spawn(python,['scripts/verify_import_server.py','--root',root,'--port','4240'],{
  cwd:backend,env:{...process.env,PYTHONPATH:runtimePackages,LOCAL_ONLY:'true'},windowsHide:true,stdio:['ignore','pipe','pipe']})
let logs='';server.stdout.on('data',v=>logs+=v);server.stderr.on('data',v=>logs+=v)
after(async()=>{try{await fetch(target+'/__test/close',{method:'POST'})}catch{}server.kill()})
for(let i=0;i<100;i++){
  try{if((await fetch(target+'/api/health')).ok)break}catch{}
  if(server.exitCode!==null)throw new Error('Isolated import server failed: '+logs.slice(-500))
  await delay(100)
}
process.env.CLIMB_PREVIEW_BACKEND_TARGET=target
const base=await startFixtureServer(4241)
const browser=await chromium.launch({headless:true})
after(()=>browser.close())
const materials='D:/ai_climbing_code/素材'
const directory=path.join(materials,readdirSync(materials,{withFileTypes:true}).find(p=>p.isDirectory()&&p.name.includes('10')&&p.name.endsWith('_20261005')).name)
const files=readdirSync(directory).filter(name=>name.toLowerCase().endsWith('.mp4')).sort().map(name=>path.join(directory,name))
assert.equal(files.length,10)
const results=[]

test('all ten originals upload first and become usable color-picking previews',async()=>{
  const page=await browser.newPage({viewport:{width:1280,height:900}})
  const errors=[];page.on('pageerror',e=>errors.push(e.message))
  try{
    await page.goto(base+'/e2e/local-replay-harness.html')
    for(let index=0;index<files.length;index++){
      const file=files[index],checksum=createHash('sha256').update(readFileSync(file)).digest('hex')
      const uploaded=page.waitForResponse(r=>r.url().endsWith('/preview-video')&&r.request().method()==='POST',{timeout:180000})
      await page.locator('input[type=file]').setInputFiles(file)
      const response=await uploaded
      assert.equal(response.status(),200,`original ${index+1}: compatibility preparation failed`)
      await page.waitForFunction(()=>{const v=document.querySelector('video');return v?.readyState>=2&&v.videoWidth>0&&v.videoHeight>0},{},{timeout:30000})
      const pick=page.getByRole('button',{name:'从画面点选样本岩点',exact:true})
      await pick.waitFor();assert.equal(await pick.isEnabled(),true)
      assert.equal(await page.getByText('暂时无法预览视频',{exact:true}).count(),0)
      const video=await page.locator('video').evaluate(async v=>{
        v.pause();const at=Math.min(1,v.duration/2);const ready=new Promise(resolve=>v.addEventListener('seeked',resolve,{once:true}));v.currentTime=at;await ready
        const canvas=document.createElement('canvas');canvas.width=32;canvas.height=32;const ctx=canvas.getContext('2d');ctx.drawImage(v,0,0,32,32)
        const pixels=ctx.getImageData(0,0,32,32).data
        return {width:v.videoWidth,height:v.videoHeight,duration:v.duration,nonBlack:[...pixels].filter((value,i)=>i%4!==3&&value>12).length>100}
      })
      assert.equal(video.width,720);assert.equal(video.height,1280);assert.equal(video.nonBlack,true)
      assert.equal(createHash('sha256').update(readFileSync(file)).digest('hex'),checksum)
      results.push({index:index+1,...video,source_unchanged:true})
      assert.equal((await (await fetch(target+'/__test/stats')).json()).jobs,0)
    }
    assert.deepEqual(errors,[])
    const stats=await(await fetch(target+'/__test/stats')).json();assert.equal(stats.prepared,1)
    writeFileSync(path.join(root,'acceptance.json'),JSON.stringify({passed:10,results,jobs_started:stats.jobs},null,2))
  }finally{await page.close()}
})
