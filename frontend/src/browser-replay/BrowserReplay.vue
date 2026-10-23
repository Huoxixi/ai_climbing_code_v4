<template>
  <main class="browser-replay" :class="{'embedded-replay':embedded}">
    <header v-if="!embedded" class="page-heading">
      <a class="brand" href="/">攀岩助手<span>浏览器本地复盘 · 验证版</span></a>
      <span class="privacy-badge"><i></i>视频在你的设备上处理</span>
    </header>
    <div v-if="embedded" class="web-page-heading"><h1>视频复盘</h1><button v-if="record" type="button" class="web-secondary" @click="emit('back')">返回我的记录</button></div>
    <p v-if="embedded&&!record" class="browser-scope-note">本机处理，不上传视频。</p>
    <section v-if="!embedded" class="intro">
      <p class="eyebrow">打开网页，就在本机计算</p>
      <h1>把动作留下，<br />把视频留在自己手里。</h1>
      <p>无需安装。网页自动准备模型，使用这台设备识别骨架；你的视频不会上传到服务器。</p>
    </section>
    <section v-if="!record" class="engine-card" aria-labelledby="engine-title">
      <div class="engine-heading"><div><h2 id="engine-title">{{ ready ? '本机模型已就绪' : '准备本机模型' }}</h2><p v-if="!ready">{{ engineMessage }}</p></div><span v-if="ready" class="chip">{{ provider==='webgpu' ? '本机显卡' : '本机 CPU' }}</span></div>
      <progress v-if="preparing" :value="modelLoaded" :max="totalBytes" aria-label="模型准备进度"></progress>
      <div class="engine-details"><span>首次加载约 265 MB 模型，缓存后复用。</span><button v-if="!ready && !preparing" type="button" @click="prepare">重新准备模型</button><button v-if="preparing" type="button" @click="stop">停止准备</button></div>
      <p v-if="cacheWarning" class="notice">模型未能缓存，下次需重新加载。</p>
    </section>
    <section class="workbench" aria-labelledby="video-title">
      <div class="video-panel">
        <div class="section-heading"><h2 id="video-title">{{ fileName || '选择一段攀岩视频' }}</h2><button v-if="sourceUrl&&!record" type="button" class="text-button" :disabled="busy||saving" @click="fileInput?.click()">更换视频</button></div>
        <button v-if="!sourceUrl" class="drop-zone" type="button" @click="fileInput?.click()">
          <span class="upload-mark" aria-hidden="true"><Upload/></span><strong>选择本地视频</strong><span>建议 H.264 MP4 · 最大 500 MB</span><small>只读取本机文件，不上传</small>
        </button>
        <input id="video-file" ref="fileInput" class="sr-only" type="file" accept="video/*,.mp4,.mov,.m4v,.webm" :disabled="analyzing||detecting||exporting||wallPreparing||saving" @change="chooseFile" />
        <div v-show="sourceUrl" class="video-stage" :style="{'--source-ratio':loaded?video?.videoWidth/video?.videoHeight:1}">
          <video ref="video" :src="sourceUrl || undefined" :controls="!analyzing&&!detecting" playsinline preload="auto" :class="{'hide-human':!showHuman}" @loadeddata="videoReady" @timeupdate="draw" @seeked="seeked" @error="decodeError"></video>
          <canvas ref="overlay" :class="{selectable:selecting}" :aria-label="selecting ? '点击框选你要分析的人物' : '骨架叠加画面'" @click="selectPerson"></canvas>
        </div>
        <div v-if="sourceUrl" class="picture-controls"><label><input v-model="showHuman" type="checkbox" :disabled="!samples.length||exporting" />真人</label><label><input v-model="showSkeleton" type="checkbox" :disabled="!samples.length||exporting" @change="draw" />骨架</label><span>{{ samples.length ? '未检出或人物不确定的时刻留空' : '拖动视频到人物清晰可见的画面' }}</span></div>
        <div v-if="sourceUrl" class="playback-controls"><button type="button" :disabled="!loaded||analyzing||detecting" @click="togglePlayback">{{ playing ? '暂停' : '播放' }}</button><input type="range" min="0" :max="duration || 1" step="0.01" :value="playTime" :disabled="!loaded||analyzing||detecting" aria-label="视频播放位置" @input="seekTo" /><span>{{ playTime.toFixed(1) }} / {{ duration.toFixed(1) }} 秒</span></div>
        <div v-if="completed" class="wall-controls">
          <label>骨架背景<select v-model="backgroundMode" aria-label="骨架背景" :disabled="exporting||wallPreparing||saving"><option value="dark">深色</option><option value="wall" :disabled="!wallScene">真实墙面</option></select></label>
          <template v-if="!wallPreparing"><button type="button" :disabled="busy||saving" @click="prepareWall()">{{wallScene?'重新寻找无人背景':'寻找无人背景'}}</button><button type="button" :disabled="busy||saving||!loaded" @click="prepareWall(Math.min(playTime,Math.max(0,duration-1e-6)))">使用当前帧作为背景</button></template>
          <button v-else type="button" @click="cancelWall">停止寻找</button>
          <p v-if="wallPreparing" role="status">{{wallMessage}}</p><p v-else-if="wallScene" role="status">无人背景：{{wallScene.source_time_seconds.toFixed(2)}} 秒 · {{wallScene.aligned}} / {{wallScene.observed}} 个骨架观测已对齐{{wallScene.aligned<wallScene.observed?'，未对齐时刻留空':''}}</p>
          <p v-if="wallError" class="web-error" role="alert">{{wallError}}</p>
        </div>
      </div>
      <aside class="control-panel">
        <h2>{{record?'已保存的复盘':'准备复盘'}}</h2>
        <ol v-if="!record" class="steps"><li :class="{complete:!!sourceUrl}"><b>1</b><span>选择本地视频<small>浏览器需要能直接播放这段视频。</small></span></li><li :class="{complete:!!target}"><b>2</b><span>确认要分析的人物<small>暂停在清晰画面，识别人像后点选人物框。</small></span></li><li :class="{complete:completed}"><b>3</b><span>开始本机分析<small>从确认画面开始，最多处理 90 秒。</small></span></li></ol>
        <button v-if="!record" class="secondary" type="button" :disabled="!ready || !loaded || busy" @click="detect">{{ selecting ? '重新识别当前画面' : '识别当前画面的人物' }}</button>
        <div v-if="selecting && candidates.length" class="person-choices" aria-label="选择人物"><button v-for="(_,i) in candidates" :key="i" type="button" @click="setTarget(i)">人物 {{ i+1 }}</button></div>
        <p v-if="target" class="selection-note">已选人物 · 从 {{ targetTime.toFixed(1) }} 秒开始</p>
        <label v-if="!embedded" class="sampling">分析密度<select v-model.number="sampleFps" :disabled="busy"><option :value="10">每秒 10 次（与 App 默认相同）</option><option :value="5">每秒 5 次（计算较少）</option><option :value="2">每秒 2 次（快速预览）</option></select></label>
        <button v-if="!record" class="primary" type="button" :disabled="!ready || !target || busy || saving" @click="analyze">{{ completed ? '重新分析' : '开始本机分析' }}</button>
        <button v-if="analyzing||detecting" class="secondary" type="button" @click="stop">停止计算</button>
        <div class="analysis-status" role="status" aria-live="polite"><p>{{ status }}</p><progress v-if="analyzing" :value="analysisProgress" max="1" aria-label="视频分析进度"></progress></div>
        <p v-if="error" class="error" role="alert">{{ error }}</p>
        <div v-if="completed" class="result-note"><strong>本机分析完成</strong><span>{{ samples.length }} 个采样时刻 · {{ observedCount }} 次骨架观测</span><span role="status">{{saving?'正在保存本机记录…':saved?'已保存到本机“我的记录”':''}}</span><p v-if="saveError" class="web-error" role="alert">{{saveError}}</p><button v-if="saveError" type="button" :disabled="saving" @click="saveLocal">重新保存记录</button><button type="button" @click="exportData">保存骨架数据</button></div>
        <section v-if="completed" class="export-panel" aria-labelledby="export-title">
          <h2 id="export-title">导出复盘视频</h2>
          <p>当前画面 · {{exportDuration.toFixed(1)}} 秒 · 无声</p>
          <p class="muted">优先 MP4，设备不支持时使用 WebM。最长边不超过 1920 像素。</p>
          <button v-if="!exporting" type="button" class="primary" :disabled="!loaded||busy||saving||(!showHuman&&!showSkeleton)" @click="exportVideo">导出视频</button>
          <button v-else type="button" class="secondary" @click="cancelExport">取消导出</button>
          <p v-if="!showHuman&&!showSkeleton" class="muted">请至少开启“真人”或“骨架”。</p>
          <progress v-if="exporting" :value="exportProgress" max="1" aria-label="视频导出进度"></progress>
          <p v-if="exportStatus" role="status">{{exportStatus}}</p><p v-if="exportError" class="web-error" role="alert">{{exportError}}</p>
          <a v-if="exportUrl" :href="exportUrl" :download="exportName" class="export-download">下载已生成的视频（{{exportExtension.toUpperCase()}}）</a>
        </section>
      </aside>
    </section>
  </main>
</template>
<script setup>
import {computed,nextTick,onBeforeUnmount,onMounted,ref,shallowRef,watch} from 'vue'
import {Upload} from '@element-plus/icons-vue'
import {LocalPoseEngine,waitForVideo,readVideoFrame} from './localEngine.js'
import {MODEL_FILES,MODEL_VERSION} from './modelManifest.js'
import {continueTarget} from './poseMath.js'
import {drawReplayScene} from './replayDrawing.js'
import {prepareWallScene} from './wallScene.js'
import {validWallScene} from './wallGeometry.js'
import {exportReplayVideo} from './videoExport.js'
import {saveReplay,LOCAL_HISTORY_OWNER} from './localHistory.js'
const props=defineProps({embedded:Boolean,record:Object})
const emit=defineEmits(['saved','busy','back'])
const saving=ref(false),saved=ref(false),saveError=ref('')
const exporting=ref(false),exportProgress=ref(0),exportStatus=ref(''),exportError=ref(''),exportUrl=ref(''),exportName=ref(''),exportExtension=ref('')
let exportController
const exportDuration=computed(()=>completed.value?Math.max(0,Number(analysisMeta?.end_seconds||0)-Number(analysisMeta?.start_seconds||0)):0)
let currentFile,savedRecordId,savedOwner=LOCAL_HISTORY_OWNER
const wallScene=shallowRef(null),wallPreparing=ref(false),wallMessage=ref(''),wallError=ref(''),backgroundMode=ref('dark')
let wallController,wallImage

const video=ref(),overlay=ref(),fileInput=ref(),sourceUrl=ref(''),fileName=ref(''),ready=ref(false),preparing=ref(false),provider=ref(''),engineMessage=ref('正在准备模型…'),cacheWarning=ref(false)
const modelProgress=ref({}),totalBytes=MODEL_FILES.reduce((s,f)=>s+f.bytes,0),modelLoaded=computed(()=>Object.values(modelProgress.value).reduce((s,v)=>s+v,0))
const loaded=ref(false),detecting=ref(false),analyzing=ref(false),selecting=ref(false),candidates=ref([]),target=ref(null),targetTime=ref(0),sampleFps=ref(10),samples=ref([]),completed=ref(false),status=ref('模型准备期间也可以选择视频。'),error=ref(''),analysisProgress=ref(0),showHuman=ref(true),showSkeleton=ref(true),playTime=ref(0),playing=ref(false),duration=ref(0)
const busy=computed(()=>preparing.value||detecting.value||analyzing.value||exporting.value||wallPreparing.value),observedCount=computed(()=>samples.value.filter(s=>s.observed).length)
// Background model loading must not prevent opening an existing local record.
watch([detecting,analyzing,exporting,saving,wallPreparing],()=>emit('busy',detecting.value||analyzing.value||exporting.value||saving.value||wallPreparing.value),{immediate:true})
let engine,decoder,controller,generation=0,destroyed=false,analysisMeta
const scratch=document.createElement('canvas')
function progress(data){
  if(data.loaded!=null){modelProgress.value={...modelProgress.value,[data.name]:data.loaded};engineMessage.value=data.cached?'正在复用已缓存模型…':`正在加载模型 · ${(modelLoaded.value/1e6).toFixed(1)} / ${(totalBytes/1e6).toFixed(1)} MB`}
  if(data.stored===false)cacheWarning.value=true
  if(data.stage==='compiling')engineMessage.value='正在启动识别…'
  if(data.stage==='fallback'){provider.value='wasm';engineMessage.value=data.message;status.value=data.message}
}
async function prepare(){
  const token=++generation
  engine?.close();ready.value=false;preparing.value=true;error.value='';modelProgress.value={};cacheWarning.value=false
  if(!window.isSecureContext||!crypto.subtle){error.value='请通过 HTTPS 网站或本机 localhost 打开此页面。';preparing.value=false;return}
  engine=new LocalPoseEngine(progress)
  try{const result=await engine.initialize();if(token!==generation)return;provider.value=result.provider;ready.value=true;engineMessage.value='模型已在这台设备就绪，识别过程无需服务器算力。';status.value=target.value?'人物已确认，可以开始本机分析。':'选择视频并确认要分析的人物。'}
  catch(e){if(token===generation){error.value=e.message;engineMessage.value='准备失败，请重试。'}}
  finally{if(token===generation)preparing.value=false}
}
async function chooseFile(event){
  if(analyzing.value||detecting.value||exporting.value||wallPreparing.value||saving.value)return
  const file=event.target.files?.[0];if(!file)return
  if(file.size>500*1024*1024){error.value='视频超过 500 MB，请选择较短片段。';event.target.value='';return}
  clearExport();clearWall();currentFile=file;saved.value=false;savedRecordId=undefined;savedOwner=LOCAL_HISTORY_OWNER;saveError.value=''
  if(sourceUrl.value)URL.revokeObjectURL(sourceUrl.value)
  decoder?.pause();decoder?.removeAttribute('src');decoder?.load()
  sourceUrl.value=URL.createObjectURL(file);fileName.value=file.name;loaded.value=false;candidates.value=[];target.value=null;samples.value=[];completed.value=false;selecting.value=false;showHuman.value=true;error.value='';status.value='正在读取本地视频…'
  await nextTick();draw();event.target.value=''
}
function videoReady(){
  if(!(video.value?.duration>0&&Number.isFinite(video.value.duration))){error.value='无法读取视频时长，请使用 H.264 MP4。';return}
  if(video.value.videoWidth*video.value.videoHeight>3840*2160){error.value='当前验证版支持最高约 4K 画面，请先使用较低分辨率片段。';loaded.value=false;return}
  loaded.value=true;duration.value=video.value.duration;status.value=props.record?'已从当前浏览器读取记录，可直接回放，无需重新识别。':'拖动到人物清晰可见的画面，再点击“识别当前画面的人物”。';draw()
  if(props.record&&Math.abs(video.value.currentTime-targetTime.value)>.01)video.value.currentTime=targetTime.value
}
async function togglePlayback(){if(playing.value)video.value.pause();else{if(selecting.value){selecting.value=false;candidates.value=[]}await video.value.play().catch(()=>{error.value='视频暂时无法播放，请重新选择。'})}playing.value=!video.value.paused}
function seekTo(event){video.value.currentTime=Number(event.target.value)}
function decodeError(){if(sourceUrl.value){loaded.value=false;error.value='浏览器无法播放此视频。请使用 H.264 MP4；此页面不会把视频传到服务器转换。'}}
function seeked(){if(selecting.value){selecting.value=false;candidates.value=[];status.value='画面已变化，请重新识别当前画面的人物。'}draw()}
async function detect(){
  const token=generation;detecting.value=true;error.value='';target.value=null;completed.value=false;samples.value=[];video.value.pause()
  const time=video.value.currentTime
  try{
    const boxes=await engine.infer('detect',readVideoFrame(video.value,scratch));if(token!==generation)return
    provider.value=engine.provider
    if(Math.abs(video.value.currentTime-time)>.01){status.value='画面已变化，请重新识别。';return}
    candidates.value=boxes;targetTime.value=time;selecting.value=true
    status.value=boxes.length?'点击画面中的人物框，或下方人物按钮。':'当前画面未检出清晰人物。请拖动到其他时刻重试。';draw()
  }catch(e){if(token===generation)error.value=e.message}finally{if(token===generation)detecting.value=false}
}
function setTarget(index){
  if(Math.abs(video.value.currentTime-targetTime.value)>.01){selecting.value=false;candidates.value=[];status.value='画面已变化，请重新识别当前画面的人物。';draw();return}
  target.value=candidates.value[index].box.slice();selecting.value=false;status.value='人物已确认，可以开始本机分析。';draw()
}
function selectPerson(event){
  if(!selecting.value)return
  const r=overlay.value.getBoundingClientRect(),x=(event.clientX-r.left)/r.width*overlay.value.width,y=(event.clientY-r.top)/r.height*overlay.value.height
  const index=candidates.value.findIndex(({box:b})=>x>=b[0]&&x<=b[2]&&y>=b[1]&&y<=b[3]);if(index>=0)setTarget(index)
}
async function decoderReady(signal){
  decoder=document.createElement('video');decoder.muted=true;decoder.playsInline=true;decoder.preload='auto';decoder.src=sourceUrl.value
  await new Promise((resolve,reject)=>{
    const timer=setTimeout(()=>finish(new Error('本地视频读取超时。')),15000)
    const abort=()=>finish(signal.reason),fail=()=>finish(new Error('浏览器无法解码此视频，请使用 H.264 MP4。')),ok=()=>finish()
    function finish(e){clearTimeout(timer);decoder.removeEventListener('loadeddata',ok);decoder.removeEventListener('error',fail);signal.removeEventListener('abort',abort);e?reject(e):resolve()}
    decoder.addEventListener('loadeddata',ok,{once:true});decoder.addEventListener('error',fail,{once:true});signal.addEventListener('abort',abort,{once:true});decoder.load()
  })
}
async function analyze(){
  clearExport();clearWall()
  savedRecordId=undefined;saved.value=false;saveError.value=''
  const token=generation;controller=new AbortController();analyzing.value=true;completed.value=false;samples.value=[];error.value='';analysisProgress.value=0;video.value.pause()
  const start=targetTime.value,end=Math.min(video.value.duration,start+90),fps=sampleFps.value,total=Math.ceil((end-start)*fps)
  if(total<1){error.value='请在视频结束前选择人物。';analyzing.value=false;return}
  let previous=target.value.slice(),lastSeen=start
  analysisMeta={version:'browser-pose-accepted-19.2-v1',algorithm_baseline:'0.1.17-local.20261019.2',image_observation_refinement:'rotated-source-observation-v3',temporal_display:'bidirectional-image-pose-consensus-v3',model:MODEL_VERSION,start_seconds:start,end_seconds:end,sample_fps:fps,tracking:'manual-anchor-conservative-source-iou-v1',complete:false,video_uploaded:false}
  try{
    await decoderReady(controller.signal)
    await engine.request('reset-sequence')
    for(let i=0;i<total;i++){
      controller.signal.throwIfAborted()
      const time=start+i/fps;await waitForVideo(decoder,time,{signal:controller.signal})
      let box=i===0?previous:null,detections=[]
      if(i>0&&time-lastSeen<=.6){
        detections=await engine.infer('detect',readVideoFrame(decoder,scratch));box=continueTarget(detections,previous)?.box
      }
      const sample={time_seconds:time,source_frame_id:i,observed:false}
      if(box){
        const pose=await engine.infer('pose',readVideoFrame(decoder,scratch),box,{time,index:i,track:1})
        if(pose.previous_display){const prior=samples.value[pose.previous_display.index];if(prior?.observed)prior.temporal_display=pose.previous_display.payload}
        sample.primary_native=pose.primary_native;sample.image_observation_refinement=pose.image_observation_refinement
        sample.observed=true;sample.box=box;sample.kpts_xy=pose.points.slice(0,17);sample.kpts_score=pose.scores.slice(0,17);sample.joint_eligibility=pose.eligible.slice(0,17)
        sample.wholebody={schema:'coco-wholebody-133',coordinates:'source_image_normalized',kpts_xy:pose.points,kpts_score:pose.scores,joint_eligibility:pose.eligible}
        sample.scene_exclusions=(detections.length?detections.map(d=>d.box):[box]).map(b=>b.map((v,j)=>v/(j%2?decoder.videoHeight:decoder.videoWidth)))
        previous=box;lastSeen=time
      }else{sample.missing_reason=time-lastSeen>.6?'target_lost_requires_new_anchor':'missing_or_ambiguous_detection';await engine.request('missing')}
      if(token!==generation)return
      samples.value.push(sample);analysisProgress.value=(i+1)/total;provider.value=engine.provider
      status.value=`正在本机分析 ${i+1} / ${total} · ${time.toFixed(1)} 秒${box?'':' · 当前人物不确定，留空'}`
    }
    analysisMeta.complete=true;analysisMeta.provider=engine.provider;completed.value=true;status.value='已完成，可以播放或拖动视频查看骨架。'
    await saveLocal()
    await waitForVideo(video.value,start,{signal:controller.signal});draw()
  }catch(e){if(token===generation)error.value=e.message}
  finally{if(token===generation){analyzing.value=false;if(!engine?.closed)await engine?.request('reset-sequence')}decoder?.pause();decoder?.removeAttribute('src');decoder?.load()}
  if(completed.value&&token===generation)await prepareWall()
}
function stop(){
  if(wallPreparing.value){cancelWall();return}
  generation++;controller?.abort();engine?.close();ready.value=false;preparing.value=false;analyzing.value=false;detecting.value=false;completed.value=false;samples.value=[];error.value='';engineMessage.value='已停止。重新准备时会复用已保存的模型缓存。';status.value='已停止本机计算。';draw()
}
function draw(){
  const canvas=overlay.value,v=video.value;if(!canvas||!v?.videoWidth)return
  playTime.value=v.currentTime;playing.value=!v.paused
  if(canvas.width!==v.videoWidth||canvas.height!==v.videoHeight){canvas.width=v.videoWidth;canvas.height=v.videoHeight}
  const ctx=canvas.getContext('2d');ctx.clearRect(0,0,canvas.width,canvas.height)
  const scale=Math.max(1,canvas.width/700)
  if(selecting.value){
    candidates.value.forEach(({box:b},i)=>{ctx.strokeStyle='#f1d04b';ctx.lineWidth=3*scale;ctx.strokeRect(b[0],b[1],b[2]-b[0],b[3]-b[1]);ctx.fillStyle='#f1d04b';ctx.font=`bold ${18*scale}px sans-serif`;ctx.fillText(`人物 ${i+1}`,b[0]+5*scale,Math.max(23*scale,b[1]-8*scale))});return
  }
  if(!samples.value.length)return
  // Human playback remains the actual video layer; the overlay shares the same
  // compositor as export and draws the selected wall only when human is hidden.
  drawReplayScene(ctx,{analysis:{...analysisMeta,pose_samples:samples.value,wall_scene:wallScene.value},time:v.currentTime,width:canvas.width,height:canvas.height,includeHuman:showHuman.value,includeSkeleton:showSkeleton.value,backgroundMode:backgroundMode.value,background:wallImage})
}
function clearExport(){if(exportUrl.value)URL.revokeObjectURL(exportUrl.value);exportUrl.value='';exportName.value='';exportStatus.value='';exportError.value=''}
watch([showHuman,showSkeleton,backgroundMode],()=>{if(!exporting.value)clearExport();draw()})
function clearWall(){wallController?.abort(new DOMException('画面已更换','AbortError'));wallImage?.close();wallImage=null;wallScene.value=null;backgroundMode.value='dark';wallError.value=''}
function cancelWall(){wallController?.abort(new DOMException('已取消墙面准备','AbortError'));if(preparing.value){generation++;engine?.close();preparing.value=false;ready.value=false}}
async function prepareWall(manualTime){
  if(busy.value||saving.value||!completed.value)return
  clearExport();wallPreparing.value=true;wallError.value='';wallMessage.value='正在准备无人墙面检查…';wallController=new AbortController()
  const signal=wallController.signal
  video.value.pause();draw()
  try{
    if(!ready.value){await prepare();signal.throwIfAborted();if(!ready.value)throw new Error(error.value||'请先准备人物模型。')}
    const scene=await prepareWallScene({file:currentFile,analysis:analysisPayload(),engine,manualTime,signal,onProgress:s=>wallMessage.value=s.message})
    signal.throwIfAborted()
    const bitmap=await createImageBitmap(scene.image)
    if(signal.aborted||destroyed){bitmap.close();signal.throwIfAborted();return}
    wallImage?.close();wallImage=bitmap;wallScene.value=scene;backgroundMode.value='wall';draw();await saveLocal()
  }catch(e){if(!destroyed)wallError.value=e.name==='AbortError'?'已停止，已有骨架和背景保留。':e.message}
  finally{wallPreparing.value=false;wallController=null}
}
function cancelExport(){exportController?.abort(new DOMException('已取消导出','AbortError'))}
async function exportVideo(){
  if(busy.value||saving.value||!completed.value)return
  clearExport();exporting.value=true;exportProgress.value=0;exportError.value='';exportStatus.value='正在准备本机视频编码…';exportController=new AbortController();video.value.pause()
  const includeHuman=showHuman.value,includeSkeleton=showSkeleton.value
  try{
    const result=await exportReplayVideo({file:currentFile,analysis:analysisPayload(),includeHuman,includeSkeleton,backgroundMode:backgroundMode.value,signal:exportController.signal,onProgress:state=>{exportProgress.value=state.progress;exportStatus.value=state.stage==='finalizing'?'正在完成视频文件…':state.stage==='encoding'?`正在导出 ${Math.round(state.progress*100)}%`:'正在准备本机视频编码…'}})
    if(destroyed)return
    if(exportUrl.value)URL.revokeObjectURL(exportUrl.value)
    exportUrl.value=URL.createObjectURL(result.blob);exportExtension.value=result.extension
    const label=includeHuman?(includeSkeleton?'真人与骨架':'真人'):(backgroundMode.value==='wall'?'真实墙面纯骨架':'纯骨架'),base=fileName.value.replace(/\.[^.]+$/,'').replace(/[<>:"/\\|?*\x00-\x1f]/g,'_').slice(0,100)||'攀岩复盘'
    exportName.value=`${base}-${label}.${result.extension}`
    exportStatus.value=`视频已生成（${result.extension.toUpperCase()}），如果未自动下载，请点击下方链接。`
    const link=document.createElement('a');link.href=exportUrl.value;link.download=exportName.value;link.click()
  }catch(e){if(destroyed)return;if(e.name==='AbortError')exportStatus.value='已取消导出，原视频和本机记录保留。';else{exportStatus.value='';exportError.value=e.message||'导出失败，请重试。'}}
  finally{exporting.value=false;exportController=null}
}
function exportData(){
  if(!completed.value)return
  const payload=analysisPayload()
  if(payload.wall_scene){const {image,...metadata}=payload.wall_scene;payload.wall_scene={...metadata,image_saved_in_local_history:true}}
  const url=URL.createObjectURL(new Blob([JSON.stringify(payload)],{type:'application/json'})),link=document.createElement('a')
  link.href=url;link.download='climbing-local-skeleton.json';link.click();setTimeout(()=>URL.revokeObjectURL(url),1000)
}
function analysisPayload(){return {...analysisMeta,wall_scene:wallScene.value||undefined,video:{width:video.value.videoWidth,height:video.value.videoHeight,duration_seconds:video.value.duration},pose_samples:JSON.parse(JSON.stringify(samples.value))}}
async function saveLocal(){
  if(!completed.value||!currentFile)return
  saving.value=true;saveError.value=''
  try{const result=await saveReplay(savedOwner,{id:savedRecordId,name:fileName.value,video:currentFile,analysis:analysisPayload()});savedRecordId=result.id;saved.value=true;emit('saved',result)}
  catch(e){saved.value=false;saveError.value=e.message}
  finally{saving.value=false}
}
let animation
function tick(){if(destroyed)return;if(video.value&&!video.value.paused)draw();animation=requestAnimationFrame(tick)}
onMounted(()=>{
  if(props.record){
    const record=props.record,analysis=record.analysis
    currentFile=record.video;savedRecordId=record.id;savedOwner=record.owner;sourceUrl.value=URL.createObjectURL(record.video);fileName.value=record.name
    analysisMeta={...analysis};delete analysisMeta.pose_samples;delete analysisMeta.video;delete analysisMeta.wall_scene
    if(validWallScene(analysis.wall_scene)){
      wallScene.value=analysis.wall_scene;backgroundMode.value='wall'
      createImageBitmap(analysis.wall_scene.image).then(bitmap=>{if(destroyed){bitmap.close();return}wallImage=bitmap;draw()}).catch(()=>{wallError.value='无人背景读取失败，可重新寻找。';backgroundMode.value='dark'})
    }
    targetTime.value=analysis.start_seconds;sampleFps.value=analysis.sample_fps;samples.value=analysis.pose_samples;completed.value=true;saved.value=true;status.value='正在读取本机记录…'
  }else prepare()
  tick()
})
onBeforeUnmount(()=>{destroyed=true;generation++;controller?.abort();clearWall();cancelExport();clearExport();engine?.close();cancelAnimationFrame(animation);decoder?.pause();decoder?.removeAttribute('src');decoder?.load();if(sourceUrl.value)URL.revokeObjectURL(sourceUrl.value)})
</script>
