import {waitForVideo,readVideoFrame} from './localEngine.js'
import {WALL_SCENE_VERSION} from './wallGeometry.js'

class WallRegistration{
  constructor(signal){
    this.worker=new Worker(new URL('./wall.worker.js',import.meta.url),{type:'module'});this.pending=new Map();this.id=0
    this.abort=()=>this.close(signal.reason);this.signal=signal;signal.addEventListener('abort',this.abort,{once:true})
    this.worker.onmessage=({data})=>{const p=this.pending.get(data.id);if(!p)return;this.pending.delete(data.id);clearTimeout(p.timer);data.error?p.reject(new Error(data.error)):p.resolve(data.result)}
    this.worker.onerror=()=>this.close(new Error('墙面处理无法启动，请重新尝试。'))
    this.worker.onmessageerror=()=>this.close(new Error('墙面处理通信中断，请重试。'))
  }
  request(type,image,boxes){
    this.signal.throwIfAborted()
    if(this.closed)throw new Error('墙面处理已结束，请重试。')
    const id=++this.id
    return new Promise((resolve,reject)=>{const timer=setTimeout(()=>this.close(new Error('墙面处理超时，请重试。')),60000);this.pending.set(id,{resolve,reject,timer});this.worker.postMessage({id,type,image,boxes},[image.data.buffer])})
  }
  close(error=new DOMException('已停止墙面处理','AbortError')){this.closed=true;this.worker.terminate();this.signal.removeEventListener('abort',this.abort);for(const p of this.pending.values()){clearTimeout(p.timer);p.reject(error)}this.pending.clear()}
}

export function* backgroundTimes(duration,frameTimes=[]){
  // Last decodable image, never seek to the end sentinel. Dense edges also
  // retain a one-frame empty scene; the rest of the full source follows.
  const last=Math.max(0,duration-1e-6),seen=new Set()
  const actual=frameTimes.filter(t=>Number.isFinite(t)&&t>=0&&t<duration).sort((a,b)=>a-b)
  function snap(time){
    if(!actual.length)return time
    let low=0,high=actual.length-1
    while(low<high){const mid=Math.ceil((low+high)/2);if(actual[mid]<=time)low=mid;else high=mid-1}
    const start=actual[low],next=actual[low+1]??duration
    return Math.min(last,start+Math.min(1e-4,(next-start)/4))
  }
  function* unique(values){for(const t of values){const time=snap(Math.max(0,Math.min(last,t))),key=actual.length?time:Math.round(time*3000);if(!seen.has(key)){seen.add(key);yield time}}}
  yield* unique([0,last,.1,.2,.4,.8,1.2,2,3,last-.1,last-.2,last-.4,last-.8,last-1.2,last-2,last-3])
  if(actual.length){const edge=actual.filter(t=>t<3||t>duration-3);for(let i=0;i<Math.ceil(edge.length/2);i++)yield* unique([edge[i],edge[edge.length-1-i]])}
  else for(let t=0;t<Math.min(3,duration);t+=1/30)yield* unique([t,last-t])
  for(let t=3;t<duration-3;t+=.5)yield* unique([t])
  if(actual.length)yield* unique(actual)
  else for(let t=3;t<duration-3;t+=1/30)yield* unique([t])
}
async function sourceFrameTimes(file,signal){
  // Read presentation timestamps only, without decoding or retaining encoded
  // frames. This covers single clean frames at any/VFR rate and the true tail.
  const {Input,BlobSource,ALL_FORMATS,EncodedPacketSink}=await import('mediabunny')
  signal.throwIfAborted()
  const input=new Input({source:new BlobSource(file),formats:ALL_FORMATS}),abort=()=>input.dispose()
  signal.addEventListener('abort',abort,{once:true})
  try{
    const track=await input.getPrimaryVideoTrack();if(!track)return []
    const sink=new EncodedPacketSink(track),times=[]
    for await(const packet of sink.packets(undefined,undefined,{metadataOnly:true})){signal.throwIfAborted();if(Number.isFinite(packet.timestamp))times.push(packet.timestamp)}
    return [...new Set(times)].sort((a,b)=>a-b)
  }catch(e){if(signal.aborted)throw signal.reason;return []}
  finally{signal.removeEventListener('abort',abort);if(!input.disposed)input.dispose()}
}
export async function prepareWallScene({file,analysis,engine,manualTime,signal=new AbortController().signal,onProgress=()=>{}}){
  const video=document.createElement('video'),url=URL.createObjectURL(file),canvas=document.createElement('canvas'),full=document.createElement('canvas'),registration=new WallRegistration(signal)
  video.muted=true;video.playsInline=true;video.preload='auto'
  const frame=()=>{const ratio=Math.min(1,960/Math.max(video.videoWidth,video.videoHeight));canvas.width=Math.round(video.videoWidth*ratio);canvas.height=Math.round(video.videoHeight*ratio);const ctx=canvas.getContext('2d',{willReadFrequently:true});ctx.drawImage(video,0,0,canvas.width,canvas.height);return ctx.getImageData(0,0,canvas.width,canvas.height)}
  try{
    signal.throwIfAborted()
    await new Promise((resolve,reject)=>{
      const timer=setTimeout(()=>finish(new Error('读取原片超时。')),15000),abort=()=>finish(signal.reason),ok=()=>finish(),fail=()=>finish(new Error('原片无法解码。'))
      function finish(e){clearTimeout(timer);video.removeEventListener('loadeddata',ok);video.removeEventListener('error',fail);signal.removeEventListener('abort',abort);e?reject(e):resolve()}
      video.addEventListener('loadeddata',ok,{once:true});video.addEventListener('error',fail,{once:true});signal.addEventListener('abort',abort,{once:true});video.src=url;video.load()
    })
    const observed=analysis.pose_samples.filter(s=>s.observed)
    if(!observed.length)throw new Error('这条记录尚无可靠骨架，请先确认人物并完成分析。')
    let chosen,checked=0
    const manual=Number.isFinite(manualTime)
    onProgress({stage:'index',message:'正在检查视频画面…'})
    const frameTimes=manual?[]:await sourceFrameTimes(file,signal)
    const times=manual?[Math.max(0,Math.min(video.duration-1e-6,manualTime))]:backgroundTimes(video.duration,frameTimes)
    for(const time of times){
      signal.throwIfAborted();await waitForVideo(video,time,{signal});checked++
      onProgress({stage:'search',checked,time,message:`正在检查无人墙面 · ${time.toFixed(2)} 秒 · 已查 ${checked} 帧`})
      const detection=await engine.infer('background',readVideoFrame(video,full));signal.throwIfAborted()
      if(!detection.empty){if(manual)throw new Error('这一帧检测到人物，请选择无人画面。');continue}
      const quality=await registration.request('reference',frame())
      if(quality.brightness<10||quality.contrast<12||quality.sharpness<30||quality.features<80){if(manual)throw new Error('这一帧过暗、模糊或纹理不足，请换一帧。');continue}
      // Check camera motion around the candidate without requiring the adjacent
      // frame to be empty (a single clean decoded frame may be sufficient).
      const neighbor=time+.1<video.duration?time+.1:Math.max(0,time-.1)
      await waitForVideo(video,neighbor,{signal})
      const stability=await registration.request('register',frame())
      if(!stability.valid||(!manual&&stability.displacement>8)){if(manual&&!stability.valid)throw new Error('这一帧无法与相邻墙面对齐，请换一帧。');if(!manual)continue}
      // A clean frame from another shot is not a usable background. Check
      // actual climbing observations before accepting it; keep searching if
      // none of the beginning/middle/end probes belongs to this wall view.
      let related=false
      for(const sample of [observed[0],observed[Math.floor(observed.length/2)],observed.at(-1)]){
        await waitForVideo(video,sample.time_seconds,{signal})
        const b=sample.box,w=analysis.video.width,h=analysis.video.height,boxes=sample.scene_exclusions||(b?[[b[0]/w,b[1]/h,b[2]/w,b[3]/h]]:[])
        if((await registration.request('register',frame(),boxes)).valid){related=true;break}
      }
      if(!related){if(manual)throw new Error('这一帧与攀爬画面不属于可可靠对齐的同一视角，请换一帧。');continue}
      await waitForVideo(video,time,{signal});readVideoFrame(video,full)
      const image=await new Promise((resolve,reject)=>full.toBlob(blob=>blob?resolve(blob):reject(new Error('无法保存墙面画面。')),'image/png'))
      chosen={image,source_time_seconds:time,selection:manual?'manual':'automatic',quality,stability:stability.diagnostics,checked_frames:checked};break
    }
    if(!chosen)throw new Error('未找到清晰、可对齐的无人画面。可以拖动视频，手动选择一帧重试。')
    const registrations=[];let examined=0
    for(const sample of observed){
      signal.throwIfAborted();await waitForVideo(video,sample.time_seconds,{signal})
      const b=sample.box,w=analysis.video.width,h=analysis.video.height
      const boxes=sample.scene_exclusions||(b?[[b[0]/w,b[1]/h,b[2]/w,b[3]/h]]:[])
      const result=await registration.request('register',frame(),boxes)
      registrations.push({time_seconds:sample.time_seconds,matrix:result.valid?result.matrix:null,diagnostics:result.diagnostics,reason:result.reason})
      examined++;onProgress({stage:'align',progress:examined/observed.length,message:`正在对齐骨架与墙面 · ${examined} / ${observed.length}`})
    }
    const aligned=registrations.filter(r=>r.matrix).length
    if(!aligned)throw new Error('已找到无人画面，但无法与攀爬片段可靠对齐，请换一帧。')
    return {version:WALL_SCENE_VERSION,status:'ready',...chosen,search_index:manual?'manual':frameTimes.length?'presentation-timestamps':'video-seek-fallback-30fps',width:video.videoWidth,height:video.videoHeight,registrations,aligned,observed:observed.length}
  }finally{registration.close();video.pause();video.removeAttribute('src');video.load();URL.revokeObjectURL(url);canvas.width=full.width=0;canvas.height=full.height=0}
}
