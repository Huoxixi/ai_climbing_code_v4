import * as ort from 'onnxruntime-web/webgpu'
import wasmUrl from 'onnxruntime-web/ort-wasm-simd-threaded.jsep.wasm?url'
import wasmModuleUrl from 'onnxruntime-web/ort-wasm-simd-threaded.jsep.mjs?url'
import {MODEL_FILES,MODEL_VERSION} from './modelManifest.js'
import {loadModel} from './modelCache.js'
import {detectorInput,decodeDetector,poseInput,decodePose} from './poseMath.js'

ort.env.wasm.numThreads=1 // Works without cross-origin isolation, including static hosting.
ort.env.wasm.wasmPaths={wasm:wasmUrl,mjs:wasmModuleUrl}
ort.env.logLevel='error'
let sessions={},provider='wasm'
let currentRequest
const progress=data=>self.postMessage({id:currentRequest,type:'progress',...data})

async function release() {
  for(const session of Object.values(sessions))await session.release().catch(()=>{})
  sessions={}
}
async function initialize(forceCpu=false) {
  await release()
  let gpu=false
  if(!forceCpu)try{gpu=!!(await self.navigator.gpu?.requestAdapter())}catch{/* CPU */}
  provider=gpu?'webgpu':'wasm'
  try{
    for(const file of MODEL_FILES){
      const buffer=await loadModel(file,{onProgress:progress})
      progress({stage:'compiling',name:file.name,provider})
      sessions[file.name]=await ort.InferenceSession.create(buffer,{executionProviders:[provider],graphOptimizationLevel:'all'})
    }
  }catch(error){
    await release()
    if(gpu){progress({stage:'fallback',message:'本机显卡暂不可用，正在切换到本机 CPU。'});return initialize(true)}
    throw error
  }
  return {provider,model:MODEL_VERSION}
}
async function run(model,input) {
  const session=sessions[model]
  if(!session)throw new Error('请先准备模型。')
  const tensor=new ort.Tensor('float32',input.data,input.dims)
  try{
    // The pinned human detector also returns int64 labels. It has one class;
    // fetch only its packed float boxes/scores, as the native adapter does.
    const names=model==='detector'?session.outputNames.slice(0,1):session.outputNames
    const result=await session.run({[session.inputNames[0]]:tensor},names)
    try{return names.map(name=>({data:Float32Array.from(result[name].data),dims:result[name].dims}))}
    finally{for(const value of Object.values(result))value.dispose()}
  }finally{tensor.dispose()}
}
async function infer(message) {
  if(message.type==='background'){
    // Absence of pose is not evidence of an empty scene. Independently inspect
    // the full frame and overlapping crops, including partial/edge people.
    const image=message.image,views=[[0,0,1,1],[0,0,.65,.65],[.35,0,1,.65],[0,.35,.65,1],[.35,.35,1,1]]
    let checked=0
    for(const [x0,y0,x1,y1]of views){
      const x=Math.floor(x0*image.width),y=Math.floor(y0*image.height),width=Math.floor(x1*image.width)-x,height=Math.floor(y1*image.height)-y
      const data=new Uint8ClampedArray(width*height*4)
      for(let row=0;row<height;row++)data.set(image.data.subarray(((y+row)*image.width+x)*4,((y+row)*image.width+x+width)*4),row*width*4)
      const input=detectorInput({data,width,height}),outputs=await run('detector',input)
      if(!outputs[0].data.every(Number.isFinite))throw new Error('人物检测结果不确定，无法确认无人背景。')
      const boxes=decodeDetector(outputs[0],input.ratio,width,height,.2);checked++
      if(boxes.length)return {empty:false,checked}
    }
    return {empty:true,checked}
  }
  if(message.type==='detect'){
    const input=detectorInput(message.image),outputs=await run('detector',input)
    return decodeDetector(outputs[0],input.ratio,message.image.width,message.image.height)
  }
  const input=poseInput(message.image,message.box),outputs=await run('pose',input)
  return decodePose(outputs[0],outputs[1],input.center,input.scale,message.image.width,message.image.height)
}
// Client sends one request at a time. Keep this queue as a second guard against
// concurrent session runs / lifecycle operations from other callers.
let queue=Promise.resolve()
self.onmessage=({data:message})=>{
  queue=queue.then(async()=>{
    currentRequest=message.id
    try{
      let result
      if(message.type==='initialize')result=await initialize(message.forceCpu)
      else if(message.type==='release'){await release();result={}}
      else{
        try{result=await infer(message)}catch(error){
          if(provider!=='webgpu')throw error
          progress({stage:'fallback',message:'显卡计算中断，正在用本机 CPU 重试。'})
          await initialize(true);result=await infer(message)
        }
      }
      self.postMessage({id:message.id,type:'result',result,provider})
    }catch(error){self.postMessage({id:message.id,type:'error',message:error.message || '本机计算失败，请重试。'})}
  })
}
