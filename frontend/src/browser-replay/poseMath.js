// Port of the attributed rtmlib YOLOX / RTMPose preprocessing and decoders.
// RGB browser pixels become BGR, matching the existing cv2 input path.
export function intersectionOverUnion(a,b) {
  const intersection = Math.max(0,Math.min(a[2],b[2])-Math.max(a[0],b[0])) * Math.max(0,Math.min(a[3],b[3])-Math.max(a[1],b[1]))
  const area = r=>Math.max(0,r[2]-r[0])*Math.max(0,r[3]-r[1])
  return intersection / Math.max(1e-9,area(a)+area(b)-intersection)
}

function sampleBgr(image, x, y, channel, border) {
  const {width,height,data} = image
  const x0=Math.floor(x),y0=Math.floor(y),dx=x-x0,dy=y-y0
  const pixel=(ix,iy)=>{
    if (border==='edge') { ix=Math.max(0,Math.min(width-1,ix)); iy=Math.max(0,Math.min(height-1,iy)) }
    return ix<0||iy<0||ix>=width||iy>=height ? 0 : data[(iy*width+ix)*4+2-channel]
  }
  return Math.round((pixel(x0,y0)*(1-dx)+pixel(x0+1,y0)*dx)*(1-dy)+(pixel(x0,y0+1)*(1-dx)+pixel(x0+1,y0+1)*dx)*dy)
}

export function detectorInput(image) {
  const size=640, ratio=Math.min(size/image.width,size/image.height)
  const rw=Math.floor(image.width*ratio),rh=Math.floor(image.height*ratio)
  const data=new Float32Array(3*size*size); data.fill(114)
  for(let c=0;c<3;c++)for(let y=0;y<rh;y++)for(let x=0;x<rw;x++)
    data[c*size*size+y*size+x]=sampleBgr(image,(x+.5)*image.width/rw-.5,(y+.5)*image.height/rh-.5,c,'edge')
  return {data,ratio,dims:[1,3,size,size]}
}

export function decodeDetector(tensor,ratio,width,height,threshold=.3) {
  const columns=tensor.dims.at(-1),rows=tensor.dims.at(-2),data=tensor.data, candidates=[]
  // The checksum-pinned detector has embedded NMS and returns packed dets.
  // Do not apply a second, different suppression rule to its native output.
  if(columns!==5)throw new Error('人物模型输出格式不匹配。')
  const add=(box,score)=>{
    box=box.map((v,i)=>Math.max(0,Math.min(i%2?height:width,v/ratio)))
    if(Number.isFinite(score)&&score>threshold&&box.every(Number.isFinite)&&box[2]-box[0]>4&&box[3]-box[1]>4)candidates.push({box,score})
  }
  for(let i=0;i<rows;i++)add(Array.from(data.slice(i*columns,i*columns+4)),data[i*columns+4])
  return candidates
}

export function poseInput(image,box) {
  if(box?.length!==4 || !box.every(Number.isFinite) || box[2]<=box[0] || box[3]<=box[1])throw new Error('人物区域无效。')
  const center=[(box[0]+box[2])/2,(box[1]+box[3])/2],scale=[(box[2]-box[0])*1.25,(box[3]-box[1])*1.25]
  if(scale[0]>scale[1]*.75)scale[1]=scale[0]/.75;else scale[0]=scale[1]*.75
  const w=288,h=384,data=new Float32Array(3*w*h),mean=[123.675,116.28,103.53],std=[58.395,57.12,57.375]
  for(let y=0;y<h;y++)for(let x=0;x<w;x++){
    // cv2 INTER_LINEAR warpAffine uses a 1/32 pixel interpolation table.
    const sx=Math.round((x/w*scale[0]+center[0]-scale[0]/2)*32)/32
    const sy=Math.round((y/h*scale[1]+center[1]-scale[1]/2)*32)/32
    for(let c=0;c<3;c++)data[c*w*h+y*w+x]=(sampleBgr(image,sx,sy,c,'zero')-mean[c])/std[c]
  }
  return {data,dims:[1,3,h,w],center,scale}
}

export function decodePose(xTensor,yTensor,center,scale,width,height) {
  const count=xTensor.dims.at(-2),wx=xTensor.dims.at(-1),wy=yTensor.dims.at(-1)
  if(count!==133||yTensor.dims.at(-2)!==133||wx!==576||wy!==768)throw new Error('骨架模型输出格式不匹配。')
  const points=[],scores=[],eligible=[]
  for(let k=0;k<count;k++){
    let mx=-Infinity,my=-Infinity,ix=0,iy=0
    for(let i=0;i<wx;i++){const v=xTensor.data[k*wx+i];if(v>mx){mx=v;ix=i}}
    for(let i=0;i<wy;i++){const v=yTensor.data[k*wy+i];if(v>my){my=v;iy=i}}
    const score=(mx+my)/2,positive=score>0
    const point=[((positive?ix:-1)/2/288*scale[0]+center[0]-scale[0]/2)/width,((positive?iy:-1)/2/384*scale[1]+center[1]-scale[1]/2)/height]
    points.push(point.map(v=>Number.isFinite(v)?v:null));scores.push(Number.isFinite(score)?score:0)
    eligible.push(Number.isFinite(score)&&score>=.5&&point.every(v=>Number.isFinite(v)&&v>0&&v<1))
  }
  return {points,scores,eligible}
}

// Explicit initial user selection; conservative source-space continuation only.
// This is not the desktop clip-level multi-person association algorithm.
export function continueTarget(detections,previous) {
  const ranked=detections.map(d=>({...d,overlap:intersectionOverUnion(d.box,previous)})).sort((a,b)=>b.overlap-a.overlap)
  if(!ranked.length||ranked[0].overlap<.2)return null
  if(ranked[1]&&ranked[1].overlap>ranked[0].overlap-.12)return null
  return ranked[0]
}
