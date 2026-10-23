// Browser port of the accepted desktop 19.2 rules. No previous-location holds.
export const IMAGE_VERSION='rotated-source-observation-v3'
export const TEMPORAL_VERSION='bidirectional-image-pose-consensus-v3'
const limbs=[7,8,9,10,17,18,19,20,21,22],temporalJoints=[7,8,9,10,13,14,15,16,17,18,19,20,21,22]
const chains=[[5,7,9],[6,8,10],[11,13,15],[12,14,16]]
const distance=(a,b)=>Math.hypot(a[0]-b[0],a[1]-b[1])
const midpoint=(a,b)=>[(a[0]+b[0])/2,(a[1]+b[1])/2]
const pixels=(pose,size)=>pose.points.map(p=>p.map((v,i)=>v*size[i]))
const finite=p=>p?.length===2&&p.every(Number.isFinite)
const c=Math.cos(Math.PI/12),s=Math.sin(Math.PI/12)

export function nativePoseInput(image,box,cv){
  const center=[(box[0]+box[2])/2,(box[1]+box[3])/2],scale=[(box[2]-box[0])*1.25,(box[3]-box[1])*1.25],w=288,h=384
  if(scale[0]>scale[1]*.75)scale[1]=scale[0]/.75;else scale[0]=scale[1]*.75
  const [x,y]=center,r=scale[0]/2,rgba=cv.matFromImageData(image),bgr=new cv.Mat(),crop=new cv.Mat()
  const source=cv.matFromArray(3,1,cv.CV_32FC2,[x,y,x,y-r,x-r,y-r]),target=cv.matFromArray(3,1,cv.CV_32FC2,[w/2,h/2,w/2,h/2-w/2,0,h/2-w/2]),matrix=cv.getAffineTransform(source,target)
  try{
    cv.cvtColor(rgba,bgr,cv.COLOR_RGBA2BGR);cv.warpAffine(bgr,crop,matrix,new cv.Size(w,h),cv.INTER_LINEAR,cv.BORDER_CONSTANT,new cv.Scalar())
    const data=new Float32Array(3*w*h),mean=[123.675,116.28,103.53],std=[58.395,57.12,57.375]
    for(let i=0;i<w*h;i++)for(let channel=0;channel<3;channel++)data[channel*w*h+i]=(crop.data[i*3+channel]-mean[channel])/std[channel]
    return {data,dims:[1,3,h,w],center,scale}
  }finally{for(const mat of [rgba,bgr,crop,source,target,matrix])mat.delete()}
}

export function rotateInput(input,cv){
  const [,,h,w]=input.dims,interleaved=new Float32Array(input.data.length),output=new Float32Array(input.data.length)
  for(let i=0;i<w*h;i++)for(let channel=0;channel<3;channel++)interleaved[i*3+channel]=input.data[channel*w*h+i]
  const source=cv.matFromArray(h,w,cv.CV_32FC3,interleaved),target=new cv.Mat(),matrix=cv.getRotationMatrix2D(new cv.Point(w/2,h/2),15,1)
  try{
    cv.warpAffine(source,target,matrix,new cv.Size(w,h),cv.INTER_LINEAR,cv.BORDER_CONSTANT,new cv.Scalar(-123.675/58.395,-116.28/57.12,-103.53/57.375))
    for(let i=0;i<w*h;i++)for(let channel=0;channel<3;channel++)output[channel*w*h+i]=target.data32F[i*3+channel]
    return {...input,data:output}
  }finally{source.delete();target.delete();matrix.delete()}
}
export function undoRotation(pose,input,size){
  const [,,h,w]=input.dims
  return {...pose,points:pose.points.map(p=>{
    const x=(p[0]*size[0]-input.center[0]+input.scale[0]/2)/input.scale[0]*w-w/2
    const y=(p[1]*size[1]-input.center[1]+input.scale[1]/2)/input.scale[1]*h-h/2
    return [((c*x-s*y+w/2)/w*input.scale[0]+input.center[0]-input.scale[0]/2)/size[0],((s*x+c*y+h/2)/h*input.scale[1]+input.center[1]-input.scale[1]/2)/size[1]]
  })}
}
export function selectImageObservation(primary,candidate,size){
  const result=structuredClone(primary),raw=pixels(primary,size),xy=pixels(candidate,size),selected=raw.map(p=>[...p]),chosen=new Set(),rejected=new Set()
  const good=i=>primary.eligible[i]===true&&finite(xy[i])&&Number.isFinite(candidate.scores[i])&&candidate.scores[i]>=.5&&xy[i].every((v,k)=>v>0&&v<size[k])
  const torso=distance(midpoint(raw[5],raw[6]),midpoint(raw[11],raw[12]))
  if(!Number.isFinite(torso)||torso<1)return result
  for(const j of limbs)if(good(j)){selected[j]=xy[j];chosen.add(j)}
  for(const [anchors,joints]of [[[5,6],[7,8,9,10]],[[11,12],[17,18,19,20,21,22]]]){
    const [a,b]=anchors,own=distance(xy[a],raw[a])+distance(xy[b],raw[b]),opposite=distance(xy[a],raw[b])+distance(xy[b],raw[a]),margin=Math.max(4,.04*torso)
    if(!good(a)||!good(b)||distance(raw[a],raw[b])<margin||opposite+margin<own)for(const j of joints)rejected.add(j)
  }
  for(const chain of chains)if(chain.slice(1).some((j,i)=>distance(selected[j],selected[chain[i]])<=0||distance(selected[j],selected[chain[i]])>3*torso))for(const j of chain.slice(1))rejected.add(j)
  for(let j=17;j<23;j++)if(distance(selected[j],selected[j<20?15:16])>Math.max(30,.65*torso))rejected.add(j)
  for(const j of rejected)chosen.delete(j)
  for(const j of chosen){result.points[j]=candidate.points[j].map(v=>Math.round(v*1e6)/1e6);result.scores[j]=candidate.scores[j]}
  result.primary_native=structuredClone(primary)
  result.image_observation_refinement={version:IMAGE_VERSION,angle_degrees:15,selected_joints:[...chosen],rejected_joints:[...rejected],primary_raw_preserved:true,candidate_raw_xy_px:xy,candidate_native_response:candidate.scores}
  return result
}

// The following math has the same thresholds as refine_triplet in desktop 19.2.
export function temporalUpdates(records,tracks,size,scale){
  const [previous,middle,next]=records,[left,right]=tracks,xy=records.map(r=>pixels(r.pose,size)),flags=records.map(r=>r.pose.eligible)
  if(records.some(r=>!Number.isFinite(r.time))||middle.time<=previous.time||next.time<=middle.time||middle.time-previous.time>.200001||next.time-middle.time>.200001||new Set(records.map(r=>r.track)).size!==1)return []
  if(flags.some(m=>[5,6,11,12].some(j=>!m[j])))return []
  const torso=distance(midpoint(xy[1][5],xy[1][6]),midpoint(xy[1][11],xy[1][12]))
  if(!Number.isFinite(torso)||torso<30)return []
  const updated=xy[1].map(p=>[...p]),updates=[]
  for(const j of temporalJoints){
    if(!flags[1][j]||!left.valid[j]||!right.valid[j])continue
    const a=left.points[j].map(v=>v/scale),b=right.points[j].map(v=>v/scale),target=midpoint(a,b),agree=distance(a,b),delta=distance(target,xy[1][j])
    if(!finite(a)||!finite(b))continue
    let mode='three_image_estimate'
    if(delta>Math.max(12,.2*torso)){
      if(j<17)continue
      const ankle=j<20?15:16
      if(flags.some(m=>!m[ankle])||distance(xy[1][j],xy[1][ankle])<=.65*torso||distance(target,xy[1][ankle])>=.35*torso||[0,2].some(i=>distance(xy[i][j],xy[i][ankle])>=.45*torso)||agree>Math.max(8,.1*torso))continue
      updated[j]=target;mode='detached_foot_detail_two_image_reconstruction'
    }else{
      if(agree>Math.max(4,.035*torso))continue
      updated[j]=xy[1][j].map((v,i)=>(v+a[i]+b[i])/3)
    }
    if(distance(updated[j],xy[1][j])<.25){updated[j]=xy[1][j];continue}
    updates.push({joint:j,xy:updated[j].map((v,i)=>Math.round(v/size[i]*1e6)/1e6),mode,neighbour_agreement_px:agree})
  }
  const rejected=new Set()
  for(const chain of chains)if(chain.slice(1).some((j,i)=>{
    const old=distance(xy[1][j],xy[1][chain[i]]),now=distance(updated[j],updated[chain[i]])
    return now<2||now>3*torso||Math.abs(now-old)>.2*torso
  }))for(const j of chain.slice(1))rejected.add(j)
  return updates.filter(u=>!rejected.has(u.joint))
}

function track(cv,previous,current,points,eligible){
  const ids=points.map((p,i)=>eligible[i]&&finite(p)?i:-1).filter(i=>i>=0),out={points:points.map(p=>[...p]),valid:points.map(()=>false)}
  if(!ids.length)return out
  const p0=cv.matFromArray(ids.length,1,cv.CV_32FC2,ids.flatMap(i=>points[i])),p1=new cv.Mat(),status=new cv.Mat(),error=new cv.Mat(),p2=new cv.Mat(),back=new cv.Mat(),backError=new cv.Mat()
  try{
    const args=[new cv.Size(21,21),3,new cv.TermCriteria(cv.TermCriteria_EPS|cv.TermCriteria_COUNT,30,.01)]
    cv.calcOpticalFlowPyrLK(previous,current,p0,p1,status,error,...args)
    for(let k=0;k<ids.length;k++)if(!Number.isFinite(p1.data32F[k*2])||!Number.isFinite(p1.data32F[k*2+1])){status.data[k]=0;p1.data32F[k*2]=p0.data32F[k*2];p1.data32F[k*2+1]=p0.data32F[k*2+1]}
    cv.calcOpticalFlowPyrLK(current,previous,p1,p2,back,backError,...args)
    ids.forEach((id,k)=>{
      const q=[p1.data32F[2*k],p1.data32F[2*k+1]],origin=[p0.data32F[2*k],p0.data32F[2*k+1]],roundtrip=[p2.data32F[2*k],p2.data32F[2*k+1]]
      out.points[id]=q;out.valid[id]=status.data[k]===1&&back.data[k]===1&&finite(q)&&finite(roundtrip)&&distance(origin,roundtrip)<=1.5&&Number.isFinite(error.data32F[k])&&error.data32F[k]<=20&&q[0]>=11&&q[0]<current.cols-11&&q[1]>=11&&q[1]<current.rows-11
    })
    return out
  }finally{for(const mat of [p0,p1,status,error,p2,back,backError])mat.delete()}
}
export class ImageDisplayWindow{
  constructor(cv){this.cv=cv;this.window=[]}
  clear(){for(const entry of this.window)entry.gray.delete();this.window=[]}
  push(image,pose,metadata){
    const cv=this.cv,size=[image.width,image.height],scale=Math.min(1,960/Math.max(...size))
    if(this.window.some(e=>e.size.some((v,i)=>v!==size[i])))this.clear()
    const rgba=cv.matFromImageData(image),gray=new cv.Mat(),small=new cv.Mat()
    try{cv.cvtColor(rgba,gray,cv.COLOR_RGBA2GRAY);cv.resize(gray,small,new cv.Size(Math.round(size[0]*scale),Math.round(size[1]*scale)))}catch(e){small.delete();throw e}finally{rgba.delete();gray.delete()}
    this.window.push({gray:small,pose,time:metadata.time,track:metadata.track,index:metadata.index,size})
    if(this.window.length>3)this.window.shift().gray.delete()
    if(this.window.length<3)return null
    const [a,b,d]=this.window,tracks=[a,d].map(entry=>track(cv,entry.gray,b.gray,pixels(entry.pose,size).map(p=>p.map(v=>v*scale)),entry.pose.eligible))
    const updates=temporalUpdates(this.window,tracks,size,scale)
    return updates.length?{index:b.index,payload:{version:TEMPORAL_VERSION,source_frame_id:b.index,coordinates:'source_image_normalized',kind:'image_supported_temporal_inference',updates}}:null
  }
}
