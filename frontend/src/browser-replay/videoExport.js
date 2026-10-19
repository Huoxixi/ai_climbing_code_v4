import {waitForVideo} from './localEngine.js'
import {drawReplayScene} from './replayDrawing.js'
import {validWallScene} from './wallGeometry.js'

const FPS=30,MAX_OUTPUT_BYTES=96*1024*1024
export function exportDimensions(width,height){
  const scale=Math.min(1,1920/Math.max(width,height))
  return {width:Math.max(2,Math.floor(width*scale/2)*2),height:Math.max(2,Math.floor(height*scale/2)*2)}
}

async function loadVideo(video,url,signal){
  signal.throwIfAborted()
  await new Promise((resolve,reject)=>{
    const timer=setTimeout(()=>finish(new Error('读取原视频超时，请重新打开记录后重试。')),15000)
    const abort=()=>finish(signal.reason),loaded=()=>finish(),error=()=>finish(new Error('无法解码原视频，请使用浏览器能播放的 H.264 MP4。'))
    function finish(reason){clearTimeout(timer);video.removeEventListener('loadeddata',loaded);video.removeEventListener('error',error);signal.removeEventListener('abort',abort);reason?reject(reason):resolve()}
    video.addEventListener('loadeddata',loaded,{once:true});video.addEventListener('error',error,{once:true});signal.addEventListener('abort',abort,{once:true});video.src=url;video.load()
  })
}

export async function exportReplayVideo({file,analysis,includeHuman=true,includeSkeleton=true,backgroundMode='dark',signal=new AbortController().signal,onProgress=()=>{}}){
  signal.throwIfAborted()
  if(!includeHuman&&!includeSkeleton)throw new Error('请至少开启“真人”或“骨架”，再导出视频。')
  if(!(file instanceof Blob)||!file.size||!analysis?.complete||!analysis.pose_samples?.length)throw new Error('请先完成一次骨架分析，或打开已保存的记录。')
  if(!includeHuman&&backgroundMode==='wall'&&!validWallScene(analysis.wall_scene))throw new Error('请先准备可用的无人墙面，或选择深色背景。')
  if(typeof VideoEncoder==='undefined'||typeof VideoFrame==='undefined')throw new Error('当前浏览器不支持本机视频导出，请使用新版电脑版 Chrome 或 Edge。')
  const {Output,Mp4OutputFormat,WebMOutputFormat,BufferTarget,CanvasSource,canEncodeVideo}=await import('mediabunny')
  signal.throwIfAborted()
  const video=document.createElement('video'),url=URL.createObjectURL(file),canvas=document.createElement('canvas')
  video.muted=true;video.playsInline=true;video.preload='auto'
  let output,abortOutput,encodedBytes=0,background
  try{
    onProgress({stage:'preparing',progress:0});await loadVideo(video,url,signal)
    if(!includeHuman&&backgroundMode==='wall')background=await createImageBitmap(analysis.wall_scene.image)
    const start=Number(analysis.start_seconds),end=Math.min(Number(analysis.end_seconds),video.duration)
    if(!Number.isFinite(start)||!Number.isFinite(end)||start<0||end<=start||end-start>90.001)throw new Error('这条记录的分析时间范围无效，请重新分析后导出。')
    const size=exportDimensions(video.videoWidth,video.videoHeight),bitrate=Math.round(Math.max(1e6,Math.min(6e6,size.width*size.height*FPS*.12)))
    canvas.width=size.width;canvas.height=size.height
    const config={width:size.width,height:size.height,bitrate,frameRate:FPS},codec=await canEncodeVideo('avc',config)?'avc':await canEncodeVideo('vp9',config)?'vp9':await canEncodeVideo('vp8',config)?'vp8':null
    signal.throwIfAborted()
    if(!codec)throw new Error('当前设备没有可用的视频编码器，请使用新版电脑版 Chrome 或 Edge。')
    const format=codec==='avc'?new Mp4OutputFormat({fastStart:'in-memory'}):new WebMOutputFormat(),target=new BufferTarget()
    output=new Output({format,target})
    const source=new CanvasSource(canvas,{codec,bitrate,keyFrameInterval:2,onEncodedPacket:packet=>{encodedBytes+=packet.data.byteLength;if(encodedBytes>MAX_OUTPUT_BYTES)throw new Error('导出文件超过本机内存保护范围，请缩短分析片段后重试。')}})
    output.addVideoTrack(source,{frameRate:FPS})
    abortOutput=()=>{output.cancel().catch(()=>{})};signal.addEventListener('abort',abortOutput,{once:true})
    await output.start();signal.throwIfAborted()
    const ctx=canvas.getContext('2d',{alpha:false}),duration=end-start,total=Math.max(1,Math.ceil(duration*FPS-1e-7))
    for(let i=0;i<total;i++){
      signal.throwIfAborted()
      const relative=i/FPS,time=start+relative,frameDuration=Math.min(1/FPS,duration-relative)
      // The original video is decoded only for modes that contain the person.
      if(includeHuman)await waitForVideo(video,time,{signal})
      drawReplayScene(ctx,{analysis,time,width:canvas.width,height:canvas.height,includeHuman,includeSkeleton,video,backgroundMode,background})
      await source.add(relative,frameDuration);signal.throwIfAborted()
      onProgress({stage:'encoding',progress:(i+1)/total,extension:codec==='avc'?'mp4':'webm'})
      // Yield for cancellation and UI updates without encoding in real time.
      if(i%8===0)await new Promise(resolve=>setTimeout(resolve,0))
    }
    onProgress({stage:'finalizing',progress:1});await output.finalize();signal.throwIfAborted()
    if(!target.buffer?.byteLength||target.buffer.byteLength>MAX_OUTPUT_BYTES)throw new Error('导出文件未能完整生成，请缩短片段后重试。')
    return {blob:new Blob([target.buffer],{type:format.mimeType}),extension:codec==='avc'?'mp4':'webm',duration,width:canvas.width,height:canvas.height,frames:total}
  }catch(error){await output?.cancel().catch(()=>{});if(signal.aborted)throw signal.reason;throw error}
  finally{background?.close();signal.removeEventListener('abort',abortOutput);video.pause();video.removeAttribute('src');video.load();URL.revokeObjectURL(url);canvas.width=0;canvas.height=0}
}
