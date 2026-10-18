import {createReadStream} from 'node:fs'
import {mkdir,copyFile,stat,readFile,writeFile} from 'node:fs/promises'
import {createHash} from 'node:crypto'
import {fileURLToPath} from 'node:url'
import {resolve} from 'node:path'
import {MODEL_FILES,MODEL_VERSION} from './src/browser-replay/modelManifest.js'

const source=fileURLToPath(new URL('../backend/model_assets/rtmw-l-384x288/',import.meta.url))
const notice=`Climbing Assistant browser-local pose validation\n\nModels (unchanged bytes, see manifest.json):\nRTMW-L 384x288, COCO WholeBody 133 keypoints, OpenMMLab MMPose\nhttps://github.com/open-mmlab/mmpose/tree/main/projects/rtmw\nYOLOX-S HumanArt detector, distributed by OpenMMLab\nhttps://github.com/Megvii-BaseDetection/YOLOX\nOriginal downloads and archive hashes: backend/scripts/install_replay_rtmw.py\n\nPreprocessing and decoding ported from the attributed rtmlib helpers (Apache-2.0):\nhttps://github.com/Tau-J/rtmlib\nLocal changes: browser BGR sampling, tensor layout, bounds checks, typed-array decoders.\nFull license: rtmlib-LICENSE.txt\n\nONNX Runtime Web 1.30.0 (MIT), Microsoft\nhttps://github.com/microsoft/onnxruntime\nFull license: onnxruntime-LICENSE.txt\n\nThis validation page does not implement the desktop clip-level person tracker,\nwall registration, bounded-context observation provider, holds or contacts.\n`
const textAssets=new Map([
  ['/browser-models/NOTICE.txt',()=>Promise.resolve(notice+'\nVideo export: Mediabunny 1.61.6, Vanilagy and contributors (MPL-2.0).\nUnmodified source: https://registry.npmjs.org/mediabunny/-/mediabunny-1.61.6.tgz\nhttps://github.com/Vanilagy/mediabunny\nFull license: mediabunny-LICENSE.txt\n')],
  ['/browser-models/mediabunny-LICENSE.txt',()=>readFile(new URL('./browser-licenses/mediabunny-LICENSE.txt',import.meta.url),'utf8')],
  ['/browser-models/rtmlib-LICENSE.txt',()=>readFile(new URL('../backend/vendor/rtmlib/LICENSE',import.meta.url),'utf8')],
  ['/browser-models/onnxruntime-LICENSE.txt',()=>readFile(new URL('./browser-licenses/onnxruntime-LICENSE.txt',import.meta.url),'utf8')],
  ['/browser-models/model-Apache-2.0.txt',()=>readFile(new URL('../backend/vendor/rtmlib/LICENSE',import.meta.url),'utf8')],
  [`/browser-models/${MODEL_VERSION}/manifest.json`,()=>readFile(resolve(source,'manifest.json'),'utf8')],
  ['/browser-fonts/NOTICE.txt',()=>readFile(new URL('./public/fonts/NOTICE.md',import.meta.url),'utf8')],
])
const fontFile=fileURLToPath(new URL('./public/fonts/MiSans-Regular.woff2',import.meta.url))
export default function browserModelAssets({copy=false}={}) {
  let output,command
  return {
    name:'climbing-browser-model-assets',
    configResolved(config){output=resolve(config.root,config.build.outDir);command=config.command},
    configureServer(server){
      server.middlewares.use(async(req,res,next)=>{
        const path=req.url?.split('?')[0],file=MODEL_FILES.find(f=>f.url===path)
        if(!file&&!textAssets.has(path)&&path!=='/browser-fonts/MiSans-Regular.woff2')return next()
        if(!['GET','HEAD'].includes(req.method)){res.statusCode=405;res.end();return}
        try{
          if(file||path==='/browser-fonts/MiSans-Regular.woff2'){
            const local=file?resolve(source,file.file):fontFile,info=await stat(local)
            if(file&&info.size!==file.bytes)throw new Error('Model size mismatch')
            res.setHeader('Content-Type',file?'application/octet-stream':'font/woff2');res.setHeader('Content-Length',info.size)
            res.setHeader('Cache-Control','public, max-age=31536000, immutable')
            if(req.method==='HEAD'){res.end();return}
            const stream=createReadStream(local);stream.on('error',()=>res.destroy());res.on('close',()=>stream.destroy());stream.pipe(res)
          }else{res.setHeader('Content-Type',path.endsWith('.json')?'application/json':'text/plain; charset=utf-8');res.end(req.method==='HEAD'?'':await textAssets.get(path)())}
        }catch{res.statusCode=503;res.end('Local model resources unavailable')}
      })
    },
    async closeBundle(){
      if(!copy||command!=='build')return
      for(const file of MODEL_FILES){
        const local=resolve(source,file.file),hash=createHash('sha256')
        for await(const chunk of createReadStream(local))hash.update(chunk)
        if((await stat(local)).size!==file.bytes||hash.digest('hex')!==file.sha256)throw new Error(`Model checksum mismatch: ${file.file}`)
        const target=resolve(output,`.${file.url}`);await mkdir(resolve(target,'..'),{recursive:true});await copyFile(local,target)
      }
      for(const [path,read]of textAssets){const target=resolve(output,`.${path}`);await mkdir(resolve(target,'..'),{recursive:true});await writeFile(target,await read())}
      await copyFile(fontFile,resolve(output,'browser-fonts/MiSans-Regular.woff2'))
    },
  }
}
