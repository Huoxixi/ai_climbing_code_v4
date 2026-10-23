export class LocalPoseEngine {
  constructor(onProgress=()=>{}) {
    this.worker=new Worker(new URL('./pose.worker.js',import.meta.url),{type:'module'})
    this.pending=new Map();this.nextId=0;this.onProgress=onProgress
    this.worker.onmessage=({data})=>{
      if(data.type==='progress'){this.onProgress(data);return}
      if(data.provider)this.provider=data.provider
      const request=this.pending.get(data.id)
      if(!request)return
      clearTimeout(request.timer);this.pending.delete(data.id)
      data.type==='error'?request.reject(new Error(data.message)):request.resolve(data.result)
    }
    this.worker.onerror=()=>this.close(new Error('本机计算未能启动。请重新准备模型，或使用电脑版 Chrome / Edge。'))
    this.worker.onmessageerror=()=>this.close(new Error('本机计算通信中断，请重新准备模型。'))
  }
  request(type,data={},transfer=[]) {
    if(this.closed)return Promise.reject(new Error('计算已停止，请重新准备模型。'))
    const id=++this.nextId
    return new Promise((resolve,reject)=>{
      const timer=setTimeout(()=>this.close(new Error('本机计算等待超时，请检查网络或重新准备模型。')),type==='initialize'?600000:120000)
      this.pending.set(id,{resolve,reject,timer})
      this.worker.postMessage({id,type,...data},transfer)
    })
  }
  initialize(){return this.request('initialize')}
  infer(type,image,box,metadata){return this.request(type,{image,box,metadata},[image.data.buffer])}
  close(reason=new DOMException('已停止本机计算','AbortError')) {
    this.closed=true;this.worker.terminate()
    for(const p of this.pending.values()){clearTimeout(p.timer);p.reject(reason)}
    this.pending.clear()
  }
}

export function waitForVideo(video,time,{signal,timeout=15000}={}) {
  return new Promise((resolve,reject)=>{
    if(signal?.aborted){reject(signal.reason);return}
    let timer
    const cleanup=()=>{clearTimeout(timer);video.removeEventListener('seeked',ready);video.removeEventListener('error',fail);signal?.removeEventListener('abort',abort)}
    const ready=()=>{cleanup();resolve()}
    const fail=()=>{cleanup();reject(new Error('浏览器无法解码这段视频，请使用 H.264 MP4 格式。'))}
    const abort=()=>{cleanup();reject(signal.reason)}
    if(Math.abs(video.currentTime-time)<.00001 && video.readyState>=2){resolve();return}
    timer=setTimeout(()=>{cleanup();reject(new Error('视频读取超时，请换用 H.264 MP4 格式。'))},timeout)
    video.addEventListener('seeked',ready,{once:true});video.addEventListener('error',fail,{once:true});signal?.addEventListener('abort',abort,{once:true})
    video.currentTime=time
  })
}

export function readVideoFrame(video,canvas) {
  canvas.width=video.videoWidth;canvas.height=video.videoHeight
  if(!canvas.width||!canvas.height)throw new Error('请等待视频预览就绪。')
  const ctx=canvas.getContext('2d',{willReadFrequently:true});ctx.drawImage(video,0,0)
  const {data,width,height}=ctx.getImageData(0,0,canvas.width,canvas.height)
  return {data,width,height}
}
