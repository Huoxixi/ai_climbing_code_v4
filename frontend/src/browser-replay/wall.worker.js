// OpenCV is bundled locally and loaded only for wall preparation. The worker
// owns all native Mats and deletes them on replacement/completion/cancellation.
import cvModule from '@techstark/opencv-js'
let cv,reference
const dispose=objects=>objects.forEach(o=>o?.delete())
function features(image,boxes=[]){
  const rgba=cv.matFromImageData(image),gray=new cv.Mat(),mask=new cv.Mat(image.height,image.width,cv.CV_8UC1,new cv.Scalar(255)),points=new cv.KeyPointVector(),descriptors=new cv.Mat(),orb=new cv.ORB()
  try{
    cv.cvtColor(rgba,gray,cv.COLOR_RGBA2GRAY)
    for(const b of boxes){
      const x0=Math.max(0,Math.floor((b[0]-.025)*image.width)),y0=Math.max(0,Math.floor((b[1]-.025)*image.height)),x1=Math.min(image.width-1,Math.ceil((b[2]+.025)*image.width)),y1=Math.min(image.height-1,Math.ceil((b[3]+.025)*image.height))
      if(x1>x0&&y1>y0)cv.rectangle(mask,new cv.Point(x0,y0),new cv.Point(x1,y1),new cv.Scalar(0),-1)
    }
    orb.setMaxFeatures(2400);orb.detectAndCompute(gray,mask,points,descriptors)
    let brightness=0,variance=0,sharpness=0,n=0
    for(let y=1;y<gray.rows-1;y+=2)for(let x=1;x<gray.cols-1;x+=2){
      const i=y*gray.cols+x,v=gray.data[i],lap=gray.data[i-1]+gray.data[i+1]+gray.data[i-gray.cols]+gray.data[i+gray.cols]-4*v
      brightness+=v;variance+=v*v;sharpness+=lap*lap;n++
    }
    const quality={brightness:brightness/n,contrast:Math.sqrt(Math.max(0,variance/n-(brightness/n)**2)),sharpness:sharpness/n,features:points.size()}
    return {points,descriptors,width:image.width,height:image.height,quality}
  }catch(error){dispose([points,descriptors]);throw error}
  finally{dispose([rgba,gray,mask,orb])}
}
function project(m,x,y){const d=m[6]*x+m[7]*y+m[8];return [(m[0]*x+m[1]*y+m[2])/d,(m[3]*x+m[4]*y+m[5])/d]}
function register(image,boxes){
  if(!reference)throw new Error('墙面参考尚未准备。')
  const current=features(image,boxes),matcher=new cv.BFMatcher(cv.NORM_HAMMING,false),pairs=new cv.DMatchVectorVector(),objects=[]
  try{
    if(current.descriptors.rows<24||reference.descriptors.rows<24)return {valid:false,reason:'texture'}
    matcher.knnMatch(current.descriptors,reference.descriptors,pairs,2)
    const matches=[],used=new Set()
    for(let i=0;i<pairs.size();i++){
      const pair=pairs.get(i)
      try{if(pair.size()<2)continue;const a=pair.get(0),b=pair.get(1);if(a.distance<.72*b.distance&&!used.has(a.trainIdx)){matches.push(a);used.add(a.trainIdx)}}finally{pair.delete()}
    }
    if(matches.length<24)return {valid:false,reason:'matches',matches:matches.length}
    const source=[],target=[]
    for(const m of matches){const a=current.points.get(m.queryIdx).pt,b=reference.points.get(m.trainIdx).pt;source.push(a.x,a.y);target.push(b.x,b.y)}
    const src=cv.matFromArray(matches.length,1,cv.CV_32FC2,source),dst=cv.matFromArray(matches.length,1,cv.CV_32FC2,target),mask=new cv.Mat();objects.push(src,dst,mask)
    const h=cv.findHomography(src,dst,cv.RANSAC,3,mask,2000,.995);objects.push(h)
    if(h.empty())return {valid:false,reason:'homography'}
    const m=Array.from(h.data64F),errors=[],xs=[],ys=[],cells=new Set()
    for(let i=0;i<matches.length;i++)if(mask.data[i]){
      const x=source[i*2],y=source[i*2+1],p=project(m,x,y)
      errors.push(Math.hypot(p[0]-target[i*2],p[1]-target[i*2+1]));xs.push(x);ys.push(y);cells.add(Math.floor(x/image.width*4)+4*Math.floor(y/image.height*4))
    }
    errors.sort((a,b)=>a-b)
    const diagnostics={matches:matches.length,inliers:errors.length,ratio:errors.length/matches.length,median:errors[Math.floor(errors.length/2)]??Infinity,p90:errors[Math.floor(errors.length*.9)]??Infinity,coverageX:(Math.max(...xs)-Math.min(...xs))/image.width,coverageY:(Math.max(...ys)-Math.min(...ys))/image.height,cells:cells.size}
    const corners=[[0,0],[image.width,0],[image.width,image.height],[0,image.height]].map(p=>project(m,...p))
    const area=corners.reduce((sum,p,i)=>{const q=corners[(i+1)%4];return sum+p[0]*q[1]-q[0]*p[1]},0)/2/(reference.width*reference.height)
    const inside=corners.every(p=>p.every(Number.isFinite)&&p[0]>-reference.width*.5&&p[0]<reference.width*1.5&&p[1]>-reference.height*.5&&p[1]<reference.height*1.5)
    const valid=diagnostics.inliers>=20&&diagnostics.ratio>=.5&&diagnostics.median<=1.5&&diagnostics.p90<=3&&diagnostics.coverageX>=.35&&diagnostics.coverageY>=.35&&diagnostics.cells>=6&&inside&&area>.55&&area<1.8
    // Normalized source -> normalized selected background, independent of output size.
    const matrix=[m[0]*image.width/reference.width,m[1]*image.height/reference.width,m[2]/reference.width,m[3]*image.width/reference.height,m[4]*image.height/reference.height,m[5]/reference.height,m[6]*image.width,m[7]*image.height,m[8]]
    const displacement=Math.max(...corners.map((p,i)=>Math.hypot(p[0]-[[0,0],[reference.width,0],[reference.width,reference.height],[0,reference.height]][i][0],p[1]-[[0,0],[reference.width,0],[reference.width,reference.height],[0,reference.height]][i][1])))
    return {valid,matrix:valid?matrix:null,diagnostics,displacement,reason:valid?'':'alignment'}
  }finally{dispose([current.points,current.descriptors,matcher,pairs,...objects])}
}
let queue=Promise.resolve()
self.onmessage=({data})=>{queue=queue.then(async()=>{
  try{
    cv=await cvModule
    let result
    if(data.type==='reference'){
      if(reference)dispose([reference.points,reference.descriptors])
      reference=features(data.image);result=reference.quality
    }else result=register(data.image,data.boxes||[])
    self.postMessage({id:data.id,result})
  }catch(e){self.postMessage({id:data.id,error:e.message||'墙面配准失败。'})}
})}
